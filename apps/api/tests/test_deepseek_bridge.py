"""C-1B byte-bound offline HTTP + real PostgreSQL restricted LOGIN tests.

No real approvals, keys, provider sockets or actual invoices. Positive money
and token attestations are synthetic fixtures in a fresh random test schema.
"""
import asyncio
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import multiprocessing
import os
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from app.cost_ledger import canonical, digest
from app.deepseek_bridge import (DeepSeekBridge, BridgeProfile, BoundFakeSecretResolver,
    SecretRef, bind_bytes, synthetic_request)
from app.deepseek_contract import SyntheticRequest, ProbeError, FAKE_SECRET, synthetic_requests
from app.deepseek_transport import DeepSeekOfficialTransport, DisabledSecretResolver, TimeLimits
from app.mining_context import MiningContext
from app.mining_provider import MiningOutputV2
from app.mining_validation import atomic, sentence_spans, validate_context_v2
from app.models import utcnow
from app.paid_control import PaidControl, PaidPolicy
from app.paid_models import PaidFunding, PaidCall
from test_paid_control import paid, authorize, expire, policy as fixture_policy
from test_cost_ledger import ledger_stack, profile
from test_http_api import api
from test_deepseek_c0 import packet


def components(paid=None):
    request = synthetic_request()
    base = paid[5] if paid is not None else fixture_policy()
    ref = SecretRef(account_ref=base.account_ref, name='only-public-fake-not-a-vault')
    data = base.model_dump(mode='json')
    data['secret_ref_digest'] = ref.fingerprint()
    data['certificates'][0]['request_sha'] = request.fingerprint
    policy = PaidPolicy.model_validate(data)
    profile = BridgeProfile(output_cap=256, request_sha=request.fingerprint,
                            policy_sha=digest(canonical(policy.model_dump(mode='json'))), secret_ref=ref)
    resolver = BoundFakeSecretResolver(reference=ref, expires_at=utcnow()+timedelta(hours=1))
    return request, policy, profile, resolver


@pytest.fixture(scope='session')
def role_capability():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        if os.getenv('CI'):pytest.fail('CI requires isolated test database')
        pytest.skip('TEST_DATABASE_URL required')
    engine = create_engine(url,hide_parameters=True)
    try:
        if engine.url.database not in ('pathwise_test','pathwise_e2e') or engine.url.host not in ('localhost','127.0.0.1'):
            pytest.fail('isolated test database required')
        with engine.connect() as conn:
            return conn.scalar(text('SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user'))
    finally:engine.dispose()


@pytest.fixture
def restricted(request, role_capability):
    if not role_capability:
        if os.getenv('CI'):pytest.fail('CI must execute restricted LOGIN integration tests')
        pytest.skip('Local test owner has no CREATEROLE; restricted LOGIN full-chain tests mandatory in CI')
    paid = request.getfixturevalue('paid')
    admin, owner_control, factory, schema, _, _ = paid
    engine = factory.kw['bind']
    role = 'bridge_test_' + uuid4().hex
    password = uuid4().hex  # ephemeral synthetic DB password, NEVER an API Key
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('pathwise.fixture_password', :p, true)"), {'p':password})
        # Password is a bind value in the previous statement, not SQL/report text.
        conn.exec_driver_sql(f'''DO $$ BEGIN EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
            '{role}',current_setting('pathwise.fixture_password')); END $$''')
    runtime_engine = create_engine(engine.url.set(username=role, password=password), poolclass=NullPool, hide_parameters=True)
    try:
        admin.provision_runtime_role(schema, role)
        request, policy, profile, resolver = components(paid)
        gid = authorize(admin, policy)
        control = PaidControl(runtime_engine, schema, owner_control.ledger_id)
        control.assert_offline_runtime()
        yield paid, control, gid, request, policy, profile, resolver
    finally:
        runtime_engine.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


