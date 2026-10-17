"""Persistent proposal tests. Fictional approvals/USD/FX/token bounds ONLY.

The fixed synthetic request is NOT a live multi-round request. The fake model
supplies output for the current real business snapshot; no raw user data/keys.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker

from test_http_api import api
from test_idempotency import headers
from test_paid_control import policy, authorize
from test_deepseek_bridge import role_capability, response
from test_deepseek_mining_integration import offline_guard, test_database_only
from app import facts, mining, idempotency
from app.mining_api import Start, get_mining_factory
from app.main import app
from app.mining_provider import MiningOutputV2
from app.mining_validation import validate_context_v2
from app.deepseek_contract import synthetic_requests, decode_official, FAKE_SECRET, ProbeError
from app.deepseek_transport import DeepSeekOfficialTransport
from app.models import ExperienceSession, ExperienceProject, ConversationTurn, ExperienceFact, MiningRun, utcnow
from app.paid_models import PaidFunding, PaidCall, PaidGrant
from app.paid_control import PaidAdmin, PaidControl
from app.cost_ledger import canonical, digest
from offline_paid_binding import BindingControl, install_test_proposal, stage_test_plan, scopes


@pytest.fixture
def binding(api, role_capability):
    if not role_capability:
        pytest.fail('Binding prototype requires restricted LOGIN tests, never skip')
    client, factory = api
    engine = factory.kw['bind']
    with factory() as db:
        schema = db.scalar(text('SELECT current_schema()'))
        ledger_id = db.get(PaidFunding, 1).ledger_id
    admin = PaidAdmin(factory)
    admin.approve_total('1', digest('SYNTHETIC total'))
    for kind, key in [('provider','deepseek_official'),('model','deepseek-flash')]:
        admin.approve_scope(kind,key,'1',digest('SYNTHETIC scope'))
    requests = synthetic_requests(256)
    p = policy()
    cert = p.certificates[0].model_dump(mode='json')
    p = p.model_copy(update={'certificates': tuple(type(p.certificates[0]).model_validate(cert | {'request_sha':r.fingerprint}) for r in requests)})
    gid = authorize(admin,p)
    paid = PaidControl(engine,schema,ledger_id)
    paid.fixture_grant = gid  # TEST staging metadata, no production method change
    role = 'binding_test_' + uuid4().hex
    password = uuid4().hex  # short-lived TEST DB password, not a supplier key
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('pathwise.fixture_password',:p,true)"), {'p':password})
        conn.execute(text(f'''DO $$ BEGIN EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD %L',
          '{role}',current_setting('pathwise.fixture_password')); END $$'''))
        install_test_proposal(conn,schema,role)
    runtime = create_engine(engine.url.set(username=role,password=password),poolclass=NullPool,hide_parameters=True)
    app.dependency_overrides[get_mining_factory] = lambda: factory
    env = SimpleNamespace(client=client,factory=factory,admin=admin,paid=paid,schema=schema,
        control=BindingControl(runtime,schema,ledger_id),role=role,grant=gid,policy=p,
        ledger_id=ledger_id,scope_key=secrets.token_bytes(32),requests=requests)
    try: yield env
    finally:
        runtime.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


def new_run(e, *, case='S03', turn='b', actor='synthetic-user-A', existing=None):
    req = next(r for r in e.requests if (r.case_id,r.turn_key)==(case,turn))
    ctx = json.loads(json.loads(req.body)['messages'][1]['content'])
    if existing is None:
        token = secrets.token_urlsafe(32)
        with e.factory() as db, db.begin():
            session = ExperienceSession(access_token_hash=facts.token_hash(token))
            db.add(session);db.flush()
            sid = session.id
            project = ExperienceProject(id=UUID(ctx['project_id']),session_id=sid,raw_input=ctx['user_turns'][0]['content'])
            source = ConversationTurn(id=UUID(ctx['input_turn_id']),session_id=sid,role='user',content=ctx['user_turns'][0]['content'])
            db.add_all([project,source]);db.flush()
            actor_scope,session_scope = scopes(e.scope_key,actor,sid)
            db.execute(text(f'INSERT INTO "{e.schema}".binding_identity VALUES(:sid,:actor,:session)'),
                dict(sid=sid,actor=actor_scope,session=session_scope))
            for kind,scope in [('user',actor_scope),('session',session_scope)]:
                db.execute(text(f'''INSERT INTO "{e.schema}".binding_limits VALUES(:kind,:scope,'CNY',1,20,2,:evidence)
                    ON CONFLICT DO NOTHING'''),dict(kind=kind,scope=scope,evidence=digest('fixture subcap not funding')))
    else:
        sid,token,actor_scope,session_scope = existing.sid,existing.token,existing.actor_scope,existing.session_scope
        with e.factory() as db, db.begin():
            db.add(ConversationTurn(id=UUID(ctx['input_turn_id']),session_id=sid,role='user',content=ctx['user_turns'][0]['content']))
    with e.factory() as db:
        revision = db.get(ExperienceSession,sid).context_revision
    h,_ = headers('mining_run','session:'+str(sid),token)
    key = idempotency.parse(h['Idempotency-Key'],token,'mining_run','session:'+str(sid))
    body = Start(project_id=ctx['project_id'],base_revision=revision,input_turn_id=ctx['input_turn_id'])
    rid,fresh = mining.reserve(e.factory,sid,token,key,body)
    assert fresh
    return SimpleNamespace(sid=sid,token=token,rid=rid,key=key,body=body,request=req,
        actor_scope=actor_scope,session_scope=session_scope)


def claim_plan(e, run):
    run.snapshot = mining.claim(e.factory,run.sid,run.token,run.rid,contract_version=2)
    stage_test_plan(e.factory,e.schema,e.paid,run.sid,run.token,run.rid,run.snapshot.context,run.request)


def held(e):
    with e.factory() as db: return db.get(PaidFunding,1).held


def count(e, model):
    with e.factory() as db: return db.scalar(select(func.count()).select_from(model))


def business_state(e,run):
    with e.factory() as db: return db.get(MiningRun,run.rid).state


def wait_for_binding_lock(factory):
    # pg_locks.database is NULL for transactionid locks: attribute the waiter
    # via pg_stat_activity.datname, rather than filtering the lock's NULL field.
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        with factory() as db:
            waiting=db.scalar(text("""SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING(pid)
              WHERE NOT l.granted AND l.locktype='transactionid' AND a.datname=current_database()"""))
        if waiting: return
        time.sleep(.02)
    raise AssertionError('Expected isolated transaction lock was not observed')


class FakeBoundProvider:
    output_contract_version = 2
    def __init__(self,e,run,*,fault=None,after=None):
        self.e,self.run,self.fault,self.after=e,run,fault,after
        self.calls=0
    def reserve_cost(self): raise mining.MiningError(503,'ai_provider_unapproved')
    async def mine(self,input):
        # execute() owns the actual business claim and final completion checks.
        stage_test_plan(self.e.factory,self.e.schema,self.e.paid,self.run.sid,self.run.token,self.run.rid,input.context,self.run.request)
        self.e.control.invoke('bind',self.run.rid)
        permission = self.e.control.invoke('permit',self.run.rid)
        if not permission['permitted']: raise TimeoutError()
        def respond(request):
            assert request.content == self.run.request.body
            self.calls+=1
            if self.after: self.after()
            if self.fault=='timeout': raise httpx.ReadTimeout('synthetic supplier text')
            packet = response(self.run.request)
            if self.fault=='source':
                out=json.loads(packet['choices'][0]['message']['content'])
                out['candidates'][0]['citation']['quote']='我部署了虚构系统。'
                packet['choices'][0]['message']['content']=canonical(out)
            return httpx.Response(200,json=packet)
        try:
            raw = await DeepSeekOfficialTransport()._post_once(self.run.request.body,FAKE_SECRET,httpx.MockTransport(respond))
            result = decode_official(raw,SimpleNamespace(input_upper_bound=5000,output_cap=256))
            self.e.control.invoke('received',self.run.rid,dict(input_tokens=result.usage['input'],output_tokens=result.usage['output']))
            return validate_context_v2(input.context,result.output)
        except ProbeError:
            self.e.control.invoke('unknown',self.run.rid)
            raise TimeoutError('fixture unknown') from None


def test_atomic_binding_and_same_key_recovery(binding):
    e=binding;run=new_run(e);claim_plan(e,run)
    row=e.control.invoke('bind',run.rid)
    assert row['created'] and held(e)==Decimal('.014910')
    assert e.control.invoke('bind',run.rid)==dict(call_id=row['call_id'],created=False)
    assert mining.reserve(e.factory,run.sid,run.token,run.key,run.body)==(run.rid,False)
    metadata,state,amount,actual=e.control.read(run.rid)
    assert state=='reserved' and actual is None and amount==held(e)
    assert metadata.run_id==run.rid and metadata.ledger_id==e.ledger_id
    assert count(e,PaidCall)==1
    assert run.token not in metadata.model_dump_json()


def test_binding_and_central_reserve_rollback_together(binding):
    e=binding;run=new_run(e);claim_plan(e,run)
    # A real constraint/trigger failure AFTER paid_runtime.reserve must roll back
    # both the paid row/held amount and binding, not leave a hidden orphan call.
    with e.factory.begin() as db:
        db.execute(text(f'''CREATE FUNCTION "{e.schema}".reject_fixture_binding() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'synthetic_insert_failure'; END $$'''))
        db.execute(text(f'''CREATE TRIGGER reject_fixture BEFORE INSERT ON "{e.schema}".mining_call_bindings
          FOR EACH ROW EXECUTE FUNCTION "{e.schema}".reject_fixture_binding()'''))
    with pytest.raises(DBAPIError,match='synthetic_insert_failure'): e.control.invoke('bind',run.rid)
    assert held(e)==0 and count(e,PaidCall)==0


def test_business_reserve_alone_and_unauthorized_staging(binding):
    e=binding;run=new_run(e)
    assert count(e,PaidCall)==0 and held(e)==0
    with pytest.raises(DBAPIError,match='binding_business_inactive'): e.control.invoke('bind',run.rid)
    snapshot=mining.claim(e.factory,run.sid,run.token,run.rid,contract_version=2)
    with pytest.raises(PermissionError):
        stage_test_plan(e.factory,e.schema,e.paid,run.sid,'wrong-token',run.rid,snapshot.context,run.request)
    assert count(e,PaidCall)==0


@pytest.mark.parametrize('scope,field,value',[('user','ceiling','.001'),('session','ceiling','.001'),
    ('user','calls_limit','1'),('user','concurrent_limit','1')])
def test_user_session_caps_use_central_calls_not_another_pool(binding,scope,field,value):
    e=binding;a=new_run(e);claim_plan(e,a)
    if field!='ceiling': e.control.invoke('bind',a.rid)
    target=a.actor_scope if scope=='user' else a.session_scope
    with e.factory.begin() as db:
        db.execute(text(f'UPDATE "{e.schema}".binding_limits SET {field}=:v WHERE kind=:kind AND scope=:scope'),
            dict(v=Decimal(value),kind=scope,scope=target))
    b=a
    if field!='ceiling': b=new_run(e,case='S02',turn='b');claim_plan(e,b)
    before=held(e)
    with pytest.raises(DBAPIError,match='binding_scope_exceeded'): e.control.invoke('bind',b.rid)
    assert held(e)==before and count(e,PaidCall)==(0 if field=='ceiling' else 1)


@pytest.mark.parametrize('failure',['global','provider','model','single_call','grant_revoke','grant_expire'])
def test_original_paid_admission_still_enforced(binding,failure):
    e=binding;run=new_run(e)
    if failure=='grant_expire':
        gid=authorize(e.admin,e.policy,starts_at=utcnow()-timedelta(minutes=1),expires_at=utcnow()+timedelta(seconds=1))
        e.paid.fixture_grant=gid
    if failure=='single_call': e.paid.fixture_grant=authorize(e.admin,e.policy,call_limit='.001')
    claim_plan(e,run)
    if failure=='global':
        with e.factory.begin() as db: db.get(PaidFunding,1).ceiling=Decimal('.001')
    if failure in ('provider','model'):
        e.admin.approve_scope(failure,'deepseek_official' if failure=='provider' else 'deepseek-flash','0',digest('fixture lower scope'))
    if failure=='grant_revoke': e.admin.revoke(e.grant,digest('fixture revoke'))
    if failure=='grant_expire': time.sleep(1.1)
    with pytest.raises(DBAPIError,match='paid_budget_exceeded|paid_scope_exceeded|paid_grant_inactive'):
        e.control.invoke('bind',run.rid)
    assert held(e)==0 and count(e,PaidCall)==0


def test_permission_recheck_and_unique_paid_call(binding):
    e=binding;run=new_run(e);claim_plan(e,run)
    e.control.invoke('bind',run.rid)
    # Direct table writes and the old unbound paid_runtime are not granted.
    with e.control.engine.begin() as conn:
        assert conn.scalar(text(f"SELECT has_function_privilege(current_user,'{e.schema}.paid_runtime(text,text,jsonb)','EXECUTE')")) is False
    for sql in [f'UPDATE "{e.schema}".paid_funding SET ceiling=100',f'DELETE FROM "{e.schema}".mining_call_bindings',
                f'UPDATE "{e.schema}".binding_limits SET ceiling=100']:
        with pytest.raises(DBAPIError,match='permission denied'):
            with e.control.engine.begin() as conn: conn.execute(text(sql))
    owner=BindingControl(e.factory.kw['bind'],e.schema,e.ledger_id)
    with pytest.raises(DBAPIError,match='binding_restricted_login_required'): owner.invoke('permit',run.rid)
    with e.factory.begin() as db:
        db.execute(text(f'GRANT EXECUTE ON FUNCTION "{e.schema}".paid_runtime(text,text,jsonb) TO "{e.role}"'))
    with pytest.raises(DBAPIError,match='binding_restricted_login_required'): e.control.invoke('permit',run.rid)


def test_other_operation_cannot_rebind_same_paid_call(binding):
    e=binding;run=new_run(e);claim_plan(e,run);e.control.invoke('bind',run.rid)
    with pytest.raises(DBAPIError):
        with e.factory.begin() as db:
            row=db.execute(text(f'SELECT * FROM "{e.schema}".mining_call_bindings')).mappings().one()
            values=dict(row)|dict(run_id=uuid4(),root_run_id=uuid4(),operation_hash=digest('different actor operation'))
            cols=','.join(values);params=','.join(':'+k for k in values)
            db.execute(text(f'INSERT INTO "{e.schema}".mining_call_bindings({cols}) VALUES({params})'),values)
    assert count(e,PaidCall)==1


@pytest.mark.parametrize('failure',['ledger','account','configuration','inconsistent'])
def test_mismatched_binding_metadata_fails_closed(binding,failure):
    e=binding;run=new_run(e);claim_plan(e,run)
    if failure=='ledger':
        wrong=BindingControl(e.control.engine,e.schema,uuid4())
        with pytest.raises(DBAPIError,match='binding_ledger_mismatch'): wrong.invoke('bind',run.rid)
        return
    if failure=='inconsistent':
        result=e.control.invoke('bind',run.rid)
        with e.factory.begin() as db: db.get(PaidCall,UUID(result['call_id'])).request_hash=digest('fixture corrupt call')
        with pytest.raises(DBAPIError,match='binding_ledger_inconsistent'): e.control.invoke('bind',run.rid)
        return
    # Owner fault injection replaces only an unbound TEST plan; immutable update
    # is separately tested. Never mutate a historical grant/policy or migration.
    with e.factory.begin() as db:
        row=dict(db.execute(text(f'DELETE FROM "{e.schema}".binding_plans WHERE run_id=:r RETURNING *'),{'r':run.rid}).mappings().one())
        row['account_sha' if failure=='account' else 'policy_sha']=digest('fixture mismatch')
        db.execute(text(f'''INSERT INTO "{e.schema}".binding_plans({','.join(row)}) VALUES({','.join(':'+k for k in row)})'''),row)
    with pytest.raises(DBAPIError,match='binding_plan_invalid'): e.control.invoke('bind',run.rid)
    assert count(e,PaidCall)==0


@pytest.mark.parametrize('fault',[None,'source','timeout','stale'])
def test_real_business_machine_and_bill_liability_are_separate(binding,fault):
    e=binding;run=new_run(e)
    def change():
        with e.factory() as db,db.begin(): facts.add_turn(db,run.sid,run.token,'合成：并发增加资料。')
    p=FakeBoundProvider(e,run,fault=fault,after=change if fault=='stale' else None)
    asyncio.run(mining.execute(e.factory,p,run.sid,run.token,run.rid))
    expected={None:'completed','source':'failed','timeout':'unknown','stale':'stale'}[fault]
    assert business_state(e,run)==expected
    _,paid_state,reserved,actual=e.control.read(run.rid)
    assert paid_state==('unknown' if fault=='timeout' else 'response_received')
    assert actual is None and held(e)==reserved==Decimal('.014910')
    assert count(e,ExperienceFact)==(1 if fault is None else 0)
    asyncio.run(mining.execute(e.factory,p,run.sid,run.token,run.rid))
    assert p.calls==1


def test_unknown_freezes_new_operations_and_get_never_changes_or_sends(binding):
    e=binding;a=new_run(e);claim_plan(e,a);e.control.invoke('bind',a.rid);assert e.control.invoke('permit',a.rid)['permitted']
    e.control.invoke('unknown',a.rid)
    before=held(e)
    b=new_run(e,case='S02',turn='b',actor='synthetic-user-B');claim_plan(e,b)
    with pytest.raises(DBAPIError,match='binding_unsettled_pool'): e.control.invoke('bind',b.rid)
    for _ in range(2): assert e.control.read(a.rid)[1]=='unknown'
    assert held(e)==before and count(e,PaidCall)==1
    assert e.control.invoke('bind',a.rid)['created'] is False


def test_business_erasure_preserves_minimal_independent_audit(binding):
    e=binding;run=new_run(e);claim_plan(e,run);row=e.control.invoke('bind',run.rid)
    assert e.control.invoke('permit',run.rid)['permitted']
    result=e.client.delete('/api/v1/experience/sessions/'+str(run.sid),headers={'Authorization':'Bearer '+run.token})
    assert result.status_code==204
    metadata,state,amount,actual=e.control.read(run.rid)
    assert metadata.binding_state=='tombstoned' and metadata.tombstoned_at is not None
    assert state=='sent' and amount==held(e) and actual is None
    with e.factory() as db:
        assert db.get(MiningRun,run.rid) is None and db.get(ExperienceSession,run.sid) is None
        assert db.scalar(text(f'SELECT count(*) FROM "{e.schema}".binding_identity'))==0
        assert db.scalar(text(f'SELECT count(*) FROM "{e.schema}".binding_plans'))==0
    with pytest.raises(DBAPIError,match='binding_business_deleted'): e.control.invoke('permit',run.rid)
    e.control.invoke('unknown',run.rid)  # bill recording remains possible after erasure
    assert e.control.read(run.rid)[1]=='unknown' and count(e,PaidCall)==1


def test_explicit_reconciliation_cannot_restore_send_permission(binding):
    e=binding;run=new_run(e);claim_plan(e,run);row=e.control.invoke('bind',run.rid)
    assert e.control.invoke('permit',run.rid)['permitted']
    e.control.invoke('unknown',run.rid)
    invoice=digest('one synthetic invoice not a real bill')
    assert e.admin.reconcile(row['call_id'],Decimal('.001'),invoice,digest('fixture manual review'))
    assert not e.admin.reconcile(row['call_id'],Decimal('.001'),invoice,digest('same fixture'))
    assert held(e)==0 and e.control.read(run.rid)[1]=='reconciled'
    assert e.control.invoke('permit',run.rid)['permitted'] is False
    assert count(e,PaidCall)==1


def process_action(url,schema,ledger,rid,action,crash=False,queue=None):
    engine=create_engine(url,poolclass=NullPool,hide_parameters=True)
    try:
        usage=dict(input_tokens=100,output_tokens=20) if action=='received' else None
        result=BindingControl(engine,schema,ledger).invoke(action,UUID(rid),usage)
        if crash: os._exit(23)  # genuine process death AFTER durable DB commit
        if queue is not None: queue.put(result)
    except DBAPIError as error:
        code=getattr(getattr(error.orig,'diag',None),'message_primary',None)
        if queue is not None and code in ('binding_scope_exceeded','paid_budget_exceeded','paid_concurrency_exceeded'):
            queue.put({'rejected':code})
        else: raise
    finally: engine.dispose()


@pytest.mark.parametrize('action',['bind','permit','received'])
def test_process_exit_preserves_commit_and_never_reissues_permission(binding,action):
    e=binding;run=new_run(e);claim_plan(e,run)
    if action!='bind': e.control.invoke('bind',run.rid)
    if action=='received':
        assert e.control.invoke('permit',run.rid)['permitted']
    child_action=action
    ctx=multiprocessing.get_context('spawn')
    child=ctx.Process(target=process_action,args=(e.control.engine.url.render_as_string(hide_password=False),e.schema,str(e.ledger_id),str(run.rid),child_action,True))
    child.start();child.join(20)
    if child.is_alive(): child.terminate();child.join();pytest.fail('fixture child did not finish')
    assert child.exitcode==23
    _,state,amount,actual=e.control.read(run.rid)
    assert state==dict(bind='reserved',permit='sent',received='response_received')[action]
    assert amount==held(e) and actual is None and count(e,ExperienceFact)==0
    assert e.control.invoke('bind',run.rid)['created'] is False
    if action!='bind': assert e.control.invoke('permit',run.rid)['permitted'] is False


def process_business_finish(url,schema,sid,token,rid,context_json,output_json):
    from app.mining_context import MiningContext
    from sqlalchemy.engine import make_url
    target=make_url(url)
    if target.database not in ('pathwise_test','pathwise_e2e') or target.host not in ('localhost','127.0.0.1'):
        raise ValueError('test database required')
    from offline_paid_binding import identifier
    identifier(schema)
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'},hide_parameters=True)
    factory=sessionmaker(engine,expire_on_commit=False)
    mining.complete(factory,UUID(sid),token,UUID(rid),MiningOutputV2.model_validate_json(output_json),
        context=MiningContext.model_validate_json(context_json))
    os._exit(24)  # commit is done, no normal shutdown can explain persistence


def test_process_death_after_business_commit_preserves_both_ledgers(binding):
    e=binding;run=new_run(e);claim_plan(e,run);e.control.invoke('bind',run.rid)
    assert e.control.invoke('permit',run.rid)['permitted']
    e.control.invoke('received',run.rid,dict(input_tokens=100,output_tokens=20))
    packet=response(run.request)
    ctx=multiprocessing.get_context('spawn')
    child=ctx.Process(target=process_business_finish,args=(e.factory.kw['bind'].url.render_as_string(hide_password=False),
        e.schema,str(run.sid),run.token,str(run.rid),run.snapshot.context.model_dump_json(),packet['choices'][0]['message']['content']))
    child.start();child.join(20)
    if child.is_alive(): child.terminate();child.join();pytest.fail('fixture worker timeout')
    assert child.exitcode==24
    assert business_state(e,run)=='completed' and count(e,ExperienceFact)==1
    assert e.control.read(run.rid)[1]=='response_received' and held(e)==Decimal('.014910')
    assert mining.claim(e.factory,run.sid,run.token,run.rid,contract_version=2) is None


def test_concurrent_threads_and_processes_get_one_binding(binding):
    e=binding;run=new_run(e);claim_plan(e,run)
    ctx=multiprocessing.get_context('spawn');queue=ctx.Queue()
    base=(e.control.engine.url.render_as_string(hide_password=False),e.schema,str(e.ledger_id),str(run.rid))
    children=[ctx.Process(target=process_action,args=(*base,'bind',False,queue)) for _ in range(2)]
    for child in children: child.start()
    for child in children:
        child.join(20)
        if child.is_alive(): child.terminate();child.join();pytest.fail('fixture worker timeout')
        assert child.exitcode==0
    assert sum(queue.get(timeout=2)['created'] for _ in children)==1
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:e.control.invoke('bind',run.rid),range(4)))
    assert sum(r['created'] for r in results)==0 and len({r['call_id'] for r in results})==1
    args=(*base,'permit',False,queue)
    children=[ctx.Process(target=process_action,args=args) for _ in range(2)]
    for child in children: child.start()
    for child in children:
        child.join(20)
        if child.is_alive(): child.terminate();child.join();pytest.fail('fixture worker timeout')
        assert child.exitcode==0
    assert sum(queue.get(timeout=2)['permitted'] for _ in children)==1
    queue.close();queue.join_thread()
    assert count(e,PaidCall)==1 and held(e)==Decimal('.014910')


@pytest.mark.parametrize('cap',['user','global'])
def test_concurrent_distinct_runs_cannot_exceed_shared_cap(binding,cap):
    e=binding;a=new_run(e);claim_plan(e,a)
    b=new_run(e,case='S02',turn='b',actor='synthetic-user-A' if cap=='user' else 'synthetic-user-B');claim_plan(e,b)
    with e.factory.begin() as db:
        if cap=='user': db.execute(text(f'''UPDATE "{e.schema}".binding_limits SET ceiling=.02 WHERE kind='user' AND scope=:s'''),{'s':a.actor_scope})
        else: db.get(PaidFunding,1).ceiling=Decimal('.02')
    ctx=multiprocessing.get_context('spawn');queue=ctx.Queue()
    base=(e.control.engine.url.render_as_string(hide_password=False),e.schema,str(e.ledger_id))
    children=[ctx.Process(target=process_action,args=(*base,str(r.rid),'bind',False,queue)) for r in (a,b)]
    for child in children: child.start()
    for child in children:
        child.join(20)
        if child.is_alive(): child.terminate();child.join();pytest.fail('fixture worker timeout')
        assert child.exitcode==0
    results=[queue.get(timeout=2) for _ in children]
    queue.close();queue.join_thread()
    assert sum(r.get('created',False) for r in results)==1
    expected='binding_scope_exceeded' if cap=='user' else 'paid_budget_exceeded'
    assert sum(r.get('rejected')==expected for r in results)==1
    assert count(e,PaidCall)==1 and held(e)==Decimal('.014910')


def test_session_call_limit_covers_multiple_business_rounds(binding):
    e=binding;a=new_run(e,case='S03',turn='a');claim_plan(e,a);e.control.invoke('bind',a.rid)
    # Complete first business round WITHOUT sending: independent state machines.
    out=MiningOutputV2(candidates=[],questions=[dict(text='合成：请说明个人贡献？',purpose='contribution',source_turn_ids=[a.snapshot.turn_id])])
    mining.complete(e.factory,a.sid,a.token,a.rid,out,context=a.snapshot.context)
    b=new_run(e,existing=a);claim_plan(e,b)
    with e.factory.begin() as db:
        db.execute(text(f'''UPDATE "{e.schema}".binding_limits SET calls_limit=1 WHERE kind='session' AND scope=:s'''),{'s':a.session_scope})
    with pytest.raises(DBAPIError,match='binding_scope_exceeded'): e.control.invoke('bind',b.rid)
    assert count(e,PaidCall)==1 and held(e)==Decimal('.014910')


def test_retry_chain_cannot_buy_another_call_even_after_reconciliation(binding):
    e=binding;a=new_run(e);claim_plan(e,a);row=e.control.invoke('bind',a.rid)
    assert e.control.invoke('permit',a.rid)['permitted']
    e.control.invoke('unknown',a.rid)
    mining.fail(e.factory,a.sid,a.token,a.rid,'unknown','provider_outcome_unknown')
    e.admin.reconcile(row['call_id'],Decimal('.001'),digest('fixture reconciled root'),digest('fixture review'))
    with e.factory() as db: revision=db.get(ExperienceSession,a.sid).context_revision
    h,_=headers('mining_run','session:'+str(a.sid),a.token)
    key=idempotency.parse(h['Idempotency-Key'],a.token,'mining_run','session:'+str(a.sid))
    body=Start(project_id=a.body.project_id,base_revision=revision,retry_of=a.rid,confirm_retry=True)
    rid,_=mining.reserve(e.factory,a.sid,a.token,key,body)
    snapshot=mining.claim(e.factory,a.sid,a.token,rid,contract_version=2)
    stage_test_plan(e.factory,e.schema,e.paid,a.sid,a.token,rid,snapshot.context,a.request)
    with pytest.raises(DBAPIError,match='binding_call_already_used'): e.control.invoke('bind',rid)
    assert count(e,PaidCall)==1 and held(e)==0


def test_permit_transaction_rollback_is_not_a_committed_send_permission(binding):
    e=binding;run=new_run(e);claim_plan(e,run);e.control.invoke('bind',run.rid)
    with pytest.raises(RuntimeError,match='fixture_abort'):
        with e.control.engine.begin() as conn:
            result=conn.scalar(e.control.statement(),e.control.payload('permit',run.rid))
            assert result['permitted']
            raise RuntimeError('fixture_abort')
    assert e.control.read(run.rid)[1]=='reserved' and held(e)==Decimal('.014910')


def test_unattributed_central_calls_block_new_binding(binding):
    e=binding;run=new_run(e);claim_plan(e,run)
    # Existing unbound allocation by an old runtime may not evade user attribution.
    e.paid.reserve(e.grant,run.request,'fixture old unbound','old',digest(canonical(e.policy.model_dump(mode='json'))))
    with pytest.raises(DBAPIError,match='binding_unattributed_call'): e.control.invoke('bind',run.rid)
    assert count(e,PaidCall)==1 and held(e)==Decimal('.014910')


@pytest.mark.parametrize('change',['revoke','user_scope','model_scope'])
def test_final_admission_recheck_between_reserve_and_permit(binding,change):
    e=binding;run=new_run(e);claim_plan(e,run);e.control.invoke('bind',run.rid)
    if change=='revoke': e.admin.revoke(e.grant,digest('fixture revoke before permit'))
    if change=='model_scope': e.admin.approve_scope('model','deepseek-flash','0',digest('fixture lower model cap'))
    if change=='user_scope':
        with e.factory.begin() as db:
            db.execute(text(f'''UPDATE "{e.schema}".binding_limits SET ceiling=0 WHERE kind='user' AND scope=:s'''),{'s':run.actor_scope})
    with pytest.raises(DBAPIError,match='paid_grant_inactive|paid_scope_exceeded|binding_scope_exceeded'):
        e.control.invoke('permit',run.rid)
    assert e.control.read(run.rid)[1]=='reserved' and held(e)==Decimal('.014910')


def test_different_actor_scopes_do_not_borrow_quota(binding):
    e=binding;a=new_run(e);claim_plan(e,a)
    b=new_run(e,case='S02',turn='b',actor='synthetic-user-B');claim_plan(e,b)
    with e.factory.begin() as db:
        db.execute(text(f'''UPDATE "{e.schema}".binding_limits SET ceiling=0 WHERE kind='user' AND scope=:s'''),{'s':a.actor_scope})
    with pytest.raises(DBAPIError,match='binding_scope_exceeded'): e.control.invoke('bind',a.rid)
    e.control.invoke('bind',b.rid)
    assert e.control.read(b.rid)[0].actor_scope==b.actor_scope!=a.actor_scope
    assert count(e,PaidCall)==1


def test_erasure_does_not_reset_same_actor_lifetime_call_limit(binding):
    e=binding;a=new_run(e);claim_plan(e,a);row=e.control.invoke('bind',a.rid)
    assert e.control.invoke('permit',a.rid)['permitted']
    assert e.client.delete('/api/v1/experience/sessions/'+str(a.sid),headers={'Authorization':'Bearer '+a.token}).status_code==204
    e.admin.reconcile(row['call_id'],Decimal('.001'),digest('fixture erased bill'),digest('fixture erased review'))
    with e.factory.begin() as db:
        db.execute(text(f'''UPDATE "{e.schema}".binding_limits SET calls_limit=1 WHERE kind='user' AND scope=:s'''),{'s':a.actor_scope})
    b=new_run(e,case='S02',turn='b');claim_plan(e,b)
    with pytest.raises(DBAPIError,match='binding_scope_exceeded'): e.control.invoke('bind',b.rid)
    assert count(e,PaidCall)==1 and held(e)==0


def test_immutable_binding_and_plan_reject_owner_rewrites(binding):
    e=binding;run=new_run(e);claim_plan(e,run);e.control.invoke('bind',run.rid)
    for sql in [f'UPDATE "{e.schema}".binding_plans SET policy_sha=repeat(\'0\',64)',
                f'UPDATE "{e.schema}".mining_call_bindings SET run_id=gen_random_uuid()',
                f'DELETE FROM "{e.schema}".mining_call_bindings']:
        with pytest.raises(DBAPIError,match='binding_immutable'):
            with e.factory.begin() as db: db.execute(text(sql))
    assert count(e,PaidCall)==1


def test_allocation_wins_delete_race_then_committed_audit_is_tombstoned(binding):
    e=binding;run=new_run(e);claim_plan(e,run)
    with e.control.engine.connect() as conn, ThreadPoolExecutor(max_workers=1) as pool:
        transaction=conn.begin()
        try:
            assert conn.scalar(e.control.statement(),e.control.payload('bind',run.rid))['created']
            def delete_business():
                from app.experience_api import delete_session
                with e.factory() as db,db.begin():
                    return delete_session(run.sid,run.token,db)
            deletion=pool.submit(delete_business)
            wait_for_binding_lock(e.factory)
            transaction.commit()
        finally:
            if transaction.is_active: transaction.rollback()
        assert deletion.result(timeout=5).status_code==204
    assert e.control.read(run.rid)[0].binding_state=='tombstoned'
    assert held(e)==Decimal('.014910') and count(e,PaidCall)==1


def test_delete_wins_allocation_race_then_no_paid_call_is_created(binding):
    e=binding;run=new_run(e);claim_plan(e,run)
    with e.factory() as db, ThreadPoolExecutor(max_workers=1) as pool:
        transaction=db.begin()
        try:
            from app.experience_api import delete_session
            assert delete_session(run.sid,run.token,db).status_code==204
            allocation=pool.submit(e.control.invoke,'bind',run.rid)
            wait_for_binding_lock(e.factory)
            transaction.commit()
        finally:
            if transaction.is_active: transaction.rollback()
        with pytest.raises(DBAPIError,match='binding_business_inactive'): allocation.result(timeout=5)
    assert held(e)==0 and count(e,PaidCall)==0


def test_corrupt_central_balance_is_not_silently_repaired_or_spent(binding):
    e=binding;run=new_run(e);claim_plan(e,run);e.control.invoke('bind',run.rid)
    with e.factory.begin() as db: db.get(PaidFunding,1).held=0
    with pytest.raises(DBAPIError,match='binding_ledger_inconsistent'): e.control.invoke('permit',run.rid)
    with pytest.raises(ValueError,match='binding_ledger_inconsistent'): e.control.read(run.rid)
    assert count(e,PaidCall)==1 and held(e)==0  # no automatic repair/refund


def test_original_0009_exclusivity_survives_even_reconciled_fixture(binding):
    from app.controlled_probe_models import ControlledProbe
    e=binding;run=new_run(e);claim_plan(e,run)
    with e.factory.begin() as db:
        db.add(ControlledProbe(id=1,pool_id=1,grant_id=uuid4(),policy_hash=digest('test tombstone'),
            policy={'execution':'offline_mock'},revoked=False,state='reconciled',reserved=Decimal('.1'),actual_cny=Decimal(0)))
    with pytest.raises(DBAPIError,match='controlled_exclusive_pool'): e.control.invoke('bind',run.rid)
    assert held(e)==0 and count(e,PaidCall)==0
