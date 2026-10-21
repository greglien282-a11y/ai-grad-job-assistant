"""C2e executable observations, NOT an enabled cutoff or future guarantees.

Synthetic random schemas; independent least-capability LOGINs; no production
writer changes. Owner connections only arrange fixtures and inspect all tables.
"""
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
import secrets

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import facts, idempotency as idem, mining
from app.experience_api import get_db
from app.main import app
from app.maintenance_errors import ConversationError
from app.mining_api import Start, get_mining_factory, get_provider
from app.mining_provider import MiningOutput, Candidate, Citation
from app.models import ExperienceFact, ExperienceSession, MiningRun, MiningQuestion, utcnow
from app.mining_context import build_context
from test_http_api import api
from test_idempotency import headers
from test_maintenance_api import (service, seed, key, command, post, recovery,
                                  ambiguous, resolution_body, resolve)
from test_append_api import append_service, body as append_body, post as append_post, recover as append_recover
from test_fact_classification import VALID, bind_mining
from test_experience_read import synthetic, corrupt
from test_legacy_upgrade_handoff import digest

ROOT='/api/v1/experience'


@pytest.fixture
def preflight(append_service):
    s=append_service;role='c2e_legacy_'+uuid4().hex;password=secrets.token_urlsafe(32)
    with s.admin.begin() as db:
        db.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{s.schema}" TO "{role}"'))
        reads=('experience_sessions','experience_projects','conversation_turns','experience_facts',
            'fact_changes','fact_sources','fact_evidence','idempotency_operations','ai_mining_runs',
            'ai_mining_receipts','ai_mining_questions','ai_answer_questions','ai_mining_capacity',
            'conversation_operations','fact_change_sources')
        inserts=('experience_sessions','experience_projects','conversation_turns','experience_facts',
            'fact_changes','fact_sources','fact_evidence','idempotency_operations','ai_mining_runs',
            'ai_mining_receipts','ai_mining_questions','ai_answer_questions')
        for table in reads:db.execute(text(f'GRANT SELECT ON "{table}" TO "{role}"'))
        for table in inserts:db.execute(text(f'GRANT INSERT ON "{table}" TO "{role}"'))
        columns={'experience_sessions':'status,mining_status,updated_at,context_revision',
                 'experience_facts':'statement,status,memory_state,evidence_id,updated_at,version',
                 'ai_mining_runs':'state,error_code,assistant_turn_id,prompt_version,tokens_in,tokens_out',
                 'ai_mining_capacity':'id'}
        for table,cols in columns.items():db.execute(text(f'GRANT UPDATE({cols}) ON "{table}" TO "{role}"'))
        for table in ('idempotency_operations','ai_mining_receipts'):
            db.execute(text(f'GRANT UPDATE ON "{table}" TO "{role}"'))
        db.execute(text(f'GRANT DELETE ON experience_sessions TO "{role}"'))
    engine=create_engine(s.admin.kw['bind'].url.set(username=role,password=password),poolclass=NullPool,
        hide_parameters=True,connect_args={'options':'-csearch_path='+s.schema+' -ctimezone=UTC'})
    s.legacy=sessionmaker(engine,expire_on_commit=False);s.legacy_role=role
    previous_db=app.dependency_overrides[get_db]
    def limited_db():
        with s.legacy() as db,db.begin():yield db
    app.dependency_overrides[get_db]=limited_db
    provider=bind_mining(s)
    app.dependency_overrides[get_mining_factory]=lambda:s.legacy
    s.provider=provider
    try:
        with s.legacy() as db:
            assert db.scalar(text('SELECT current_user'))==role
            assert not db.scalar(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR rolinherit FROM pg_roles WHERE rolname=current_user'))
            assert not db.scalar(text("SELECT has_schema_privilege(current_schema(),'CREATE')"))
            assert not db.scalar(text("SELECT has_any_column_privilege(current_user,'paid_calls','INSERT,UPDATE') OR has_table_privilege(current_user,'paid_calls','DELETE')"))
        yield s
    finally:
        app.dependency_overrides[get_db]=previous_db
        app.dependency_overrides.pop(get_mining_factory,None)
        app.dependency_overrides.pop(get_provider,None)
        engine.dispose()
        with s.admin.begin() as db:
            db.execute(text(f'DROP OWNED BY "{role}" RESTRICT'));db.execute(text(f'DROP ROLE "{role}"'))


def transition(s,b,history_only=False):
    fid=synthetic(s,b,VALID[4])
    if history_only:
        corrupt(s,'experience_facts',"UPDATE experience_facts SET fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0' WHERE id=:id",{'id':fid})
    return fid


def auth(b):return {'Authorization':'Bearer '+b.token}


def legacy_created(s):
    h,token=headers();body={'raw_input':'合成：未来计划改进测试。'}
    r=s.client.post(ROOT+'/sessions',headers=h,json=body);assert r.status_code==201
    d=r.json();b=SimpleNamespace(sid=UUID(d['session_id']),pid=UUID(d['project_id']),
        tid=UUID(d['initial_turn_id']),token=token)
    return b,h,body


def test_legacy_create_edit_review_plan_and_receipt_contract_remains(preflight):
    s=preflight;b,h,body=legacy_created(s)
    statement='我计划下个月编写测试。'
    fact_body={'statement':statement,'source_turn_ids':[str(b.tid)]}
    fh,_=headers('add_fact',f'project:{b.pid}',b.token)
    url=ROOT+f'/projects/{b.pid}/facts'
    r=s.client.post(url,headers=fh,json=fact_body);assert r.status_code==201
    f=r.json()
    for mutation in [dict(action='edit',statement=statement+'暂未开始。'),dict(action='confirm'),
                     dict(action='verify_material',material_reference='synthetic plan',basis='用户自行核对计划材料')]:
        r=s.client.patch(ROOT+f'/facts/{f["id"]}',headers=auth(b),json={**mutation,'expected_version':f['version']})
        assert r.status_code==200;f=r.json()
    app.dependency_overrides[get_mining_factory]=lambda:s.legacy
    summary=s.client.get(ROOT+f'/projects/{b.pid}/experience-summary',headers=auth(b))
    assert summary.status_code==200 and summary.json()['text']==f['statement']
    with s.admin() as db:
        row=db.get(ExperienceFact,UUID(f['id']))
        assert (row.fact_kind,row.progress_stage,row.classification_contract)==VALID[0]
    before=digest(s.admin)
    assert s.client.post(url,headers=fh,json=fact_body).json()==f
    assert s.client.get(ROOT+'/session-creations/recovery',headers=h).json()['session_id']==str(b.sid)
    assert s.client.post(ROOT+'/sessions',headers=h,json=body).status_code==201
    assert digest(s.admin)==before and s.provider.calls==0


@pytest.mark.parametrize('history_only',[False,True])
@pytest.mark.parametrize('route',['turn','fact','patch','close','correct','withdraw','resolution','append','reserve','stop','question'])
def test_typed_new_commands_auth_first_zero_effect(preflight,history_only,route):
    s=preflight;b=seed(s);foreign=seed(s)
    parent=None
    if route=='resolution':parent,_,_=ambiguous(s,b)
    if route=='question':
        with s.admin.begin() as db:
            run=MiningRun(session_id=b.sid,project_id=b.pid,input_turn_id=b.tid,base_revision=1,
                reserved_revision=b.revision,state='completed',lease_until=utcnow()+timedelta(minutes=5))
            db.add(run);db.flush();q=MiningQuestion(session_id=b.sid,run_id=run.id,content='合成问题');db.add(q);db.flush();qid=q.id
    transition(s,b,history_only)
    def request(token):
        h={'Authorization':'Bearer '+token};base=ROOT+f'/sessions/{b.sid}'
        if route=='turn':return s.client.post(base+'/turns',headers=h,json={'content':'未保存的新回答'})
        if route=='fact':return s.client.post(ROOT+f'/projects/{b.pid}/facts',headers=h,json={'statement':'未保存的新事实','source_turn_ids':[str(b.tid)]})
        if route=='patch':return s.client.patch(ROOT+f'/facts/{b.fid}',headers=h,json={'action':'confirm','expected_version':b.version})
        if route=='close':return s.client.post(base+'/end',headers=h)
        if route=='stop':return s.client.post(base+'/mining-stop',headers=h,json={'base_revision':1})
        if route=='question':return s.client.patch(base+f'/mining-questions/{qid}',headers=h,json={'action':'skip','base_revision':1,'expected_version':1})
        kind='mining_run' if route=='reserve' else 'conversation_maintenance_v1'
        h=headers(kind,f'session:{b.sid}',token)[0]
        if route=='reserve':return s.client.post(base+'/mining-runs',headers=h,json={'project_id':str(b.pid),'base_revision':1,'input_turn_id':str(b.tid)})
        if route=='append':return append_post(s,b,append_body(b),h)
        if route=='resolution':return resolve(s,b,parent,dict(contract_version=1,base_revision=1,selected_fact_id=str(b.fid),expected_version=b.version),h)
        return post(s,b,command(b,action=route),h)
    before=digest(s.admin)
    r=request(foreign.token);assert r.status_code==404 and r.json()['error']['code']=='resource_unavailable'
    r=request(b.token);assert r.status_code==409 and r.json()['error']['code']=='fact_contract_upgrade_required'
    assert digest(s.admin)==before and s.provider.calls==0


@pytest.mark.parametrize('history_only',[False,True])
@pytest.mark.parametrize('kind',['creation','turn','fact'])
def test_old_receipts_after_typed_are_replay_not_new_commands(preflight,history_only,kind):
    s=preflight;b,h,body=legacy_created(s);url=ROOT+'/sessions';recovery_url=ROOT+'/session-creations/recovery'
    if kind!='creation':
        operation='add_turn' if kind=='turn' else 'add_fact'
        scope=f'session:{b.sid}' if kind=='turn' else f'project:{b.pid}'
        h,_=headers(operation,scope,b.token)
        url=ROOT+(f'/sessions/{b.sid}/turns' if kind=='turn' else f'/projects/{b.pid}/facts')
        body={'content':'合成旧回答'} if kind=='turn' else {'statement':'合成旧事实','source_turn_ids':[str(b.tid)]}
    original=s.client.post(url,headers=h,json=body);assert original.status_code==201
    transition(s,b,history_only);before=digest(s.admin)
    replay=s.client.post(url,headers=h,json=body)
    assert replay.status_code==201 and replay.headers['idempotency-replayed']=='true'
    assert replay.json()==original.json()
    if kind=='creation':assert s.client.get(recovery_url,headers=h).json()==original.json()
    changed=s.client.post(url,headers=h,json={**body,('raw_input' if kind=='creation' else 'content' if kind=='turn' else 'statement'):'不同输入'})
    assert changed.status_code==409 and changed.json()['error']['code']=='idempotency_payload_mismatch'
    assert digest(s.admin)==before


@pytest.mark.parametrize('action',['correct','withdraw','resolution','append'])
def test_co_receipts_survive_typed_and_cross_contract_keys_do_not_execute(preflight,action):
    s=preflight;b=seed(s);h=key(b)
    if action=='resolution':
        parent,_,_=ambiguous(s,b);body=resolution_body(s,b)
        send=lambda:resolve(s,b,parent,body,h)
    elif action=='append':
        body=append_body(b);send=lambda:append_post(s,b,body,h)
    else:
        body=command(b,action=action);send=lambda:post(s,b,body,h)
    r=send();assert r.status_code==201;original=r.json()
    transition(s,b);before=digest(s.admin)
    assert send().status_code==200
    get=append_recover(s,b,h) if action=='append' else recovery(s,b,h)
    assert get.status_code==200 and get.json()==original
    cross=(recovery(s,b,h),post(s,b,command(b),h)) if action=='append' else (append_recover(s,b,h),append_post(s,b,append_body(b),h))
    for r in cross:assert r.status_code==409 and r.json()['error']['code']=='conversation_contract_mismatch'
    assert digest(s.admin)==before and s.provider.calls==0


def test_completed_mining_receipt_after_typed_does_not_infer_again(preflight):
    s=preflight;b=seed(s);h,_=headers('mining_run',f'session:{b.sid}',b.token)
    body=dict(project_id=str(b.pid),base_revision=b.revision,content='我编写了合成测试。')
    url=ROOT+f'/sessions/{b.sid}/mining-runs'
    r=s.client.post(url,headers=h,json=body);assert r.status_code==201 and r.json()['state']=='completed'
    original=r.json();assert s.provider.calls==1
    transition(s,b);before=digest(s.admin)
    for r in (s.client.get(url+'/recovery',headers=h),s.client.post(url,headers=h,json=body)):
        assert r.status_code==200 and r.json()==original
    r=s.client.post(url,headers=h,json={**body,'content':'不同输入'})
    assert r.status_code==409 and r.json()['error']['code']=='idempotency_payload_mismatch'
    assert digest(s.admin)==before and s.provider.calls==1


@pytest.mark.parametrize('history_only',[False,True])
def test_whole_session_delete_is_authenticated_privileged_existing_exception(preflight,history_only):
    s=preflight;b,h,_=legacy_created(s);foreign=seed(s)
    with s.admin() as db:b.revision=db.get(ExperienceSession,b.sid).context_revision
    co_h=key(b);created=append_post(s,b,append_body(b),co_h);assert created.status_code==201
    transition(s,b,history_only)
    url=ROOT+f'/sessions/{b.sid}';before=digest(s.admin)
    assert s.client.delete(url,headers=auth(foreign)).status_code==404
    assert digest(s.admin)==before
    with s.admin.begin() as db:db.execute(text(f'REVOKE DELETE ON experience_sessions FROM "{s.legacy_role}"'))
    assert s.client.delete(url,headers=auth(b)).status_code==503
    assert digest(s.admin)==before
    with s.admin.begin() as db:db.execute(text(f'GRANT DELETE ON experience_sessions TO "{s.legacy_role}"'))
    assert s.client.delete(url,headers=auth(b)).status_code==204
    with s.admin() as db:
        assert db.get(ExperienceSession,b.sid) is None
        assert db.get(ExperienceSession,foreign.sid) is not None
        for table in ('experience_facts','fact_changes','fact_sources','fact_change_sources','conversation_turns'):
            assert db.scalar(text(f'SELECT count(*) FROM {table} WHERE session_id=:id'),{'id':b.sid})==0
        row=db.execute(text("SELECT state,input_turn_id,request_tag FROM conversation_operations WHERE id=:id"),{'id':UUID(created.json()['operation_id'])}).one()
        assert tuple(row)==('deleted',None,None)
    r=s.client.get(ROOT+'/session-creations/recovery',headers=h)
    assert r.status_code==410 and r.json()['error']['code']=='idempotency_resource_deleted'
    r=append_recover(s,b,co_h)
    assert r.status_code==410 and r.json()['error']['code']=='conversation_resource_deleted'


def reserved(s,b):
    h,_=headers('mining_run',f'session:{b.sid}',b.token)
    k=idem.parse(h['Idempotency-Key'],b.token,'mining_run',f'session:{b.sid}')
    rid,fresh=mining.reserve(s.legacy,b.sid,b.token,k,Start(project_id=b.pid,base_revision=b.revision,content='我编写了新的合成脚本。'))
    assert fresh
    return rid


@pytest.mark.parametrize('mode',['claim_stale','complete_stale','expired','fail','unknown','context','complete_candidate','complete_empty'])
def test_worker_finalization_has_distinct_existing_effects(preflight,mode):
    s=preflight;b=seed(s);rid=reserved(s,b)
    if mode.startswith('complete') or mode=='expired':assert mining.claim(s.legacy,b.sid,b.token,rid) is not None
    transition(s,b)
    # For the matching-revision branch, trusted owner arranges a synthetic
    # in-flight state. This is fault evidence, not a reachable typed writer.
    if mode in ('context','complete_candidate','complete_empty','expired'):
        with s.admin.begin() as db:
            run=db.get(MiningRun,rid);run.reserved_revision=db.get(ExperienceSession,b.sid).context_revision
            if mode=='expired':run.lease_until=utcnow()-timedelta(seconds=1)
    before=digest(s.admin)
    with s.admin() as db:
        # Compare every other table, including all fee/audit/receipt tables,
        # while permitting only this contract's four finalization surfaces.
        names=db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename NOT IN ('experience_sessions','conversation_turns','ai_mining_runs','ai_mining_questions') ORDER BY tablename")).all()
        prior={t:db.scalars(text(f'SELECT to_jsonb(t)::text FROM {t} t ORDER BY to_jsonb(t)::text')).all() for t in names}
        turn=db.get(MiningRun,rid).input_turn_id
        content=db.scalar(text('SELECT content FROM conversation_turns WHERE id=:id'),{'id':turn})
    empty=MiningOutput(candidates=[],questions=['合成收尾问题'])
    if mode=='context':
        with pytest.raises(ConversationError,match='fact_contract_upgrade_required'),s.legacy.begin() as db:
            build_context(db,db.get(MiningRun,rid),db.get(ExperienceSession,b.sid))
        with pytest.raises(ConversationError,match='fact_contract_upgrade_required'):mining.claim(s.legacy,b.sid,b.token,rid)
        assert digest(s.admin)==before
    elif mode=='complete_candidate':
        output=MiningOutput(candidates=[Candidate(citation=Citation(turn_id=turn,start=0,end=len(content),quote=content))],questions=[])
        with pytest.raises(ConversationError,match='fact_contract_upgrade_required'):mining.complete(s.legacy,b.sid,b.token,rid,output)
        assert digest(s.admin)==before
    else:
        if mode=='claim_stale':assert mining.claim(s.legacy,b.sid,b.token,rid) is None
        elif mode in ('fail','unknown'):mining.fail(s.legacy,b.sid,b.token,rid,'failed' if mode=='fail' else mode,'synthetic_finalization')
        else:mining.complete(s.legacy,b.sid,b.token,rid,empty)
        assert digest(s.admin)!=before  # truthful legal status/assistant/question effects
        with s.admin() as db:
            expected={'claim_stale':'stale','complete_stale':'stale','expired':'unknown','fail':'fail','unknown':'unknown','complete_empty':'completed'}[mode]
            if mode=='fail':expected='failed'
            assert db.get(MiningRun,rid).state==expected
            if mode=='complete_empty':
                assert db.get(MiningRun,rid).assistant_turn_id is not None
                assert db.scalar(select(MiningQuestion.id).where(MiningQuestion.run_id==rid)) is not None
    with s.admin() as db:
        assert {t:db.scalars(text(f'SELECT to_jsonb(t)::text FROM {t} t ORDER BY to_jsonb(t)::text')).all() for t in names}==prior
    assert s.provider.calls==0


@pytest.mark.parametrize('entry',['manual','mining','append'])
def test_R03_reworded_reassertion_is_observed_risk_not_a_closed_guarantee(preflight,entry):
    s=preflight;b=seed(s,status='rejected');new='我测试了三个导出按钮。'
    if entry=='manual':
        r=s.client.post(ROOT+f'/sessions/{b.sid}/turns',headers=auth(b),json={'content':new});assert r.status_code==201
        r=s.client.post(ROOT+f'/projects/{b.pid}/facts',headers=auth(b),json={'statement':new,'source_turn_ids':[r.json()['id']]})
        assert r.status_code==201
    elif entry=='mining':
        h,_=headers('mining_run',f'session:{b.sid}',b.token)
        r=s.client.post(ROOT+f'/sessions/{b.sid}/mining-runs',headers=h,json={'project_id':str(b.pid),'base_revision':b.revision,'content':new})
        assert r.status_code==201 and r.json()['state']=='completed' and s.provider.calls==1
    else:
        before=digest(s.admin);r=append_post(s,b,append_body(b,[new]))
        assert r.status_code==409 and r.json()['error']['code']=='append_requires_clarification'
        assert digest(s.admin)==before
    with s.admin() as db:
        old=db.get(ExperienceFact,b.fid);assert old.status=='rejected'
        added=db.scalar(select(ExperienceFact).where(ExperienceFact.session_id==b.sid,ExperienceFact.statement==new))
        assert (added is None)==(entry=='append')
        if added is not None:assert added.classification_contract=='legacy-v0' and added.status=='pending'
