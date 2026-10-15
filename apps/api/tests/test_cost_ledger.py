"""PostgreSQL budget concurrency/recovery, no HTTP provider and synthetic invoices."""
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.cost_ledger import Ledger, LedgerError, digest
from app.model_adapter import Profile, Adapter, MockTransport, OfflineRunner, SimulatedCrash
from app.mining_context import MiningContext, UserContext, StopContext
from app.models import CostBudget, CostCall, utcnow
from test_http_api import api

ROOT=Path(__file__).resolve().parents[3]
RATE={'currency':'CNY_SIMULATED','input':'2','cached':'1','output':'8'}


def profile(index=0): return Profile.model_validate(json.loads((ROOT/'docs/evaluation/m12c2-profile-drafts.json').read_text(encoding='utf8'))['profiles'][index])

def context():
    tid=uuid4()
    return MiningContext(project_id=uuid4(),context_revision=1,input_turn_id=tid,user_turns=(UserContext(turn_id=tid,content='我实现了筛选。'),),questions=(),facts=(),stop=StopContext(round_count=1,consecutive_empty_rounds=0,user_stopped=False,session_ended=False))

def response(p,ctx):
    output={'schema_version':2,'candidates':[],'questions':[{'text':'你本人具体做了什么？','purpose':'contribution','source_turn_ids':[str(ctx.input_turn_id)]}],'stop':False,'stop_reason':None}
    return {'model':p.api_model,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output,ensure_ascii=False)}}],'usage':{'prompt_tokens':100,'completion_tokens':20}}

@pytest.fixture
def ledger_stack(migrated_connection):
    conn,_=migrated_connection
    schema=conn.scalar(text('SELECT current_schema()'));conn.commit()
    engine=create_engine(os.environ['TEST_DATABASE_URL'],poolclass=NullPool,connect_args={'options':f'-csearch_path={schema}'},hide_parameters=True)
    factory=sessionmaker(engine,expire_on_commit=False)
    ledger=Ledger(factory,'test-batch')
    scopes={('global','all'):'1',('model','DeepSeek-V4.1-Flash'):'1',('model','Qwen3.7-Plus'):'1',('provider','deepseek_official'):'1',('provider','bailian'):'1'}
    for n in range(8): scopes['session','S'+str(n)]='1'
    ledger.configure(scopes)
    yield ledger,factory,schema
    engine.dispose()


def reserve(ledger,op='one',session='S0',amount='.1',p=None): return ledger.reserve(op,digest('synthetic request'),p or profile(),session,amount,RATE)[0]


def worker(url,schema,op,session,amount,send):
    engine=create_engine(url,poolclass=NullPool,connect_args={'options':f'-csearch_path={schema}'},hide_parameters=True)
    try:
        ledger=Ledger(sessionmaker(engine,expire_on_commit=False),'test-batch')
        try:
            cid,_=ledger.reserve(op,digest('synthetic request'),profile(),session,amount,RATE)
            permit=ledger.sent(cid) if send else False
            return ('ok',str(cid),permit)
        except LedgerError as error: return (str(error),None,False)
    finally: engine.dispose()


def test_multiprocess_budget_and_single_dispatch(ledger_stack):
    ledger,_,schema=ledger_stack
    # Separate OS processes, engines, connections; all target the fixture schema.
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(worker,[os.environ['TEST_DATABASE_URL']]*4,[schema]*4,['same']*4,['S0']*4,['.1']*4,[True]*4))
    assert len({r[1] for r in results})==1 and sum(r[2] for r in results)==1
    cid=next(r[1] for r in results)
    assert ledger.get(__import__('uuid').UUID(cid))['state']=='sent'


def test_multiprocess_budget_never_overspends(ledger_stack):
    ledger,factory,schema=ledger_stack
    with factory.begin() as db:
        for b in db.scalars(select(CostBudget)): b.ceiling=Decimal('.25')
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(worker,[os.environ['TEST_DATABASE_URL']]*4,[schema]*4,[str(n) for n in range(4)],['S'+str(n) for n in range(4)],['.2']*4,[False]*4))
    assert sum(r[0]=='ok' for r in results)==1
    assert all(r[0] in ('ok','budget_exceeded') for r in results)
    with factory() as db: assert db.get(CostBudget,('test-batch','global','all')).held==Decimal('.2')


def test_scopes_limits_and_active_slots(ledger_stack):
    ledger,factory,_=ledger_stack
    reserve(ledger)
    with pytest.raises(LedgerError,match='concurrency_exceeded'): reserve(ledger,'two')
    reserve(ledger,'two','S1')
    with pytest.raises(LedgerError,match='concurrency_exceeded'): reserve(ledger,'three','S2')
    with pytest.raises(LedgerError,match='budget_exceeded'): reserve(ledger,'large','S3','.6')