def response(request=None):
    request = request or synthetic_request()
    context = MiningContext.model_validate_json(json.loads(request.body)['messages'][1]['content'])
    turn = context.user_turns[0]
    candidates = [{'citation':dict(turn_id=str(turn.turn_id), start=s, end=e, quote=q)}
                  for s,e,q in sentence_spans(turn.content) if atomic(q)]
    value = packet()
    value['choices'][0]['message']['content'] = canonical(dict(schema_version=2, candidates=candidates[:1],
        questions=[], stop=True, stop_reason='no_new_information'))
    return value


def exercise(stack, handler, **kw):
    _, control, gid, request, _, profile, resolver = stack
    return asyncio.run(DeepSeekBridge().exercise_offline(control, gid, kw.pop('request',request), kw.pop('operation','one'), kw.pop('batch','fixture'),
        profile=kw.pop('profile',profile), resolver=kw.pop('resolver',resolver), wire_transport=httpx.MockTransport(handler), **kw))


def test_real_entries_never_resolve_or_open_http(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sentinel-not-a-real-key-never-read')
    with patch('os.getenv', side_effect=AssertionError('env forbidden')), patch('httpx.AsyncClient', side_effect=AssertionError('HTTP forbidden')), patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')):
        with pytest.raises(ProbeError, match='live_dispatch_disabled_c1b'):
            asyncio.run(DeepSeekBridge().invoke(enabled=True, grant=True))
        with pytest.raises(ProbeError, match='live_dispatch_disabled_c0'):
            asyncio.run(DeepSeekOfficialTransport().invoke(enabled=True))
        with pytest.raises(ProbeError): DisabledSecretResolver().resolve('not-read')


def test_owner_login_is_rejected_before_secret_or_http(paid):
    request, _, profile, resolver = components(paid)
    with patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('secret forbidden')):
        result = asyncio.run(DeepSeekBridge().exercise_offline(paid[1], paid[4], request, 'one', 'fixture',
            profile=profile, resolver=resolver, wire_transport=httpx.MockTransport(lambda _: pytest.fail('HTTP forbidden'))))
    assert result.code == 'bridge_restricted_login_required'


def test_daily_database_and_nonrandom_schema_refused_without_connect():
    for database, schema in [('pathwise_dev','test_'+uuid4().hex), ('pathwise_test','public')]:
        engine = create_engine(f'postgresql+psycopg://unused:fake@localhost/{database}')
        try:
            control = PaidControl(engine, schema, uuid4())
            with patch.object(engine,'connect',side_effect=AssertionError('must not connect')):
                with pytest.raises(ProbeError,match='bridge_isolated_database_required'): control.assert_offline_runtime()
        finally: engine.dispose()


@pytest.mark.parametrize('index', range(24))
def test_all_fixed_synthetic_bodies_have_exact_bytes_context_and_schema(index):
    request, policy, profile, _ = components()
    chosen = synthetic_requests()[index]
    data = policy.model_dump(mode='json'); data['certificates'][0]['request_sha'] = chosen.fingerprint
    policy = PaidPolicy.model_validate(data)
    profile = profile.model_copy(update={'request_sha':chosen.fingerprint,'policy_sha':digest(canonical(policy.model_dump(mode='json')))})
    frozen, context, limits = bind_bytes(chosen, policy, profile)
    assert frozen.body is chosen.body
    assert hashlib.sha256(frozen.body).hexdigest() == profile.request_sha
    assert context.input_turn_id == context.user_turns[0].turn_id
    assert limits.output_cap == 256


