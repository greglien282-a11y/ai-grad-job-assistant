"""Real PostgreSQL HTTP/concurrency/privacy regressions; synthetic data only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hmac
import secrets
from threading import Barrier, Event
import time
from uuid import UUID
from pathlib import Path
import json

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from test_http_api import api, create, patch
from app import facts, idempotency as idem
from app.models import ExperienceSession, ExperienceProject, ConversationTurn, ExperienceFact, FactChange, FactSource, FactEvidence, IdempotencyOperation, utcnow

ROOT = '/api/v1/experience'
BODY = {'raw_input': 'Synthetic 中文 project 🚀\nOnly invented experience.'}


def test_shared_browser_python_crypto_vector():
    v=json.loads((Path(__file__).parents[2]/'shared/idempotency-vector.json').read_text(encoding='utf-8'))
    proof=idem.encode(hmac.digest(v['token'].encode(),idem.message(v['kind'],v['scope'],v['issued'],v['nonce']),'sha256'))
    assert f'v1.{v["issued"]}.{v["nonce"]}.{proof}'==v['key']
    key=idem.OperationKey('',utcnow(),v['kind'],v['scope'])
    assert idem.request_tag(key,v['token'],v['body'])==v['bodyTag']


def headers(kind='create_session', scope='global', token=None, issued=None):
    token = token or idem.encode(secrets.token_bytes(32))
    issued = int(utcnow().timestamp()) if issued is None else issued
    nonce = idem.encode(secrets.token_bytes(32))
    proof = idem.encode(hmac.digest(token.encode(), idem.message(kind, scope, issued, nonce), 'sha256'))
    return {'Authorization': 'Bearer ' + token, 'Idempotency-Key': f'v1.{issued}.{nonce}.{proof}'}, token


def count(factory, model):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model))


def wait_for_database_wait(factory, locktype):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with factory() as db:
            waiting = db.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted AND locktype=:kind AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"), {'kind': locktype})
        if waiting:
            return
        time.sleep(.02)
    raise AssertionError('Expected real PostgreSQL lock wait was not observed')


def start(client):
    h, token = headers()
    response = client.post(ROOT + '/sessions', headers=h, json=BODY)
    assert response.status_code == 201
    return response.json(), h, token


def test_receipt_recovery_payload_authorization_and_legacy(api, caplog):
    client, factory = api
    h, token = headers()
    recovery = ROOT + '/session-creations/recovery'
    missing = client.get(recovery, headers=h)
    assert missing.status_code == 404 and missing.json()['error']['code'] == 'idempotency_creation_not_found'
    assert count(factory, IdempotencyOperation) == count(factory, ExperienceSession) == 0
    data, h, token = start(client)
    replay = client.post(ROOT + '/sessions', headers=h, json=BODY)
    recovered = client.get(recovery, headers=h)
    assert replay.status_code == 201 and recovered.status_code == 200
    assert replay.headers['idempotency-replayed'] == recovered.headers['idempotency-replayed'] == 'true'
    assert recovered.json()['session_id'] == data['session_id']
    token_matches = secrets.compare_digest(recovered.json()['access_token'], token)
    assert token_matches
    assert count(factory, ExperienceSession) == count(factory, IdempotencyOperation) == 1
    changed = client.post(ROOT + '/sessions', headers=h, json={'raw_input': 'Synthetic different body'})
    assert changed.status_code == 409 and changed.json()['error']['code'] == 'idempotency_payload_mismatch'
    wrong = {**h, 'Authorization': 'Bearer ' + idem.encode(b'x' * 32)}
    assert client.get(recovery, headers=wrong).status_code == 401
    assert client.get(recovery, headers={'Idempotency-Key': h['Idempotency-Key']}).status_code == 401
    duplicated = [(k,v) for k,v in h.items()] + [('Idempotency-Key',h['Idempotency-Key'])]
    assert client.get(recovery, headers=duplicated).status_code == 422
    leaked = token in caplog.text or h['Idempotency-Key'] in caplog.text
    assert not leaked
    legacy = client.post(ROOT + '/sessions', headers={'Authorization': h['Authorization']}, json=BODY)
    assert legacy.status_code == 201
    reused = secrets.compare_digest(legacy.json()['access_token'], token)
    assert not reused and count(factory, IdempotencyOperation) == 1


@pytest.mark.parametrize('offset,code,status', [(-86400,'idempotency_key_expired',410),(301,'idempotency_clock_skew',422)])
def test_deadline_unknown_key_is_not_a_new_operation(api, offset, code, status):
    client, factory = api
    h, _ = headers(issued=int(utcnow().timestamp()) + offset)
    result = client.post(ROOT + '/sessions', headers=h, json=BODY)
    assert result.status_code == status and result.json()['error']['code'] == code
    assert count(factory, ExperienceSession) == 0


@pytest.mark.parametrize('value', ['', 'v1.invalid', 'x'*129, 'v1.1700000000.'+'A'*43+'.'+'A'*43+'='])
def test_invalid_key_is_fail_closed(api, value):
    client, factory = api
    h, _ = headers(); h['Idempotency-Key'] = value
    assert client.post(ROOT + '/sessions', headers=h, json=BODY).status_code == 422
    assert count(factory, ExperienceSession) == 0


def test_current_fact_source_end_and_deleted_receipt_privacy(api):
    client, factory = api
    data, creation, token = start(client)
    sid, pid = data['session_id'], data['project_id']
    turn_h, _ = headers('add_turn', 'session:' + sid, token)
    turn_url = ROOT + f'/sessions/{sid}/turns'
    turn_body = {'content': 'Synthetic A own source'}
    turn = client.post(turn_url, headers=turn_h, json=turn_body).json()
    assert client.post(turn_url, headers=turn_h, json=turn_body).json()['id'] == turn['id']
    fact_h, _ = headers('add_fact', 'project:' + pid, token)
    fact_url = ROOT + f'/projects/{pid}/facts'
    fact_body = {'statement': 'Synthetic A', 'source_turn_ids': [turn['id']]}
    fact = client.post(fact_url, headers=fact_h, json=fact_body).json()
    auth = {'Authorization': creation['Authorization']}
    fact = patch(client, fact, auth, 'confirm').json()
    fact = patch(client, fact, auth, 'edit', statement='Synthetic B').json()
    fact = patch(client, fact, auth, 'confirm').json()
    fact = patch(client, fact, auth, 'verify_material', material_reference='Synthetic report', basis='Synthetic user comparison').json()
    before = count(factory, FactChange)
    current = client.post(fact_url, headers=fact_h, json=fact_body).json()
    assert current['version'] == 5 and current['statement'] == 'Synthetic B'
    assert current['source_kind'] == 'user_edit' and current['source_turn_ids'] == []
    assert current['original_source_turn_ids'] == [turn['id']]
    assert count(factory, FactChange) == before and count(factory, FactSource) == 1
    other, other_auth = create(client)
    forged, _ = headers('add_fact', 'project:' + pid, other['access_token'])
    assert client.post(fact_url, headers=forged, json=fact_body).status_code == 404
    assert client.post(ROOT + f'/sessions/{sid}/end', headers=auth).status_code == 200
    assert client.post(fact_url, headers=fact_h, json=fact_body).status_code == 201
    assert client.get(ROOT + '/session-creations/recovery', headers=creation).json()['status'] == 'ended'
    new_h, _ = headers('add_turn', 'session:' + sid, token)
    assert client.post(turn_url, headers=new_h, json=turn_body).status_code == 409
    assert client.delete(ROOT + f'/sessions/{sid}', headers=auth).status_code == 204
    assert client.post(ROOT + '/sessions', headers=creation, json=BODY).status_code == 410
    assert client.get(ROOT + '/session-creations/recovery', headers=creation).json()['error']['code'] == 'idempotency_resource_deleted'
    wrong = {**creation, 'Authorization': 'Bearer ' + idem.encode(b'z' * 32)}
    assert client.get(ROOT + '/session-creations/recovery', headers=wrong).status_code == 401
    assert client.post(fact_url, headers=fact_h, json=fact_body).status_code == 404
    with factory() as db:
        rows = db.scalars(select(IdempotencyOperation)).all()
        assert len(rows) == 3
        for row in rows:
            assert row.state == 'deleted' and all(getattr(row,f) is None for f in idem.FIELDS)
        assert db.scalar(select(func.count()).select_from(ExperienceSession)) == 1
        for model in (ExperienceFact, FactChange, FactSource, FactEvidence):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert client.get(ROOT + f'/sessions/{other["session_id"]}', headers=other_auth).status_code == 200


def test_concurrent_create_and_different_payload(api):
    client, factory = api
    h, _ = headers(); barrier = Barrier(6)
    def post(index):
        barrier.wait(timeout=10)
        body = BODY if index < 5 else {'raw_input': 'Synthetic competitor'}
        response = client.post(ROOT + '/sessions', headers=h, json=body)
        return response.status_code, response.json().get('session_id')
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(post,range(6)))
    successes = [sid for status,sid in results if status == 201]
    assert len(set(successes)) == 1 and len(successes) in (1,5)
    assert all(status in (201,409) for status,_ in results)
    for model in (ExperienceSession, ExperienceProject, ConversationTurn, IdempotencyOperation):
        assert count(factory,model) == 1


def test_concurrent_turn_fact_single_side_effect(api):
    client, factory = api
    data, _, token = start(client)
    for kind,scope,url,body,model in [
        ('add_turn','session:'+data['session_id'],ROOT+f'/sessions/{data["session_id"]}/turns',{'content':'Synthetic answer'},ConversationTurn),
        ('add_fact','project:'+data['project_id'],ROOT+f'/projects/{data["project_id"]}/facts',{'statement':'Synthetic statement','source_turn_ids':[data['initial_turn_id']]},ExperienceFact),
    ]:
        h,_ = headers(kind,scope,token); barrier=Barrier(4)
        def post(_):
            barrier.wait(timeout=10)
            r=client.post(url,headers=h,json=body)
            assert r.status_code == 201
            return r.json()['id']
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids=list(pool.map(post,range(4)))
        assert len(set(ids))==1
    assert count(factory,ConversationTurn)==2
    assert count(factory,ExperienceFact)==count(factory,FactChange)==count(factory,FactSource)==1


def test_recovery_waits_for_real_commit_and_partial_failure_rolls_back(api, monkeypatch):
    client,factory=api
    h,_=headers(); entered,release=Event(),Event(); original=idem.remember
    def delayed(*args,**kwargs):
        original(*args,**kwargs); entered.set()
        assert release.wait(timeout=10)
    monkeypatch.setattr(idem,'remember',delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing=pool.submit(client.post,ROOT+'/sessions',headers=h,json=BODY)
        assert entered.wait(timeout=10)
        reading=pool.submit(client.get,ROOT+'/session-creations/recovery',headers=h)
        try:
            wait_for_database_wait(factory, 'advisory')
            assert not reading.done()
        finally:
            release.set()
        assert writing.result(timeout=10).status_code==201
        assert reading.result(timeout=10).status_code==200
    monkeypatch.setattr(idem,'remember',original)
    h2,_=headers()
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise idem.IdempotencyError(503,'idempotency_busy')
    monkeypatch.setattr(idem,'remember',fail)
    assert client.post(ROOT+'/sessions',headers=h2,json=BODY).status_code==503
    assert count(factory,ExperienceSession)==count(factory,IdempotencyOperation)==1
    monkeypatch.setattr(idem,'remember',original)
    assert client.post(ROOT+'/sessions',headers=h2,json=BODY).status_code==201


def test_expiry_cleanup_and_delete_replay_race(api, monkeypatch):
    client,factory=api
    data,h,token=start(client)
    sid=data['session_id']; ready=Event()
    # Parent lock represents a real DELETE transaction, while replay waits for it.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with factory() as db,db.begin():
            record=facts.authorize(db,UUID(sid),token,lock=True)
            from app import experience_api
            original_receipt=experience_api.creation_receipt
            def observed(*args,**kwargs):
                ready.set()
                return original_receipt(*args,**kwargs)
            monkeypatch.setattr(experience_api,'creation_receipt',observed)
            def replay():
                return client.post(ROOT+'/sessions',headers=h,json=BODY)
            future=pool.submit(replay); assert ready.wait(timeout=5)
            idem.erase_receipts(db,record.id); db.delete(record); db.flush()
        assert future.result(timeout=10).status_code==410
    real_now=utcnow()
    monkeypatch.setattr(idem,'utcnow',lambda:real_now+timedelta(hours=25))
    assert client.post(ROOT+'/sessions',headers=h,json=BODY).status_code==410
    with factory() as db,db.begin():
        assert idem.cleanup(db)==1
    assert client.get(ROOT+'/session-creations/recovery',headers=h).status_code==410
    assert count(factory,IdempotencyOperation)==count(factory,ExperienceSession)==0


def test_deadline_rechecked_before_commit_and_tombstone_constraint(api,monkeypatch):
    client,factory=api; h,_=headers(); original=idem.remember
    def expire(*args,**kwargs):
        original(*args,**kwargs)
        monkeypatch.setattr(idem,'utcnow',lambda:utcnow()+timedelta(hours=25))
    monkeypatch.setattr(idem,'remember',expire)
    assert client.post(ROOT+'/sessions',headers=h,json=BODY).status_code==410
    assert count(factory,ExperienceSession)==0
    with factory() as db:
        with pytest.raises(IntegrityError),db.begin():
            db.add(IdempotencyOperation(key_digest='0'*64,state='deleted',expires_at=utcnow(),request_tag='1'*64))
            db.flush()


def test_real_advisory_timeout_is_safe(api):
    client,factory=api; h,token=headers()
    key=idem.parse(h['Idempotency-Key'],token,'create_session','global')
    with factory() as db,db.begin():
        idem.lock(db,key)
        with ThreadPoolExecutor(max_workers=1) as pool:
            response=pool.submit(client.post,ROOT+'/sessions',headers=h,json=BODY).result(timeout=10)
        assert response.status_code==503 and response.json()['error']['code']=='idempotency_busy'
        assert response.headers['retry-after']=='1'
        revealed=token in response.text or h['Idempotency-Key'] in response.text
        assert not revealed
    assert count(factory,ExperienceSession)==0


def test_cleanup_preserves_business_and_reports_failure(api,monkeypatch,capsys):
    from app import cleanup_idempotency as cli
    client,factory=api
    data,h,_=start(client)
    old=utcnow()-timedelta(hours=1)
    with factory() as db,db.begin():
        row=db.scalar(select(IdempotencyOperation)); row.expires_at=old
    monkeypatch.setattr(cli,'build_engine',lambda:factory.kw['bind'])
    cli.run()
    output=capsys.readouterr().out
    assert 'removed: 1' in output and 'oldest expiration:' in output
    assert count(factory,ExperienceSession)==1 and count(factory,IdempotencyOperation)==0
    auth={'Authorization':h['Authorization']}
    assert client.get(ROOT+f'/sessions/{data["session_id"]}',headers=auth).status_code==200
    def broken(): raise RuntimeError('SYNTHETIC_PRIVATE_CONNECTION')
    monkeypatch.setattr(cli,'build_engine',broken)
    with pytest.raises(SystemExit) as caught:
        cli.main()
    message=str(caught.value)
    assert 'monitoring required' in message and 'SYNTHETIC_PRIVATE_CONNECTION' not in message