def test_idempotency_scope_request_profile_and_rate_conflict(ledger_stack):
    ledger,_,_=ledger_stack
    cid=reserve(ledger)
    assert reserve(ledger)==cid
    for changes in [{'request_hash':digest('different')},{'session':'S1'},{'amount':'.2'},{'profile':profile(1)},{'rate':dict(RATE,output='9')}]:
        args=dict(operation='one',request_hash=digest('synthetic request'),profile=profile(),session='S0',amount='.1',rate=RATE);args.update(changes)
        with pytest.raises(LedgerError,match='idempotency_payload_mismatch'): ledger.reserve(**args)


def test_unknown_holds_and_readonly_expiry_then_reconcile(ledger_stack):
    ledger,factory,_=ledger_stack
    cid=reserve(ledger);assert ledger.sent(cid)
    with factory.begin() as db: db.get(CostCall,cid).lease_until=utcnow()-timedelta(seconds=1)
    assert ledger.get(cid)['state']=='unknown' and ledger.get(cid)['persisted_state']=='sent'
    with pytest.raises(LedgerError,match='unknown'): reserve(ledger,'next','S1',p=profile(1))
    assert ledger.recover_expired()==1 and ledger.get(cid)['persisted_state']=='unknown'
    with factory() as db: assert db.get(CostBudget,('test-batch','global','all')).held==Decimal('.1')
    assert ledger.reconcile(cid,'.03','synthetic-invoice')
    assert not ledger.reconcile(cid,'.03','synthetic-invoice')
    with pytest.raises(LedgerError,match='invoice_mismatch'): ledger.reconcile(cid,'.04','synthetic-invoice')
    with pytest.raises(LedgerError,match='invalid_transition'): ledger.unknown(cid,'timeout')
    reserve(ledger,'next','S1')


def test_expired_unsent_has_no_dispatch_and_can_explicitly_release(ledger_stack):
    ledger,factory,_=ledger_stack
    cid=reserve(ledger)
    with factory.begin() as db: db.get(CostCall,cid).lease_until=utcnow()-timedelta(seconds=1)
    assert not ledger.sent(cid)
    assert ledger.get(cid)['actual'] is None
    ledger.recover_expired()
    assert ledger.get(cid)['actual']=='0.000000'
    assert reserve(ledger)==cid and not ledger.sent(cid)


def test_invoice_overrun_actual_not_clamped_and_all_scopes_frozen(ledger_stack):
    ledger,factory,_=ledger_stack
    cid=reserve(ledger);ledger.sent(cid);ledger.unknown(cid,'timeout');ledger.reconcile(cid,'.3','synthetic-invoice')
    assert ledger.get(cid)['actual']=='0.300000'
    with pytest.raises(LedgerError,match='frozen'): reserve(ledger,'next','S1',p=profile(1))
    with factory() as db:
        assert db.get(CostBudget,('test-batch','global','all')).spent==Decimal('.3')
        assert db.get(CostBudget,('test-batch','global','all')).held==0


@pytest.mark.parametrize('fault',['timeout','crash',429,503,'refusal','length','schema','usage'])
def test_mock_failures_no_retry_no_refund(ledger_stack,fault):
    ledger,_,_=ledger_stack;p=profile();ctx=context();packet=response(p,ctx)
    if isinstance(fault,int):packet={'status':fault}
    elif fault=='refusal':packet['choices'][0]['message']['refusal']='synthetic refusal'
    elif fault=='length':packet['choices'][0]['finish_reason']='length'
    elif fault=='schema':packet['choices'][0]['message']['content']='{"status":"user_confirmed"}'
    elif fault=='usage':packet['usage']['prompt_tokens']=True
    transport=MockTransport(packet,fault=fault if fault in ('timeout','crash') else None)
    runner=OfflineRunner(ledger,Adapter(p,{}),transport)
    if fault=='crash':
        with pytest.raises(SimulatedCrash): runner.run(ctx,'one','S0','.1',RATE)
        with ledger.factory() as db:cid=db.scalar(select(CostCall.id))
        assert ledger.get(cid)['state']=='sent'
    else:
        cid,result=runner.run(ctx,'one','S0','.1',RATE);assert result is None
        assert ledger.get(cid)['state']=='unknown'
    assert runner.run(ctx,'one','S0','.1',RATE)[1] is None
    assert transport.calls==1 and ledger.get(cid)['actual'] is None


@pytest.mark.parametrize('index',[0,1,2])
def test_provider_contract_and_usage_accounting(ledger_stack,index):
    ledger,_,_=ledger_stack;p=profile(index);ctx=context();packet=response(p,ctx)
    packet['usage'].update(prompt_cache_hit_tokens=40,completion_tokens_details={'reasoning_tokens':5})
    transport=MockTransport(packet);adapter=Adapter(p,{})
    request=adapter.build_request(ctx)
    assert request['max_tokens']==1200 and request['model']==p.api_model
    assert ('thinking' in request)==(index==0) and 'Authorization' not in str(request)
    cid,result=OfflineRunner(ledger,adapter,transport).run(ctx,'one','S0','.1',RATE)
    assert result and result.usage=={'input':100,'output':20,'cached':40,'reasoning':5}
    assert result.output.tokens_in==100 and result.output.tokens_out==20
    assert ledger.get(cid)['estimated']=='0.000320'
    assert ledger.get(cid)['actual'] is None
    ledger.reconcile(cid,'0','synthetic-mock-free')
    assert ledger.report()['provider:'+p.provider]['input_tokens_mock']==100