@pytest.mark.parametrize('change', ['utf8','whitespace','model','cap','system','context','case','sha'])
def test_bytes_or_identity_changes_rejected(change):
    request, policy, profile, _ = components()
    body = request.body; case = request.case_id
    if change == 'utf8': body = b'\xff'
    if change == 'whitespace': body += b' '
    if change == 'model': body = body.replace(b'deepseek-flash', b'other-model')
    if change == 'cap': body = body.replace(b'"max_tokens":256',b'"max_tokens":512')
    if change == 'system': body = body.replace(b'"role":"system"',b'"role":"assistant"')
    if change == 'context': body = body.replace(b'"role":"user"',b'"role":"assistant"')
    if change == 'case': case = 'S01'
    if change == 'sha': profile = profile.model_copy(update={'request_sha':digest('other')})
    altered = SyntheticRequest(case, request.turn_key, body)
    with pytest.raises(ProbeError): bind_bytes(altered, policy, profile)


@pytest.mark.parametrize('case,turn,allowed', [('S03','a',True),('S01','a',False),('S04','a',False),('S06','a',False)])
def test_shared_source_guard_preserves_negation_and_rejects_team_hypothesis_uncertainty(case, turn, allowed):
    request = synthetic_request(case,turn)
    context = MiningContext.model_validate_json(json.loads(request.body)['messages'][1]['content'])
    user = context.user_turns[0]
    output = MiningOutputV2.model_validate(dict(schema_version=2,candidates=[dict(citation=dict(
        turn_id=user.turn_id,start=0,end=len(user.content),quote=user.content))],questions=[],stop=True,stop_reason='no_new_information'))
    if allowed:
        result = validate_context_v2(context,output)
        assert '没有' in result.candidates[0].citation.quote
    else:
        with pytest.raises(ValueError,match='Invalid atomic source'):validate_context_v2(context,output)


def test_full_chain_exact_http_body_valid_sources_and_no_real_bill(restricted):
    stack = restricted; seen = []
    def handler(request):
        seen.append(request.content)
        assert request.content == stack[3].body
        assert hashlib.sha256(request.content).hexdigest() == stack[5].request_sha
        assert str(request.url) == stack[5].endpoint
        assert request.headers['Authorization'] == 'Bearer '+FAKE_SECRET
        return httpx.Response(200,json=response(stack[3]))
    result = exercise(stack, handler)
    assert result.code == 'validated_offline'
    assert result.output and result.output.candidates
    assert seen == [stack[3].body]
    row = stack[1].get(result.call_id)
    assert row['state'] == 'response_received' and row['actual'] is None and row['actual_usd'] is None
    assert row['reserved'] > 0
    with stack[0][2]() as db: assert db.get(PaidFunding,1).spent == 0
    again = exercise(stack, handler)
    assert again.code == 'recovered_read_only' and again.call_id == result.call_id
    assert len(seen) == 1 and again.output is None


@pytest.mark.parametrize('case_id', ['S'+str(i).zfill(2) for i in range(1,13)])
def test_all_twelve_cases_through_offline_http_and_ledger(restricted, case_id):
    stack = restricted
    request = next(r for r in synthetic_requests() if r.case_id==case_id)
    data = stack[4].model_dump(mode='json'); data['certificates'][0]['request_sha']=request.fingerprint
    policy = PaidPolicy.model_validate(data); gid = authorize(stack[0][0],policy)
    profile = stack[5].model_copy(update={'request_sha':request.fingerprint,'policy_sha':digest(canonical(policy.model_dump(mode='json')))})
    updated = (stack[0],stack[1],gid,request,policy,profile,stack[6])
    result = exercise(updated,lambda _:httpx.Response(200,json=response(request)))
    assert result.code=='validated_offline'
    assert updated[1].get(result.call_id)['actual'] is None
    assert result.diagnostic()['real_quality'] is None


def test_mutating_original_object_cannot_replace_frozen_http_buffer(restricted):
    stack=restricted;approved_body=stack[3].body;original=PaidControl.reserve;seen=[]
    def mutate_original(control,*args,**kw):
        row=original(control,*args,**kw)
        object.__setattr__(stack[3],'body',b'UNAPPROVED_REPLACEMENT')
        return row
    with patch.object(PaidControl,'reserve',mutate_original):
        result=exercise(stack,lambda request:(seen.append(request.content) or httpx.Response(200,json=response())))
    assert result.code=='validated_offline' and seen==[approved_body]


