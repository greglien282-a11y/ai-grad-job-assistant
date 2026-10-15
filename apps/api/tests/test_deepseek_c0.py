"""C-0: real PostgreSQL controls + fully offline official HTTP protocol tests."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
import json
import multiprocessing
import os
from unittest.mock import patch
from uuid import UUID,uuid4

from alembic import command
import httpx
import pytest
from sqlalchemy import create_engine,select,text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.cost_ledger import canonical,digest
from app.deepseek_contract import (ENDPOINT,MODEL,VERSION,FAKE_SECRET,ProbeError,ProbePolicy,
    synthetic_requests,SyntheticRequest,decode_official)
from app.deepseek_transport import DeepSeekOfficialTransport,FakeSecretResolver,DisabledSecretResolver,DeniedNetworkTransport,TimeLimits
from app.probe_control import ProbeControl
from app.models import ProbeFunding,ProbeGrant,ProbeAttempt,CostBudget,utcnow
from app.model_adapter import Adapter,MockTransport,OfflineRunner,SimulatedCrash
from test_cost_ledger import ledger_stack,profile


def policy(request=None,**changes):
    request=request or synthetic_requests()[0];until=utcnow()+timedelta(hours=1)
    data={'key_binding':digest(FAKE_SECRET),'request_hashes':[request.fingerprint],
          'input_upper_bound':5000,'output_cap':256,'token_evidence_digest':digest('fixture only full framing bound'),
          'price':{'source_digest':digest('offline official-price fixture'),'expires_at':until.isoformat(),
                   'peak_miss':'.30','offpeak_miss':'.15','peak_hit':'.006','offpeak_hit':'.003','peak_output':'1.2','offpeak_output':'.6'},
          'fx':{'source_digest':digest('unapproved fixture FX'),'expires_at':until.isoformat(),'cny_per_usd':'7.5','tax_margin_factor':'1.1'}}
    data.update(changes);return ProbePolicy.model_validate(data)


def packet():
    return {'id':'offline-completion-1','object':'chat.completion','created':1791980000,'model':MODEL,'system_fingerprint':'fp_offline_fixture',
            'choices':[{'index':0,'finish_reason':'stop','logprobs':None,'message':{'role':'assistant','content':canonical({'schema_version':2,
                'candidates':[],'questions':[],'stop':True,'stop_reason':'no_new_information'})}}],
            'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_cache_hit_tokens':40,'prompt_cache_miss_tokens':60,'total_tokens':120,
                     'prompt_tokens_details':{'cached_tokens':40},'completion_tokens_details':{'reasoning_tokens':0}}}


@pytest.fixture
def probe(ledger_stack):
    _,factory,schema=ledger_stack;control=ProbeControl(factory);control.setup_fixture_pool('1')
    req=synthetic_requests()[0];p=policy(req)
    gid=control.add_fixture_grant(p,utcnow()-timedelta(minutes=1),utcnow()+timedelta(minutes=30),'1',calls_limit=10)
    return control,factory,schema,req,gid


def run(control,gid,req,handler,op='test-operation',**kw):
    return asyncio.run(DeepSeekOfficialTransport(limits=kw.pop('limits',None)).exercise_offline(control,gid,req,op,'fixture-batch',
         resolver=kw.pop('resolver',FakeSecretResolver()),wire_transport=httpx.MockTransport(handler),**kw))


def test_default_live_entry_never_reads_key_or_opens_network(monkeypatch):
    # Environment values are sentinels; no real key is read, supplied or required.
    monkeypatch.setenv('DEEPSEEK_API_KEY','not-a-real-key-do-not-read')
    monkeypatch.setenv('HTTPS_PROXY','http://never-use.invalid')
    with patch('httpx.AsyncClient',side_effect=AssertionError('client forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')):
        with pytest.raises(ProbeError,match='live_dispatch_disabled_c0'):asyncio.run(DeepSeekOfficialTransport().invoke(approval='anything',enabled=True))
    with pytest.raises(ProbeError):DisabledSecretResolver().resolve('unused')
    assert 'fake-secret' not in repr(FakeSecretResolver())


@pytest.mark.parametrize('url',['http://api.deepseek.com/chat/completions','https://api.deepseek.com/v1/chat/completions',
    'https://api.deepseek.com/beta/chat/completions','https://api.deepseek.com/chat/completions?key=fake','https://api.deepseek.com.evil.invalid/chat/completions',
    'https://api.deepseek.com:443/chat/completions','https://api.deepseek.com/anthropic'])
def test_complete_endpoint_allowlist(url):
    with pytest.raises(ProbeError,match='endpoint_not_allowlisted'):DeepSeekOfficialTransport(endpoint=url)


def test_offline_http_contract_has_only_fake_key_no_proxy_or_redirect(probe,caplog):
    control,factory,_,req,gid=probe;calls=[]
    def handler(request):
        calls.append(1)
        assert str(request.url)==ENDPOINT and request.method=='POST'
        assert request.headers['authorization']=='Bearer '+FAKE_SECRET
        body=json.loads(request.content)
        assert body['model']==MODEL and body['thinking']=={'type':'disabled'} and body['stream'] is False
        assert body['response_format']=={'type':'json_object'} and body['max_tokens']==256
        assert request.extensions['timeout']['connect']==5 and request.extensions['timeout']['read']==15
        return httpx.Response(200,json=packet())
    aid,result=run(control,gid,req,handler)
    assert result.output.tokens_in==100 and result.output.tokens_out==20
    assert result.usage['cached']==40 and result.usage['uncached']==60
    assert result.evidence['version_confidence']=='alias_not_immutable_unverified'
    assert control.get(aid)['state']=='response_received' and control.get(aid)['actual_fixture_cny'] is None
    assert run(control,gid,req,handler)==(aid,None) and len(calls)==1
    assert FAKE_SECRET not in caplog.text and 'Authorization' not in caplog.text and req.body.decode() not in caplog.text
    with factory() as db:assert db.get(ProbeFunding,1).approved_real_cny==0


@pytest.mark.parametrize('bad',['key','region','model','expired','revoked','fx','price','bound','raw_user','manifest','policy_drift'])
def test_preflight_failures_do_not_send(probe,bad,monkeypatch):
    control,factory,_,req,gid=probe;calls=[];resolver=FakeSecretResolver()
    if bad=='key':resolver=FakeSecretResolver('wrong-fake-key')
    elif bad=='raw_user':req=SyntheticRequest('user','real',b'{"real_resume":"unapproved"}')
    elif bad=='manifest':monkeypatch.setattr('app.deepseek_contract.digest',lambda _: '0'*64)
    else:
        with factory.begin() as db:
            g=db.get(ProbeGrant,gid);p=dict(g.policy)
            if bad=='region':p['region']='unapproved-region'
            if bad=='model':p['model']='deepseek-v4-pro'
            if bad=='expired':g.expires_at=utcnow()-timedelta(seconds=1)
            if bad=='revoked':g.mode='revoked'
            if bad in ('fx','price'):p[bad]=dict(p[bad],expires_at=(utcnow()-timedelta(seconds=1)).isoformat())
            if bad=='bound':p.pop('token_evidence_digest')
            if bad=='policy_drift':p['expected_version']='unknown-next-version'
            g.policy=p
    with pytest.raises(ProbeError):run(control,gid,req,lambda r:calls.append(1),resolver=resolver)
    assert not calls
    with factory() as db:assert db.scalar(select(ProbeAttempt.id)) is None


@pytest.mark.parametrize('fault',[401,429,500,503,302,'invalid_json','truncated','refusal','drift','cache','total','reasoning','mode','body_limit','timeout','connect_timeout','crash'])
def test_faults_are_unknown_never_retried_and_reservations_remain(probe,fault):
    control,factory,_,req,gid=probe;calls=[]
    def handler(request):
        calls.append(1);p=packet()
        if fault=='crash':raise SimulatedCrash()
        if fault=='timeout':raise httpx.ReadTimeout('FAKE_SECRET_MUST_NOT_LEAK',request=request)
        if fault=='connect_timeout':raise httpx.ConnectTimeout('FAKE_SECRET_MUST_NOT_LEAK',request=request)
        if type(fault) is int:return httpx.Response(fault,headers={'Location':'https://unapproved.invalid'},text='SENSITIVE_ERROR_MUST_NOT_LEAK')
        if fault=='invalid_json':return httpx.Response(200,content=b'{bad')
        if fault=='body_limit':return httpx.Response(200,content=b' '*262145)
        if fault=='truncated':p['choices'][0]['finish_reason']='length'
        if fault=='refusal':p['choices'][0]['finish_reason']='content_filter'
        if fault=='drift':p['model']='future-model'
        if fault=='cache':p['usage']['prompt_cache_miss_tokens']=100
        if fault=='total':p['usage']['total_tokens']=119
        if fault=='reasoning':p['usage']['completion_tokens_details']['reasoning_tokens']=1
        if fault=='mode':p['choices'][0]['message']['tool_calls']=[{'invented':'tool'}]
        return httpx.Response(200,json=p)
    if fault=='crash':
        with pytest.raises(SimulatedCrash):run(control,gid,req,handler)
        with factory() as db:aid=db.scalar(select(ProbeAttempt.id))
    else:aid,result=run(control,gid,req,handler);assert result is None
    assert run(control,gid,req,handler)==(aid,None) and len(calls)==1
    view=control.get(aid)
    assert view['state']==('sent' if fault=='crash' else 'unknown') and view['actual_fixture_cny'] is None
    assert 'SENSITIVE' not in str(view)
    with factory() as db:assert db.get(ProbeFunding,1).held>0


class KeepAlive(httpx.AsyncByteStream):
    async def __aiter__(self):
        while True:
            await asyncio.sleep(.005);yield b'\n'


def test_keepalive_bytes_cannot_extend_total_deadline(probe):
    control,_,_,req,gid=probe;calls=[]
    def handler(request):calls.append(1);return httpx.Response(200,stream=KeepAlive())
    aid,result=run(control,gid,req,handler,limits=TimeLimits(connect=.01,read=.01,total=.04))
    assert result is None and control.get(aid)['error_code']=='timeout' and len(calls)==1


def test_mock_and_http_layers_cannot_impersonate_each_other(probe):
    control,_,_,req,gid=probe;t=DeepSeekOfficialTransport()
    with pytest.raises(ProbeError,match='offline_components_required'):
        asyncio.run(t.exercise_offline(control,gid,req,'op','batch',resolver=FakeSecretResolver(),wire_transport=MockTransport()))
    with pytest.raises(ProbeError,match='offline_wire_required'):
        asyncio.run(t._post_once(req.body,FAKE_SECRET,None))
    with pytest.raises(ProbeError):asyncio.run(DeniedNetworkTransport().handle_async_request(httpx.Request('POST',ENDPOINT)))
    with pytest.raises(ValueError,match='mock_transport_required'):OfflineRunner(None,Adapter(profile(),{}),t)


def budget_worker(url,schema,gid,operation,batch,send):
    engine=create_engine(url,hide_parameters=True,poolclass=NullPool,connect_args={'options':f'-csearch_path={schema}'})
    try:
        control=ProbeControl(sessionmaker(engine,expire_on_commit=False));request=synthetic_requests()[0]
        try:
            aid,_=control.prepare(UUID(gid),request,operation,batch)
            allowed=control.permit_fixture_send(aid,request) if send else False
            return ('ok',str(aid),allowed)
        except ProbeError as error:return (str(error),None,False)
    finally:engine.dispose()


def test_cross_process_cross_grant_batches_cannot_multiply_global_budget(probe):
    control,factory,schema,req,gid=probe;p=policy(req)
    gid2=control.add_fixture_grant(p,utcnow()-timedelta(seconds=1),utcnow()+timedelta(hours=1),'1',calls_limit=10)
    # One call fits, two do not. Changing batch/grant cannot mint another pool.
    with factory.begin() as db:db.get(ProbeFunding,1).fixture_ceiling=p.reservation()*__import__('decimal').Decimal('1.5')
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(budget_worker,[os.environ['TEST_DATABASE_URL']]*4,[schema]*4,[str(gid),str(gid2)]*2,
            ['op'+str(n) for n in range(4)],['different-batch'+str(n) for n in range(4)],[False]*4))
    assert sum(r[0]=='ok' for r in results)==1
    assert all(r[0] in ('ok','budget_exceeded') for r in results)
    with factory() as db:assert db.get(ProbeFunding,1).held==p.reservation()
    with factory.begin() as db:
        with pytest.raises(IntegrityError):
            with db.begin_nested():db.add(ProbeFunding(id=2,fixture_ceiling=100,approved_real_cny=0,held=0,spent=0,frozen=False));db.flush()


def test_same_operation_one_send_permit_across_processes(probe):
    _,_,schema,_,gid=probe
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(budget_worker,[os.environ['TEST_DATABASE_URL']]*4,[schema]*4,[str(gid)]*4,['same']*4,['same']*4,[True]*4))
    assert len({r[1] for r in results})==1 and sum(r[2] for r in results)==1


def die_after_intent(url,schema,gid):
    engine=create_engine(url,hide_parameters=True,connect_args={'options':f'-csearch_path={schema}'})
    control=ProbeControl(sessionmaker(engine,expire_on_commit=False));request=synthetic_requests()[0]
    aid,_=control.prepare(UUID(gid),request,'abrupt-death','batch');assert control.permit_fixture_send(aid,request)
    os._exit(23)


def test_real_process_death_and_readonly_recovery_never_refunds_unknown(probe):
    control,factory,schema,req,gid=probe
    child=multiprocessing.get_context('spawn').Process(target=die_after_intent,args=(os.environ['TEST_DATABASE_URL'],schema,str(gid)))
    child.start();child.join(20)
    if child.is_alive():child.terminate();child.join();pytest.fail('worker hung')
    assert child.exitcode==23
    with factory.begin() as db:
        row=db.scalar(select(ProbeAttempt));aid=row.id;row.lease_until=utcnow()-timedelta(seconds=1)
    assert control.get(aid)['state']=='unknown' and control.get(aid)['persisted_state']=='sent'
    control.recover_expired()
    assert control.get(aid)['persisted_state']=='unknown'
    with factory() as db:assert db.get(ProbeFunding,1).held==policy(req).reservation()
    with pytest.raises(ProbeError,match='unknown'):control.prepare(gid,req,'new-op','different-batch')


def test_overrun_recorded_pool_frozen_and_manual_review_not_a_refund(probe):
    control,factory,_,req,gid=probe
    aid,_=control.prepare(gid,req,'test','batch');control.permit_fixture_send(aid,req);control.unknown(aid,'timeout')
    assert control.reconcile_fixture(aid,'.1','offline-invoice')
    assert not control.reconcile_fixture(aid,'.1','offline-invoice')
    assert control.get(aid)['actual_fixture_cny']=='0.100000'
    with factory() as db:
        pool=db.get(ProbeFunding,1);assert pool.frozen and pool.held==0 and pool.spent==__import__('decimal').Decimal('.1')
    with pytest.raises(ProbeError,match='frozen'):control.prepare(gid,req,'different','batch')
    with pytest.raises(ProbeError):control.unknown(aid,'timeout')
    with pytest.raises(ProbeError):control.reconcile_fixture(aid,'0','offline-invoice')
    control.unfreeze_fixture('human-reviewed-fixture-invoice')
    with factory() as db:assert db.get(ProbeFunding,1).last_review_digest==digest('human-reviewed-fixture-invoice')
    aid2,_=control.prepare(gid,req,'after-review','batch');assert aid2!=aid


def test_real_authority_cannot_be_inserted_even_in_db(probe):
    control,factory,_,req,gid=probe
    with factory.begin() as db:
        with pytest.raises(IntegrityError):
            with db.begin_nested():db.get(ProbeFunding,1).approved_real_cny=30;db.flush()
    with pytest.raises(ProbeError,match='real_grant_unavailable'):control.add_fixture_grant(policy(req),utcnow(),utcnow()+timedelta(minutes=1),'30',mode='approved')
    with factory.begin() as db:
        with pytest.raises(IntegrityError):
            with db.begin_nested():db.get(ProbeGrant,gid).approved_real_cny=30;db.flush()


def test_expired_reserved_release_only_proven_unsent(probe):
    control,factory,_,req,gid=probe;aid,_=control.prepare(gid,req,'unused','batch')
    with factory.begin() as db:db.get(ProbeAttempt,aid).lease_until=utcnow()-timedelta(seconds=1)
    assert control.get(aid)['state']=='reserved' and control.get(aid)['actual_fixture_cny'] is None
    assert control.recover_expired()==1
    assert control.get(aid)['state']=='reconciled' and control.get(aid)['actual_fixture_cny']=='0.000000'
    assert not control.permit_fixture_send(aid,req)


def test_0006_to_0007_roundtrip_preserves_mock_ledger(migrated_connection):
    conn,cfg=migrated_connection
    command.downgrade(cfg,'0006_cost_ledger')
    conn.execute(text("INSERT INTO cost_budgets(namespace,kind,key,ceiling,call_limit,held,spent,frozen,max_active) VALUES ('legacy','global','all',1,.5,0,0,false,2)"));conn.commit()
    command.upgrade(cfg,'head');command.check(cfg)
    assert conn.scalar(text("SELECT ceiling FROM cost_budgets WHERE namespace='legacy'"))==1
    command.downgrade(cfg,'0006_cost_ledger');command.upgrade(cfg,'head')
    assert conn.scalar(text('SELECT count(*) FROM probe_attempts'))==0


def test_cancellation_preserves_hold_and_never_restarts(probe):
    control,_,_,req,gid=probe;calls=[]
    async def handler(request):calls.append(1);raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):run(control,gid,req,handler)
    with control.factory() as db:aid=db.scalar(select(ProbeAttempt.id))
    assert control.get(aid)['error_code']=='cancelled' and control.get(aid)['actual_fixture_cny'] is None
    assert run(control,gid,req,handler)==(aid,None) and len(calls)==1


def test_no_http_retry_or_proxy_configuration_surface():
    t=DeepSeekOfficialTransport();options=t.client_options()
    assert options['trust_env'] is False and options['follow_redirects'] is False and options['event_hooks']=={}
    assert 'proxy' not in options and 'mounts' not in options
    for limits in [dict(total=0),dict(connect=float('inf')),dict(read=-1),dict(total=46)]:
        with pytest.raises(ProbeError):TimeLimits(**limits)


def test_policy_drift_after_reservation_cannot_send(probe):
    control,factory,_,req,gid=probe;aid,_=control.prepare(gid,req,'before-change','batch')
    with factory.begin() as db:
        grant=db.get(ProbeGrant,gid);p=dict(grant.policy);p['price']=dict(p['price'],peak_output='1.3');grant.policy=p
    with pytest.raises(ProbeError,match='idempotency_payload_mismatch'):control.permit_fixture_send(aid,req)
    assert control.get(aid)['state']=='reserved'


def test_request_key_scope_conflict_and_pool_unknown_across_new_grants(probe):
    control,_,_,req,gid=probe;aid,_=control.prepare(gid,req,'same-key','batch')
    with pytest.raises(ProbeError,match='idempotency_payload_mismatch'):control.prepare(gid,req,'same-key','new-batch')
    gid2=control.add_fixture_grant(policy(req),utcnow()-timedelta(minutes=1),utcnow()+timedelta(minutes=30),'1',calls_limit=10)
    with pytest.raises(ProbeError,match='idempotency_payload_mismatch'):control.prepare(gid2,req,'same-key','batch')
    assert control.permit_fixture_send(aid,req);control.unknown(aid,'timeout')
    with pytest.raises(ProbeError,match='pool_frozen_or_unknown'):control.prepare(gid2,req,'new-key','new-batch')
    with pytest.raises(ProbeError,match='manual_review_unresolved'):control.unfreeze_fixture('not-yet-reviewed')


def test_usd_fx_worst_case_reservation_never_uses_cache_discount():
    from decimal import Decimal
    p=policy();expected=Decimal('.014910')
    assert p.reservation()==expected
    # Higher off-peak/cached rates (misconfiguration) cannot lower the bound.
    p2=policy(price=p.price.model_dump(mode='json')|{'offpeak_miss':'0.4','offpeak_hit':'0.006'})
    assert p2.reservation()>expected
    with pytest.raises(ValueError):policy(fx=p.fx.model_dump(mode='json')|{'cny_per_usd':'NaN'})
    with pytest.raises(ProbeError):policy(token_evidence_kind='pretend_supplier_verified').check(utcnow())


def test_decoder_requires_consistent_documented_usage_not_mock_defaults():
    p=policy();r=packet()
    for field in ['total_tokens','prompt_cache_miss_tokens','prompt_cache_hit_tokens']:
        invalid=json.loads(json.dumps(r));invalid['usage'].pop(field)
        with pytest.raises(ProbeError,match='response_invalid'):decode_official(canonical(invalid),p)
    invalid=json.loads(json.dumps(r));invalid['choices'][0]['index']=False
    with pytest.raises(ProbeError):decode_official(canonical(invalid),p)


def test_already_reserved_attempt_cannot_send_behind_expired_sent(probe):
    control,factory,_,req,gid=probe
    first,_=control.prepare(gid,req,'first','batch');second,_=control.prepare(gid,req,'second','batch')
    assert control.permit_fixture_send(first,req)
    with factory.begin() as db:db.get(ProbeAttempt,first).lease_until=utcnow()-timedelta(seconds=1)
    with pytest.raises(ProbeError,match='pool_frozen_or_unknown'):control.permit_fixture_send(second,req)
    assert control.get(second)['persisted_state']=='reserved'