def test_0005_upgrade_rollback_compatibility(migrated_connection):
    conn,cfg=migrated_connection
    command.downgrade(cfg,'0005_answer_questions')
    sid,pid=uuid4(),uuid4()
    conn.execute(text("INSERT INTO experience_sessions(id,access_token_hash,status,created_at,updated_at) VALUES (:id,:h,'active',now(),now())"),{'id':sid,'h':'0'*64})
    conn.execute(text("INSERT INTO experience_projects(id,session_id,raw_input,created_at) VALUES (:id,:sid,'synthetic legacy',now())"),{'id':pid,'sid':sid});conn.commit()
    command.upgrade(cfg,'head');command.check(cfg)
    assert conn.scalar(text('SELECT raw_input FROM experience_projects WHERE id=:id'),{'id':pid})=='synthetic legacy'
    command.downgrade(cfg,'0005_answer_questions');command.upgrade(cfg,'head')
    assert conn.scalar(text('SELECT count(*) FROM cost_calls'))==0


def crash_after_sent(url,schema):
    engine=create_engine(url,poolclass=NullPool,connect_args={'options':f'-csearch_path={schema}'},hide_parameters=True)
    ledger=Ledger(sessionmaker(engine,expire_on_commit=False),'test-batch')
    cid=reserve(ledger,'process-crash');assert ledger.sent(cid)
    os._exit(17)  # Abrupt death; no finally, no recovery/inference in that process.


def test_actual_process_death_persists_intent_without_resend(ledger_stack):
    ledger,factory,schema=ledger_stack
    child=multiprocessing.get_context('spawn').Process(target=crash_after_sent,args=(os.environ['TEST_DATABASE_URL'],schema))
    child.start();child.join(timeout=20)
    if child.is_alive():child.terminate();child.join();pytest.fail('crash worker hung')
    assert child.exitcode==17
    with factory.begin() as db:
        c=db.scalar(select(CostCall));cid=c.id;c.lease_until=utcnow()-timedelta(seconds=1)
    assert ledger.get(cid)['state']=='unknown' and ledger.get(cid)['persisted_state']=='sent'
    assert not ledger.sent(cid)
    ledger.recover_expired()
    assert reserve(ledger,'process-crash')==cid
    assert not ledger.sent(cid) and ledger.get(cid)['actual'] is None


@pytest.mark.parametrize('kind,key',[('global','all'),('provider','deepseek_official'),('model','DeepSeek-V4.1-Flash'),('session','S0')])
def test_each_budget_scope_is_enforced(ledger_stack,kind,key):
    ledger,factory,_=ledger_stack
    with factory.begin() as db:db.get(CostBudget,('test-batch',kind,key)).ceiling=Decimal('.09')
    with pytest.raises(LedgerError,match='budget_exceeded'):reserve(ledger)
    with factory() as db:assert not db.scalar(select(CostCall.id))


def test_single_invoice_not_applied_to_two_attempts(ledger_stack):
    ledger,_,_=ledger_stack
    a=reserve(ledger);ledger.sent(a);ledger.reconcile(a,'.01','same-invoice')
    b=reserve(ledger,'two','S1');ledger.sent(b)
    with pytest.raises(LedgerError,match='invoice_already_used'):ledger.reconcile(b,'.01','same-invoice')
    assert ledger.get(b)['actual'] is None


def test_bad_usage_and_unknown_price_refuse_estimate(ledger_stack):
    from app.cost_ledger import priced,money
    for n in ('NaN','Infinity','-1'):
        with pytest.raises(LedgerError):money(n)
    with pytest.raises(LedgerError):priced({'input':10,'cached':11,'output':2,'reasoning':0},RATE)
    with pytest.raises(LedgerError):priced({'input':10,'cached':0,'output':2,'reasoning':3},RATE)
    with pytest.raises(LedgerError):priced({'input':10,'cached':0,'output':2,'reasoning':0},dict(RATE,currency='USD'))


def test_insufficient_mock_reservation_refuses_before_transport(ledger_stack):
    ledger,_,_=ledger_stack;p=profile();ctx=context();transport=MockTransport(response(p,ctx))
    with pytest.raises(LedgerError,match='reservation_below_mock_upper_bound'):
        OfflineRunner(ledger,Adapter(p,{}),transport).run(ctx,'tiny','S0','.000001',RATE)
    assert transport.calls==0


def test_exactly_300_second_clock_skew_is_accepted_without_relaxing_301(api,monkeypatch):
    from test_idempotency import headers,ROOT,BODY
    from app import idempotency as idem
    client,_=api;now=utcnow().replace(microsecond=0)
    monkeypatch.setattr(idem,'utcnow',lambda:now)
    h,_=headers(issued=int(now.timestamp())+300)
    assert client.post(ROOT+'/sessions',headers=h,json=BODY).status_code==201