def test_declined_permit_keeps_reserve_without_resolving_secret(restricted):
    original=PaidControl.transition
    def decline(control,cid,action,*args,**kw):
        return {'permitted':False} if action=='permit' else original(control,cid,action,*args,**kw)
    with patch.object(PaidControl,'transition',decline),patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('no secret')):
        result=exercise(restricted,lambda _:pytest.fail('no HTTP'))
    assert result.code=='recovered_read_only' and result.state=='reserved'
    assert restricted[1].get(result.call_id)['actual'] is None


@pytest.mark.parametrize('change', ['model','endpoint','expected_version','region','mode','output_cap','request_sha','policy_sha'])
def test_profile_drift_refused_before_resolution(restricted, change):
    profile = restricted[5].model_copy(update={change:512 if change=='output_cap' else digest('different') if change.endswith('sha') else 'different'})
    with patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('no secret')):
        result = exercise(restricted, lambda _:pytest.fail('no HTTP'), profile=profile)
    assert result.code in ('bridge_profile_changed','bridge_policy_changed','bridge_payload_not_approved')


@pytest.mark.parametrize('kind', ['expired','revoked','reference','account','provider'])
def test_bound_fake_secret_refused(restricted, kind):
    resolver = restricted[6]; ref = resolver.reference
    if kind == 'expired': resolver = resolver.model_copy(update={'expires_at':utcnow()-timedelta(seconds=1)})
    if kind == 'revoked': resolver = resolver.model_copy(update={'revoked':True})
    if kind in ('reference','account','provider'):
        changed = ref.model_copy(update={dict(reference='name',account='account_ref',provider='provider')[kind]:'different'})
        resolver = resolver.model_copy(update={'reference':changed})
    with patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('no secret')):
        result = exercise(restricted, lambda _:pytest.fail('no HTTP'), resolver=resolver)
    assert result.code == 'bridge_secret_binding_invalid'


def test_missing_authority_or_failed_reservation_never_resolves(restricted):
    stack = restricted
    with patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('no secret')):
        result = asyncio.run(DeepSeekBridge().exercise_offline(stack[1], uuid4(), stack[3], 'one','fixture',profile=stack[5],
            resolver=stack[6],wire_transport=httpx.MockTransport(lambda _:pytest.fail('HTTP forbidden'))))
        assert result.code == 'paid_grant_inactive'
        with stack[0][2].begin() as db: db.get(PaidFunding,1).ceiling = 0
        result = exercise(stack, lambda _:pytest.fail('no HTTP'))
        assert result.code == 'paid_pool_blocked'


def test_reservation_without_permit_stays_reserved_and_replay_is_read_only(restricted):
    stack = restricted; original = PaidControl.reserve
    def reserve_then_revoke(control,*args,**kw):
        row = original(control,*args,**kw)
        stack[0][0].revoke(stack[2], digest('synthetic revoked after reservation'))
        return row
    with patch.object(PaidControl,'reserve',reserve_then_revoke),patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('no secret')):
        result = exercise(stack, lambda _:pytest.fail('no HTTP'))
    assert result.code == 'paid_grant_inactive'
    assert stack[1].get(result.call_id)['state'] == 'reserved'
    assert stack[1].get(result.call_id)['actual'] is None


def test_revocation_after_permit_before_http_conservatively_unknown(restricted):
    stack = restricted; original = PaidControl.transition
    def permit_then_revoke(control,cid,action,*args,**kw):
        result = original(control,cid,action,*args,**kw)
        if action == 'permit': stack[0][0].revoke(stack[2],digest('synthetic late revocation'))
        return result
    with patch.object(PaidControl,'transition',permit_then_revoke),patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('no secret')):
        result = exercise(stack, lambda _:pytest.fail('no HTTP'))
    assert result.code == 'paid_grant_inactive'
    assert stack[1].get(result.call_id)['state'] == 'unknown'
    assert stack[1].get(result.call_id)['actual'] is None


