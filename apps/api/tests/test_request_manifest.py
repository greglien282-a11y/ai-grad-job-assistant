"""0012 + synthetic-only body persistence, real processes and lock races."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from threading import Event
from uuid import UUID,uuid4

from alembic import command
from alembic.script import ScriptDirectory
import httpx
import pytest
from sqlalchemy import event,inspect,select,text
from sqlalchemy.exc import DBAPIError

from test_http_api import api
from test_deepseek_mining_integration import offline_guard,test_database_only
from test_prepared_mining_request import env,prepared
from test_mining_paid_binding import binding
from test_deepseek_bridge import role_capability
from app import facts,mining
from app.experience_api import delete_session
from app.models import ExperienceSession,ExperienceFact,MiningRun,utcnow
from app.paid_models import PaidFunding,PaidCall
from app.mining_paid_models import MiningPaidIdentity,MiningPaidPlan,MiningPaidBinding
from app.request_manifest_models import RequestManifest,RequestManifestTombstone,IDENTITY_FIELDS
from app.request_manifest import ManifestError,manifest_record,persist_metadata,verify_recovered,purge_expired_tombstones
from app.prepared_mining_request import prepare_request,sha,strict_json
from app.mining_request_snapshot import read_snapshot
from app.mining_request_admission import admit_offline
from app.cost_ledger import canonical
from app.offline_output_contract import envelope
from app.deepseek_contract import decode_official
from app.mining_validation import validate_context_v2
from app.mining_context import MiningContext
from offline_prepared_mining import start,output,frozen
from offline_manifest_store import install,put,recover

OLD='0011_mining_paid_metadata'
NEW='0012_request_manifest'
TABLES=('mining_request_manifests','mining_request_tombstones')


@pytest.fixture
def stored(prepared):
    e,rid,request,current=prepared
    with e.factory.begin() as db:
        install(db)
        record=put(db,current,request)
    return e,rid,request,current,record


def load(stored,**change):
    e,rid,_,current,_=stored
    args=dict(sid=e.sid,token=e.token,rid=rid,root=current.root_run_id,operation=current.operation_hash)
    args.update(change)
    with e.factory.begin() as db: return recover(db,**args)


def worker(e,rid,current,mode):
    with e.factory() as db: schema=db.scalar(text('SELECT current_schema()'))
    child_env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR','TEMP','TMP') if k in os.environ}
    child_env.update(TEST_DATABASE_URL=os.environ['TEST_DATABASE_URL'],
        DATABASE_URL=os.environ['TEST_DATABASE_URL'],PYTHONIOENCODING='utf-8')
    return subprocess.run([sys.executable,str(Path(__file__).with_name('manifest_process_worker.py'))],
        input=json.dumps(dict(mode=mode,schema=schema,sid=str(e.sid),token=e.token,rid=str(rid),
            root=str(current.root_run_id),operation=current.operation_hash)),text=True,capture_output=True,
        timeout=30,env=child_env)


def test_atomic_original_bytes_and_repeat_read_never_rebuild_or_send(stored,monkeypatch):
    e,rid,request,current,record=stored
    def forbidden(*a,**k): raise AssertionError('Must not rebuild or send')
    from app import model_adapter,prepared_mining_request,mining_context
    monkeypatch.setattr(model_adapter.Adapter,'build_request',forbidden)
    monkeypatch.setattr(prepared_mining_request,'prepare_request',forbidden)
    monkeypatch.setattr(mining_context,'build_context',forbidden)
    monkeypatch.setattr(httpx.MockTransport,'handle_request',forbidden)
    for _ in range(3):
        result=load(stored)
        assert result.request==request and result.request.body==request.body
        assert result.recovered_and_verified and not result.paid_authorized and not result.dispatch_permitted
        assert not hasattr(result,'offline_contract_valid')
        assert '我编写' not in repr(result)
    with e.factory.begin() as db:
        again=put(db,current,request)
        assert again==record
        assert db.scalar(text('SELECT count(*) FROM mining_request_manifests'))==1
        assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==1
        assert db.scalar(select(PaidCall)) is None
        money=db.get(PaidFunding,1)
        assert money.ceiling==money.held==money.spent==0


@pytest.mark.parametrize('mode,exit_code,records',[('before_commit',41,0),('after_commit',42,1)])
def test_abrupt_real_process_exit_and_new_process_recovery(prepared,mode,exit_code,records):
    e,rid,request,current=prepared
    with e.factory.begin() as db: install(db)
    crashed=worker(e,rid,current,mode)
    assert crashed.returncode==exit_code and crashed.stdout=='' and crashed.stderr==''
    with e.factory() as db:
        assert db.scalar(text('SELECT count(*) FROM mining_request_manifests'))==records
        assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==records
    restarted=worker(e,rid,current,'recover')
    if records:
        assert restarted.returncode==0 and restarted.stderr==''
        assert json.loads(restarted.stdout)==dict(sha=request.request_sha,verified=True,paid_authorized=False,dispatch_permitted=False)
    else:
        assert restarted.returncode==3 and restarted.stdout.strip()=='OFFLINE_MANIFEST_WORKER_STOPPED'


def test_body_failure_rolls_back_manifest_and_payload(prepared):
    e,_,_,current=prepared
    with e.factory.begin() as db: install(db)
    class SimulatedFailure(Exception): pass
    def fail(): raise SimulatedFailure()
    with pytest.raises(SimulatedFailure):
        with e.factory.begin() as db: put(db,current,prepared[2],crash_at=fail)
    with e.factory() as db:
        assert db.scalar(text('SELECT count(*) FROM mining_request_manifests'))==0
        assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==0


def test_concurrent_same_root_commits_one_manifest(prepared):
    e,rid,request,current=prepared
    with e.factory.begin() as db: install(db)
    def freeze():
        with e.factory.begin() as db: return put(db,current,request)
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:freeze(),range(2)))
    assert results[0]==results[1]
    with e.factory() as db:
        assert db.scalar(text('SELECT count(*) FROM mining_request_manifests'))==1
        assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==1
        assert db.scalar(select(PaidCall)) is None


@pytest.mark.parametrize('field',['sid','token','rid','root','operation'])
def test_scope_and_root_cannot_be_swapped(stored,field):
    value='synthetic-invalid-token' if field=='token' else sha(b'other') if field=='operation' else uuid4()
    with pytest.raises(ManifestError): load(stored,**{field:value})


def test_other_real_session_cannot_read_manifest(stored,api):
    e,_,_,_,_=stored
    response=e.client.post('/api/v1/experience/sessions',json={'raw_input':'合成：我编写了另一项校验。'})
    data=response.json()
    with pytest.raises(ManifestError): load(stored,sid=UUID(data['session_id']),token=data['access_token'])


def test_other_actual_run_and_root_retry_cannot_replace_manifest(stored):
    e,rid,request,current,record=stored
    mining.fail(e.factory,e.sid,e.token,rid,'unknown','provider_outcome_unknown')
    other,_,_=start(e,retry_of=rid,confirm_retry=True)
    with pytest.raises(ManifestError): load(stored,rid=other)
    from app.prepared_mining_request import RequestContractError
    with pytest.raises(RequestContractError,match='dynamic_root_already_bound'):
        read_snapshot(e.factory,e.sid,e.token,other)
    with e.factory() as db: assert manifest_record(db.get(RequestManifest,rid))==record


@pytest.mark.parametrize('fault',['append','truncate','invalid_utf8','missing'])
def test_corrupt_or_missing_stored_bytes_fail_closed(stored,fault):
    e,rid,request,_,_=stored
    with e.factory.begin() as db:
        if fault=='missing': db.execute(text('DELETE FROM test_synthetic_request_bodies WHERE run_id=:r'),{'r':rid})
        else:
            body={'append':request.body+b'x','truncate':request.body[:20],'invalid_utf8':b'\xff'}[fault]
            db.execute(text('UPDATE test_synthetic_request_bodies SET body=:b WHERE run_id=:r'),{'r':rid,'b':body})
    with pytest.raises(ManifestError): load(stored)


@pytest.mark.parametrize('field',IDENTITY_FIELDS)
def test_manifest_identity_and_configuration_tamper_rejected(stored,field):
    e,rid,request,current,record=stored
    raw=strict_json(record.metadata_bytes)
    if field in ('context_revision','output_cap','manifest_version','contract_version'): raw[field]+=1
    elif field.endswith('_id'): raw[field]=str(uuid4())
    elif field.endswith(('_sha','_hash')) or field=='root_request_tag': raw[field]='f'*64
    else: raw[field]='unreviewed-change'
    modified=replace(record,metadata_bytes=canonical(raw).encode('utf8'))
    with pytest.raises(ManifestError):
        verify_recovered(modified,request.body,lookup=(e.sid,rid,current.root_run_id,current.operation_hash))


@pytest.mark.parametrize('field',['created_at','expires_at','storage_state','metadata_bytes'])
def test_invalid_storage_record_rejected(stored,field):
    e,rid,request,current,record=stored
    value={'created_at':record.expires_at,'expires_at':utcnow()-timedelta(seconds=1),
        'storage_state':'dispatch_permitted','metadata_bytes':b'{'}[field]
    with pytest.raises(ManifestError):
        verify_recovered(replace(record,**{field:value}),request.body,lookup=(e.sid,rid,current.root_run_id,current.operation_hash))


@pytest.mark.parametrize('change',['stop','end','delete','revision','lease','unknown','stale','completed'])
def test_recovery_does_not_upgrade_changed_business_state(stored,change):
    e,rid,_,_,_=stored
    if change=='delete':
        assert e.client.delete('/api/v1/experience/sessions/'+str(e.sid),headers={'Authorization':'Bearer '+e.token}).status_code==204
    else:
        with e.factory.begin() as db:
            if change=='stop': db.get(ExperienceSession,e.sid).mining_status='stopped'
            elif change=='end': facts.end_session(db,e.sid,e.token)
            elif change=='revision': facts.add_turn(db,e.sid,e.token,'合成：我补充了说明。')
            elif change=='lease': db.get(MiningRun,rid).lease_until=utcnow()-timedelta(seconds=1)
            else: db.get(MiningRun,rid).state=change
    with pytest.raises(ManifestError): load(stored)


def test_recovered_archive_not_current_business_permission(stored):
    e,rid,request,_,_=stored
    original=load(stored)
    with e.factory.begin() as db: facts.add_turn(db,e.sid,e.token,'合成：我修改了上下文。')
    from app.prepared_mining_request import RequestContractError
    with pytest.raises(RequestContractError): admit_offline(e.factory,e.sid,e.token,rid,original.request)
    assert original.request.body==request.body and not original.dispatch_permitted


@pytest.mark.parametrize('state',['reserved','sent','unknown','response_received','reconciled'])
def test_recovery_never_changes_synthetic_billing_liability(stored,state):
    e,_,request,_,_=stored
    with e.factory.begin() as db:
        plan=db.scalar(select(MiningPaidPlan))
        # Deliberately synthetic liability fixture, not an authorization path.
        db.add(PaidCall(id=uuid4(),grant_id=plan.grant_id,operation_hash=plan.operation_hash,
            request_hash=request.request_sha,policy_hash=plan.policy_sha,batch_tag='synthetic-liability-only',
            provider=plan.provider,model=plan.model,state=state,reserved='.01',lease_until=utcnow()+timedelta(minutes=1)))
    with e.factory() as db:
        before=db.execute(text('SELECT * FROM paid_calls')).all(),db.execute(text('SELECT * FROM paid_funding')).all()
    for _ in range(2): assert load(stored).recovered_and_verified
    with e.factory() as db:
        after=db.execute(text('SELECT * FROM paid_calls')).all(),db.execute(text('SELECT * FROM paid_funding')).all()
    assert before==after


def test_delete_erases_body_and_scopes_leaves_only_expiring_tombstone(stored):
    e,rid,request,current,_=stored
    assert e.client.delete('/api/v1/experience/sessions/'+str(e.sid),headers={'Authorization':'Bearer '+e.token}).status_code==204
    with e.factory() as db:
        assert db.get(RequestManifest,rid) is None
        assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==0
        tomb=db.scalar(select(RequestManifestTombstone))
        assert tomb.root_digest==sha(str(current.root_run_id).encode())
        assert tomb.operation_hash==current.operation_hash and tomb.request_sha==request.request_sha
        assert tomb.expires_at-tomb.erased_at==timedelta(hours=24)
        assert set(tomb.__table__.columns.keys())=={'root_digest','operation_hash','request_sha','erased_at','expires_at'}
    with pytest.raises(ManifestError): load(stored)


def wait_for_pid_lock(factory,pid):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        with factory() as db:
            if db.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:p AND NOT granted)'),{'p':pid}): return
        time.sleep(.02)
    raise AssertionError('Expected isolated lock waiter not observed')


@pytest.mark.parametrize('first',['delete','recover'])
def test_delete_and_recover_serialize_in_both_directions(stored,first):
    e,rid,request,current,_=stored
    ready=Event();pids=[]
    def competing():
        with e.factory.begin() as db:
            pids.append(db.scalar(text('SELECT pg_backend_pid()')));ready.set()
            if first=='delete': return recover(db,e.sid,e.token,rid,current.root_run_id,current.operation_hash)
            delete_session(e.sid,e.token,db)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with e.factory.begin() as db:
            if first=='delete':
                delete_session(e.sid,e.token,db)
            else:
                recovered=recover(db,e.sid,e.token,rid,current.root_run_id,current.operation_hash)
                assert recovered.request.body==request.body and not recovered.dispatch_permitted
            pending=pool.submit(competing)
            assert ready.wait(3)
            wait_for_pid_lock(e.factory,pids[0])
            assert not pending.done()
        if first=='delete':
            with pytest.raises(ManifestError): pending.result(timeout=5)
        else: assert pending.result(timeout=5) is None
    with pytest.raises(ManifestError): load(stored)
    with e.factory() as db: assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==0


def test_read_recovery_only_select_and_no_financial_functions(stored):
    e,_,_,_,_=stored;statements=[]
    engine=e.factory.kw['bind']
    def record(c,cu,s,p,ctx,m): statements.append(s)
    event.listen(engine,'before_cursor_execute',record)
    try: assert load(stored).recovered_and_verified
    finally: event.remove(engine,'before_cursor_execute',record)
    assert statements and all(s.lstrip().upper().startswith('SELECT') for s in statements)
    assert any('FOR SHARE' in s for s in statements)
    assert not any(x in ' '.join(statements) for x in ('paid_runtime(', 'controlled_runtime(', 'binding_runtime('))


def test_recovered_mock_response_uses_existing_complete_pending_only(stored):
    from types import SimpleNamespace
    e,rid,_,current,_=stored
    restored=load(stored)
    admit_offline(e.factory,e.sid,e.token,rid,restored.request)
    observed=[]
    def response(req):
        observed.append(req.content)
        ctx=MiningContext.model_validate_json(json.loads(req.content)['messages'][1]['content'])
        return httpx.Response(200,json=envelope(canonical(output(ctx))))
    with httpx.Client(transport=httpx.MockTransport(response),trust_env=False,follow_redirects=False) as client:
        answer=client.post(restored.request.endpoint,content=restored.request.body)
    decoded=decode_official(answer.content,SimpleNamespace(input_upper_bound=12000,output_cap=1200))
    result=validate_context_v2(current.context,decoded.output)
    mining.complete(e.factory,e.sid,e.token,rid,result,context=current.context)
    assert observed==[restored.request.body]
    with e.factory() as db:
        assert db.get(MiningRun,rid).state=='completed'
        rows=db.scalars(select(ExperienceFact)).all()
        assert len(rows)==1 and rows[0].status=='pending'
        assert db.scalar(select(PaidCall)) is None


def test_empty_candidate_upgrade_check_downgrade_reupgrade(migrated_connection):
    conn,cfg=migrated_connection
    assert ScriptDirectory.from_config(cfg).get_current_head()==NEW
    command.check(cfg);conn.commit()
    assert set(TABLES).issubset(inspect(conn).get_table_names());conn.commit()
    before=conn.execute(text('SELECT * FROM paid_funding')).one();conn.commit()
    command.downgrade(cfg,OLD);conn.commit()
    assert not set(TABLES).intersection(inspect(conn).get_table_names());conn.commit()
    command.upgrade(cfg,NEW);conn.commit();command.check(cfg)
    assert conn.execute(text('SELECT * FROM paid_funding')).one()==before
    for t in (*TABLES,'paid_grants','paid_calls','controlled_probe','paid_audit'):
        assert conn.scalar(text(f'SELECT count(*) FROM {t}'))==0


@pytest.mark.parametrize('table',TABLES)
def test_nonempty_manifest_or_tombstone_blocks_downgrade(stored,migrated_connection,table):
    e,_,_,_,_=stored;conn,cfg=migrated_connection
    if table==TABLES[1]:
        assert e.client.delete('/api/v1/experience/sessions/'+str(e.sid),headers={'Authorization':'Bearer '+e.token}).status_code==204
    with pytest.raises(RuntimeError,match='manifest_nonempty_downgrade_blocked'):
        with conn.begin(): command.downgrade(cfg,OLD)
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==NEW


@pytest.mark.parametrize('sql',[
    "UPDATE mining_request_manifests SET request_sha=repeat('f',64)",
    'DELETE FROM mining_request_manifests','TRUNCATE mining_request_manifests,test_synthetic_request_bodies',
    'TRUNCATE mining_request_tombstones'])
def test_immutable_db_guards_and_no_truncate_loophole(stored,sql):
    e,_,_,_,_=stored
    with pytest.raises(DBAPIError,match='manifest_.*immutable'):
        with e.factory.begin() as db: db.execute(text(sql))


def test_failed_upgrade_rolls_back_entire_candidate(migrated_connection):
    conn,cfg=migrated_connection
    command.downgrade(cfg,OLD);conn.commit()
    def fail(c,cu,s,p,ctx,m):
        if s.startswith('CREATE TRIGGER request_manifest_tombstone_truncate'): raise RuntimeError('synthetic failure')
    event.listen(conn,'after_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='synthetic failure'):
            with conn.begin(): command.upgrade(cfg,NEW)
    finally: event.remove(conn,'after_cursor_execute',fail)
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==OLD
    assert not set(TABLES).intersection(inspect(conn).get_table_names())
    assert conn.scalar(text("SELECT count(*) FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'request_manifest_%'"))==0


def test_function_owner_paths_acl_and_no_production_body(migrated_connection):
    conn,_=migrated_connection
    rows=conn.execute(text('''SELECT proname,prosecdef,proconfig,proowner=current_user::regrole AS owned,
      EXISTS(SELECT 1 FROM aclexplode(coalesce(proacl,acldefault('f',proowner))) a WHERE a.grantee<>proowner) AS extra
      FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'request_manifest_%' ''')).all()
    assert len(rows)==2
    for r in rows:
        assert r.owned and not r.extra and r.proconfig==['search_path=pg_catalog']
        assert r.prosecdef==(r.proname=='request_manifest_guard')
    assert not any(c['name'] in ('body','token','secret_ref','response','grant_id') for c in inspect(conn).get_columns(TABLES[0]))
    assert 'test_synthetic_request_bodies' not in inspect(conn).get_table_names()


@pytest.mark.parametrize('sql',[
    'SELECT * FROM mining_request_manifests', 'DELETE FROM mining_request_manifests',
    'INSERT INTO mining_request_manifests DEFAULT VALUES',
    'SELECT * FROM mining_request_tombstones', 'SELECT request_manifest_guard()',
    'UPDATE paid_funding SET ceiling=ceiling+1', 'DELETE FROM paid_calls'])
def test_restricted_login_has_no_manifest_or_new_money_permissions(binding,sql):
    with pytest.raises(DBAPIError,match='permission denied'):
        with binding.control.engine.begin() as db:
            db.execute(text(f'SET LOCAL search_path TO "{binding.schema}"'))
            db.execute(text(sql))


def test_all_safe_diagnostics_remain_fixed():
    assert str(ManifestError('synthetic-private-value'))=='manifest_invalid'


def test_missing_body_cannot_be_reinserted_from_adapter_or_cached_request(stored):
    e,rid,request,current,_=stored
    with e.factory.begin() as db:
        db.execute(text('DELETE FROM test_synthetic_request_bodies WHERE run_id=:r'),{'r':rid})
    with pytest.raises(ManifestError,match='manifest_bytes_unavailable'):
        with e.factory.begin() as db: put(db,current,request)
    with e.factory() as db: assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==0


def test_metadata_only_record_is_not_a_recoverable_body(prepared):
    e,rid,request,current=prepared
    with e.factory.begin() as db:
        install(db);persist_metadata(db,current,request)
    with e.factory.begin() as db:
        with pytest.raises(ManifestError,match='manifest_bytes_unavailable'):
            recover(db,e.sid,e.token,rid,current.root_run_id,current.operation_hash)


def test_billing_responsibility_survives_erasure_without_body_or_manifest(stored):
    e,rid,request,_,_=stored
    cid=uuid4()
    with e.factory.begin() as db:
        p=db.get(MiningPaidPlan,rid);identity=db.get(MiningPaidIdentity,e.sid)
        db.add(PaidCall(id=cid,grant_id=p.grant_id,operation_hash=p.operation_hash,
            request_hash=p.request_sha,policy_hash=p.policy_sha,batch_tag='synthetic-liability-only',
            provider=p.provider,model=p.model,state='unknown',reserved='.01',lease_until=utcnow()+timedelta(minutes=1)))
        db.flush()
        values={c.name:getattr(p,c.name) for c in p.__table__.columns if c.name not in ('session_id','created_at')}
        db.add(MiningPaidBinding(**values,call_id=cid,actor_scope=identity.actor_scope,session_scope=identity.session_scope))
        funding=db.get(PaidFunding,1);funding.held='.01';funding.frozen=True
    with e.factory() as db:
        before=db.execute(text('SELECT * FROM paid_calls')).all(),db.execute(text('SELECT * FROM paid_funding')).all()
    assert e.client.delete('/api/v1/experience/sessions/'+str(e.sid),headers={'Authorization':'Bearer '+e.token}).status_code==204
    with e.factory() as db:
        assert db.get(RequestManifest,rid) is None
        assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==0
        b=db.get(MiningPaidBinding,rid)
        assert b.binding_state=='tombstoned' and b.call_id==cid and b.request_sha==request.request_sha
        after=db.execute(text('SELECT * FROM paid_calls')).all(),db.execute(text('SELECT * FROM paid_funding')).all()
        assert before==after


@pytest.mark.parametrize('field',['run_id','root_run_id','operation_hash'])
def test_database_unique_indexes_protect_original_identity(stored,field):
    e,_,_,_,_=stored
    with e.factory() as db:
        assert db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_index x JOIN pg_attribute a
          ON a.attrelid=x.indrelid AND a.attnum=ANY(x.indkey)
          WHERE x.indrelid='mining_request_manifests'::regclass AND x.indisunique
            AND x.indnkeyatts=1 AND a.attname=:f)'''),{'f':field})


def test_tombstone_cannot_be_modified_deleted_early_or_forged(stored):
    e,_,_,_,_=stored
    assert e.client.delete('/api/v1/experience/sessions/'+str(e.sid),headers={'Authorization':'Bearer '+e.token}).status_code==204
    for statement in ('DELETE FROM mining_request_tombstones',
        "UPDATE mining_request_tombstones SET expires_at=expires_at+interval '1 hour'",
        "INSERT INTO mining_request_tombstones VALUES(repeat('a',64),repeat('b',64),repeat('c',64),now(),now()+interval '24 hours')"):
        with pytest.raises(DBAPIError,match='manifest_tombstone_immutable'):
            with e.factory.begin() as db: db.execute(text(statement))
    with e.factory.begin() as db: assert purge_expired_tombstones(db)==0


def test_expired_tombstone_maintenance_does_not_restore_root(stored):
    e,rid,_,_,_=stored
    assert e.client.delete('/api/v1/experience/sessions/'+str(e.sid),headers={'Authorization':'Bearer '+e.token}).status_code==204
    with e.factory.begin() as db:
        # Test-owner-only time fixture; never installed in a persistent DB.
        db.execute(text('ALTER TABLE mining_request_tombstones DISABLE TRIGGER request_manifest_tombstone_guard'))
        db.execute(text("UPDATE mining_request_tombstones SET erased_at=x.t-interval '25 hours',expires_at=x.t-interval '1 hour' FROM (SELECT clock_timestamp() t) x"))
        db.execute(text('ALTER TABLE mining_request_tombstones ENABLE TRIGGER request_manifest_tombstone_guard'))
        assert purge_expired_tombstones(db)==1
        assert db.get(MiningRun,rid) is None and db.get(ExperienceSession,e.sid) is None
    with pytest.raises(ManifestError): load(stored)


def test_default_acl_is_stripped_from_new_objects(binding):
    from alembic.config import Config
    e=binding
    with e.factory.kw['bind'].connect() as conn:
        cfg=Config(str(Path(__file__).parents[1]/'alembic.ini'));cfg.attributes['connection']=conn
        command.downgrade(cfg,OLD);conn.commit()
        for kind in ('TABLES','FUNCTIONS'):
            conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{e.schema}" GRANT ALL ON {kind} TO "{e.role}"'))
        conn.commit()
        try:
            command.upgrade(cfg,NEW);conn.commit()
            for table in TABLES:
                assert not conn.scalar(text("SELECT has_table_privilege(:r,:t,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"),
                    {'r':e.role,'t':f'"{e.schema}".{table}'})
            for fn in ('request_manifest_guard()','request_manifest_tombstone_guard()'):
                assert not conn.scalar(text("SELECT has_function_privilege(:r,:t,'EXECUTE')"),
                    {'r':e.role,'t':f'"{e.schema}".{fn}'})
        finally:
            conn.rollback()
            for kind in ('TABLES','FUNCTIONS'):
                conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{e.schema}" REVOKE ALL ON {kind} FROM "{e.role}"'))
            conn.commit()


def test_restricted_login_cannot_read_plaintext_test_body(stored,binding):
    with pytest.raises(DBAPIError,match='permission denied'):
        with binding.control.engine.begin() as db:
            db.execute(text(f'SET LOCAL search_path TO "{binding.schema}"'))
            db.execute(text('SELECT body FROM test_synthetic_request_bodies'))


def test_original_business_api_idempotency_survives_0012(api,migrated_connection):
    from test_idempotency import headers
    client,_=api;conn,cfg=migrated_connection
    command.downgrade(cfg,OLD);conn.commit()
    h,_=headers();body={'raw_input':'合成：我编写了课程校验器。'}
    before=client.post('/api/v1/experience/sessions',headers=h,json=body)
    assert before.status_code==201
    command.upgrade(cfg,NEW);conn.commit()
    after=client.post('/api/v1/experience/sessions',headers=h,json=body)
    assert after.status_code==201 and after.json()==before.json()
    assert conn.scalar(text('SELECT count(*) FROM mining_request_manifests'))==0


def test_actual_web_login_erases_without_manifest_body_or_funding_grants(stored,role_capability):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    assert role_capability
    e,rid,_,_,_=stored
    owner=e.factory.kw['bind'];role='manifest_web_'+uuid4().hex;password=uuid4().hex
    with e.factory.begin() as db:
        schema=db.scalar(text('SELECT current_schema()'))
        db.execute(text("SELECT set_config('pathwise.fixture_password',:p,true)"),{'p':password})
        db.execute(text(f'''DO $$ BEGIN EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD %L',
          '{role}',current_setting('pathwise.fixture_password')); END $$'''))
    runtime=None
    try:
        with owner.begin() as db:
            db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            business=('experience_sessions','experience_projects','conversation_turns',
                'experience_facts','fact_sources','fact_evidence','fact_changes','idempotency_operations',
                'ai_mining_runs','ai_mining_receipts','ai_mining_questions','ai_answer_questions','ai_mining_capacity')
            db.execute(text('GRANT SELECT,UPDATE,DELETE ON '+','.join(f'"{schema}".{t}' for t in business)+f' TO "{role}"'))
            for table in (*TABLES,'test_synthetic_request_bodies','paid_funding','paid_calls','paid_grants'):
                assert not db.scalar(text("SELECT has_table_privilege(:r,:t,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"),
                    {'r':role,'t':f'"{schema}".{table}'})
        runtime=create_engine(owner.url.set(username=role,password=password),poolclass=NullPool,
            hide_parameters=True,connect_args={'options':f'-csearch_path={schema}'})
        factory=sessionmaker(runtime,expire_on_commit=False)
        with factory.begin() as db:
            assert db.scalar(text('SELECT current_user=session_user AND session_user=:r'),{'r':role})
            assert delete_session(e.sid,e.token,db).status_code==204
        with e.factory() as db:
            assert db.get(RequestManifest,rid) is None
            assert db.scalar(text('SELECT count(*) FROM test_synthetic_request_bodies'))==0
            assert db.scalar(text('SELECT count(*) FROM mining_request_tombstones'))==1
    finally:
        if runtime is not None: runtime.dispose()
        with owner.begin() as db:
            db.execute(text(f'DROP OWNED BY "{role}"'))
            db.execute(text(f'DROP ROLE "{role}"'))


@pytest.mark.parametrize('change',['stop','end','revision','unknown','lease'])
@pytest.mark.parametrize('action',['recover','persist'])
def test_locked_reads_refresh_preexisting_identity_map(stored,change,action):
    e,rid,request,current,_=stored
    with e.factory() as db:
        cached_session=db.get(ExperienceSession,e.sid)
        cached_run=db.get(MiningRun,rid)
        with e.factory.begin() as other:
            if change=='stop': other.get(ExperienceSession,e.sid).mining_status='stopped'
            elif change=='end': facts.end_session(other,e.sid,e.token)
            elif change=='revision': facts.add_turn(other,e.sid,e.token,'合成：新的上下文。')
            elif change=='unknown': other.get(MiningRun,rid).state='unknown'
            else: other.get(MiningRun,rid).lease_until=utcnow()-timedelta(seconds=1)
        assert cached_session is not None and cached_run is not None
        with pytest.raises(ManifestError):
            if action=='recover': recover(db,e.sid,e.token,rid,current.root_run_id,current.operation_hash)
            else: persist_metadata(db,current,request)


@pytest.mark.parametrize('pending',['new','dirty','deleted'])
def test_recovery_refuses_pending_autoflush_before_any_sql(stored,pending):
    e,rid,_,current,_=stored
    engine=e.factory.kw['bind'];statements=[]
    def record(c,cu,s,p,ctx,m): statements.append(s)
    with e.factory() as db:
        session=db.get(ExperienceSession,e.sid)
        if pending=='new': db.add(ExperienceSession(access_token_hash='f'*64))
        elif pending=='dirty': session.status='ended'
        else: db.delete(session)
        event.listen(engine,'before_cursor_execute',record)
        try:
            with pytest.raises(ManifestError): recover(db,e.sid,e.token,rid,current.root_run_id,current.operation_hash)
        finally: event.remove(engine,'before_cursor_execute',record)
    assert statements==[]
    with e.factory() as db:
        assert db.get(ExperienceSession,e.sid).status=='active' and db.get(MiningRun,rid) is not None