def test_read_only_recovery_survives_revocation_and_never_resolves(restricted):
    stack = restricted
    result = exercise(stack,lambda _:httpx.Response(200,json=response()))
    stack[0][0].revoke(stack[2],digest('synthetic post-completion revocation'))
    with patch.object(BoundFakeSecretResolver,'resolve_fake',side_effect=AssertionError('no secret')):
        recovered = DeepSeekBridge().recover_offline(stack[1],result.call_id)
    assert recovered.code=='recovered_read_only' and recovered.state=='response_received'
    assert recovered.output is None


@pytest.mark.parametrize('status', [401,429,500,503])
def test_http_failures_hold_unknown_once(restricted, status):
    calls = []
    def handler(request): calls.append(1); return httpx.Response(status, text='SENSITIVE_RESPONSE_DO_NOT_LOG')
    result = exercise(restricted, handler)
    assert result.code in ('http_4xx','http_429','http_5xx')
    assert restricted[1].get(result.call_id)['state'] == 'unknown'
    assert restricted[1].get(result.call_id)['actual'] is None
    assert exercise(restricted,handler).code == 'recovered_read_only'
    assert calls == [1]


@pytest.mark.parametrize('failure', ['json','schema','source','turn','duplicate','number','tokens','truncated','refused','model','body'])
def test_successful_http_invalid_output_keeps_hold(restricted, failure, caplog):
    value = response(restricted[3]); content = json.loads(value['choices'][0]['message']['content'])
    if failure == 'json': value['choices'][0]['message']['content'] = 'SENSITIVE_INVALID_JSON'
    if failure == 'schema': content['confirmed'] = True
    if failure == 'source': content['candidates'][0]['citation']['start'] += 1
    if failure == 'turn': content['candidates'][0]['citation']['turn_id'] = str(uuid4())
    if failure == 'duplicate': content['candidates'] *= 2
    if failure == 'number': content.update(stop=False,stop_reason=None, questions=[dict(text='你提升了999999倍吗？',purpose='verification',source_turn_ids=[content['candidates'][0]['citation']['turn_id']])])
    if failure == 'tokens': value['usage'].update(completion_tokens=257,total_tokens=357)
    if failure == 'truncated': value['choices'][0]['finish_reason'] = 'length'
    if failure == 'refused': value['choices'][0]['message']['refusal'] = 'SENSITIVE_REFUSAL'
    if failure == 'model': value['model'] = 'unapproved-model'
    if failure != 'json': value['choices'][0]['message']['content'] = canonical(content)
    result = exercise(restricted, lambda _:httpx.Response(200,content=b'x'*262145) if failure=='body' else httpx.Response(200,json=value))
    assert result.state == 'unknown' and result.output is None
    assert restricted[1].get(result.call_id)['actual'] is None
    report = canonical(result.diagnostic()) + repr(result) + caplog.text
    assert FAKE_SECRET not in report and 'SENSITIVE' not in report


def test_timeout_and_cancellation_preserve_hold_without_retry(restricted):
    calls=[]
    async def timeout_handler(request): calls.append(1); await asyncio.sleep(.1); return httpx.Response(200,json=response())
    result = exercise(restricted,timeout_handler,transport=DeepSeekOfficialTransport(limits=TimeLimits(connect=.01,read=.01,total=.02)))
    assert result.code == 'timeout' and len(calls)==1
    assert restricted[1].get(result.call_id)['state'] == 'unknown'


def test_task_cancellation_after_send_is_unknown(restricted):
    async def handler(request): raise asyncio.CancelledError('SENSITIVE cancellation')
    with pytest.raises(asyncio.CancelledError) as err: exercise(restricted,handler)
    assert 'SENSITIVE' not in str(err.value)
    with restricted[0][2]() as db: row = db.scalar(select(PaidCall).where(PaidCall.grant_id==restricted[2]))
    assert restricted[1].get(row.id)['state'] == 'unknown'
    assert restricted[1].get(row.id)['actual'] is None


def worker(url, schema, ledger, gid, profile_data, operation, counter, queue, crash=None):
    # Worker receives ONLY restricted LOGIN URL; no admin factory/credentials.
    engine = create_engine(url,poolclass=NullPool,hide_parameters=True)
    profile = BridgeProfile.model_validate(profile_data)
    resolver = BoundFakeSecretResolver(reference=profile.secret_ref,expires_at=utcnow()+timedelta(hours=1))
    async def before(*args): os._exit(41)
    def handler(request):
        with counter.get_lock(): counter.value += 1
        if crash == 'in_http': os._exit(42)
        return httpx.Response(200,json=response())
    if crash == 'before_http': DeepSeekOfficialTransport._post_once = before
    try:
        result = asyncio.run(DeepSeekBridge().exercise_offline(PaidControl(engine,schema,ledger),gid,synthetic_request(),operation,operation,
            profile=profile,resolver=resolver,wire_transport=httpx.MockTransport(handler)))
        queue.put(result.diagnostic())
    finally: engine.dispose()


@pytest.mark.parametrize('same_key', [True,False])
def test_full_chain_multiprocess_once_and_shared_budget(restricted, same_key):
    stack=restricted; ctx=multiprocessing.get_context('spawn'); counter=ctx.Value('i',0); queue=ctx.Queue()
    if not same_key:
        with stack[0][2].begin() as db: db.get(PaidFunding,1).ceiling=Decimal('.02')
    args=(stack[1].engine.url.render_as_string(hide_password=False),stack[1].schema,stack[1].ledger_id,str(stack[2]),stack[5].model_dump(mode='json'))
    processes=[ctx.Process(target=worker,args=(*args,'same' if same_key else 'batch-'+str(i),counter,queue)) for i in range(2)]
    for p in processes:p.start()
    for p in processes:
        p.join(45)
        if p.is_alive():p.terminate();p.join();pytest.fail('child exceeded bounded wait')
        assert p.exitcode==0
    rows=[queue.get(timeout=5) for _ in processes]
    assert counter.value==1
    assert sum(r['code']=='validated_offline' for r in rows)==1
    assert any(r['code']==('recovered_read_only' if same_key else 'paid_budget_exceeded') for r in rows)


@pytest.mark.parametrize('crash,exitcode,wire_calls', [('before_http',41,0),('in_http',42,1)])
def test_process_death_before_or_during_http_and_read_only_restart(restricted, crash, exitcode, wire_calls):
    stack=restricted;ctx=multiprocessing.get_context('spawn');counter=ctx.Value('i',0);queue=ctx.Queue()
    args=(stack[1].engine.url.render_as_string(hide_password=False),stack[1].schema,stack[1].ledger_id,str(stack[2]),stack[5].model_dump(mode='json'),'crash',counter,queue,crash)
    process=ctx.Process(target=worker,args=args);process.start();process.join(45)
    if process.is_alive():process.terminate();process.join();pytest.fail('child exceeded bounded wait')
    assert process.exitcode==exitcode and counter.value==wire_calls
    with stack[0][2]() as db:cid=str(db.scalar(select(PaidCall.id).where(PaidCall.grant_id==stack[2])))
    assert stack[1].get(cid)['persisted_state']=='sent'
    expire(stack[0][2],cid)
    assert stack[1].get(cid)['state']=='unknown' and stack[1].get(cid)['persisted_state']=='sent'
    assert stack[1].recover()['recovered']==1
    result=exercise(stack,lambda _:pytest.fail('must not replay'),operation='crash',batch='crash')
    assert result.code=='recovered_read_only' and result.state=='unknown'
    assert stack[1].get(cid)['actual'] is None
