"""B2-b HTTP uses a real restricted LOGIN, never migration-owner connections.

All fixtures are synthetic in a random schema. Admin is used only to provision
test roles/schema and arrange prior legacy state; command/recovery uses runtime.
"""
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import facts, mining
from app.experience_api import get_db, session_view
from app.fact_maintenance_models import ConversationOperation, FactChangeSource
from app.main import app
from app.maintenance_api import get_maintenance_factory
from app.maintenance_contract import Command
from app.models import ConversationTurn, ExperienceFact, ExperienceSession, FactChange, FactEvidence, MiningRun, utcnow
from test_deepseek_mining_integration import offline_guard, test_database_only
from test_fact_source_maintenance import stored
from test_http_api import api
from test_idempotency import headers

ROOT = '/api/v1/experience'
KIND = 'conversation_maintenance_v1'
READS = ('experience_sessions','experience_projects','conversation_turns','experience_facts',
         'fact_changes','fact_sources','fact_evidence','ai_mining_runs',
         'conversation_operations','fact_change_sources')


@pytest.fixture
def service(api):
    client, admin = api
    with admin() as db:
        schema = db.scalar(text('SELECT current_schema()'))
        admin_role = db.scalar(text('SELECT current_user'))
    role, auditor = 'b2b_run_'+uuid4().hex, 'b2b_owner_'+uuid4().hex
    password = secrets.token_urlsafe(32)  # disposable DB role, not a native credential
    engine = None
    functions = []
    try:
        with admin.begin() as db:
            quote = db.bind.dialect.identifier_preparer.quote_identifier
            q, r, a = map(quote, (schema, role, auditor))
            assert schema.startswith('test_')
            # Generated test password has no SQL quote characters; never output.
            db.execute(text(f"CREATE ROLE {r} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"))
            db.execute(text(f'CREATE ROLE {a} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT'))
            db.execute(text(f'GRANT USAGE ON SCHEMA {q} TO {r},{a}'))
            for table in READS:
                db.execute(text(f'GRANT SELECT ON {q}.{table} TO {r},{a}'))
            for table in ('conversation_turns','fact_changes','conversation_operations','fact_change_sources'):
                db.execute(text(f'GRANT INSERT ON {q}.{table} TO {r}'))
            db.execute(text(f'GRANT UPDATE(updated_at,context_revision) ON {q}.experience_sessions TO {r},{a}'))
            db.execute(text(f'GRANT UPDATE(statement,status,evidence_id,updated_at,version) ON {q}.experience_facts TO {r}'))
            db.execute(text(f'GRANT UPDATE(id) ON {q}.conversation_operations TO {r}'))
            db.execute(text(f'GRANT UPDATE ON {q}.conversation_operations TO {a}'))
            functions = db.scalars(text("SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'maintenance_%'")).all()
            for function in functions:
                db.execute(text(f'ALTER FUNCTION {function} OWNER TO {a}'))
        url = admin.kw['bind'].url.set(username=role, password=password)
        engine = create_engine(url, poolclass=NullPool, hide_parameters=True,
                               connect_args={'options': f'-csearch_path={schema}'})
        runtime = sessionmaker(engine, expire_on_commit=False)
        app.dependency_overrides[get_maintenance_factory] = lambda: runtime
        yield SimpleNamespace(client=client, admin=admin, runtime=runtime, role=role,
                              auditor=auditor, schema=schema)
    finally:
        app.dependency_overrides.pop(get_maintenance_factory, None)
        if engine:
            engine.dispose()
        with admin.begin() as db:
            for function in functions:
                db.execute(text(f'ALTER FUNCTION {function} OWNER TO {quote(admin_role)}'))
            for name in (role, auditor):
                # Only these random roles were created by this fixture. They own
                # no objects after function restoration; RESTRICT, never CASCADE.
                exists = db.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:r)'), {'r': name})
                if exists:
                    db.execute(text(f'DROP OWNED BY {quote(name)} RESTRICT'))
                    db.execute(text(f'DROP ROLE {quote(name)}'))
        password = None


def seed(s, *, status='pending', statement='我测试了3个导出按钮。'):
    with s.admin.begin() as db:
        project, turn, token = facts.create_experience(db, statement)
        fact = facts.add_fact(db, project.id, token, statement, [turn.id])
        if status != 'pending':
            facts.change_fact(db, fact.id, token, status='user_confirmed', expected_version=1)
        if status == 'evidence_supported':
            facts.change_fact(db, fact.id, token, status=status, expected_version=2,
                              material_reference='synthetic:test-report', basis='合成材料测试')
        if status == 'rejected':
            facts.change_fact(db, fact.id, token, status=status, expected_version=2)
        db.refresh(db.get(ExperienceSession, project.session_id))
        return SimpleNamespace(sid=project.session_id,pid=project.id,fid=fact.id,tid=turn.id,
            token=token,version=fact.version,revision=db.get(ExperienceSession,project.session_id).context_revision)


def command(b, *, action='correct', replacement='我测试了2个导出按钮。', intent=None, **overrides):
    intent = intent or ('纠正上一条。' if action != 'withdraw' else '撤回上一条。')
    content = intent + (replacement if action != 'withdraw' else '')
    body = dict(contract_version=1,base_revision=b.revision,action=action,
        input={'content':content}, target={'fact_id':str(b.fid),'expected_version':b.version},
        intent_span={'start':0,'end':len(intent),'quote':intent},
        statements=[{'start':len(intent),'end':len(content),'quote':replacement}] if action != 'withdraw' else [])
    body.update(overrides)
    return body


def key(b):
    return headers(KIND, f'session:{b.sid}', b.token)[0]


def post(s,b,body=None,h=None):
    return s.client.post(f'{ROOT}/sessions/{b.sid}/conversation-operations',
        headers=h or key(b),json=body or command(b))


def recovery(s,b,h):
    return s.client.get(f'{ROOT}/sessions/{b.sid}/conversation-operations/recovery',headers=h)


@pytest.mark.parametrize('status',['pending','user_confirmed','evidence_supported'])
@pytest.mark.parametrize('action',['correct','withdraw'])
def test_atomic_effect_sources_trust_and_old_material(service,status,action):
    s=service;b=seed(s,status=status);h=key(b);body=command(b,action=action)
    response=post(s,b,body,h)
    assert response.status_code==201,response.text
    result=response.json();assert result['provider_calls']==0 and result['mining_run_id'] is None
    assert result['effects'][0]['after_version']==b.version+1
    expected='pending' if action=='correct' else 'rejected'
    assert result['effects'][0]['applied_status']==expected
    with s.admin() as db:
        fact=db.get(ExperienceFact,b.fid)
        assert fact.status==expected and fact.evidence_id is None and fact.version==b.version+1
        change=db.get(FactChange,UUID(result['effects'][0]['change_id']))
        assert change.before['status']==status
        if status=='evidence_supported':
            assert change.before['evidence_id'] is not None and db.scalar(text('SELECT count(*) FROM fact_evidence'))==1
        assert change.after['evidence_id'] is None
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==2
        assert db.scalar(text('SELECT count(*) FROM ai_mining_runs'))==0
        assert db.scalar(text('SELECT count(*) FROM fact_change_sources'))==(2 if action=='correct' else 1)
        assert db.scalar(text('SELECT count(*) FROM paid_calls'))==0
    before=stored(s.admin)
    assert recovery(s,b,h).json()==result
    replay=post(s,b,body,h)
    assert replay.status_code==200 and replay.headers['Idempotency-Replayed']=='true' and replay.json()==result
    assert stored(s.admin)==before


def test_disabled_by_default_even_with_environment(api,monkeypatch):
    client,_=api
    monkeypatch.setenv('CONVERSATION_MAINTENANCE_ENABLED','true')
    response=client.get(f'{ROOT}/sessions/{uuid4()}/conversation-operations/{uuid4()}',
                        headers={'Authorization':'Bearer '+'x'*43})
    assert response.status_code==503 and response.json()['error']['code']=='conversation_maintenance_disabled'


def current(s,b):
    with s.admin() as db:
        b.revision=db.get(ExperienceSession,b.sid).context_revision
        b.version=db.get(ExperienceFact,b.fid).version
    return b


def error(response,status,code):
    assert response.status_code==status,response.text
    assert response.json()['error']['code']==code,response.text


def test_recovery_is_database_enforced_readonly_one_connection_no_mutation(service):
    s=service;b=seed(s);h=key(b);result=post(s,b,h=h).json()
    sql=[]; connections=set()
    def capture(conn,cursor,statement,parameters,context,many):
        sql.append(statement);connections.add(id(conn))
    event.listen(s.runtime.kw['bind'],'before_cursor_execute',capture)
    before=stored(s.admin)
    try:
        response=recovery(s,b,h)
        assert response.status_code==200 and response.json()==result
        assert len(connections)==1
        assert any('SHOW transaction_read_only' in q for q in sql)
        assert any('SHOW transaction_isolation' in q for q in sql)
        assert all(q.lstrip().split()[0].upper() in ('SELECT','SHOW') for q in sql)
        assert not any('pg_advisory' in q or 'FOR UPDATE' in q for q in sql)
    finally:event.remove(s.runtime.kw['bind'],'before_cursor_execute',capture)
    assert stored(s.admin)==before


@pytest.mark.parametrize('field',['content','action','target','span','base_revision','extra'])
def test_same_key_changed_request_is_conflict_before_new_versions(service,field):
    s=service;b=seed(s);h=key(b);body=command(b);assert post(s,b,body,h).status_code==201
    import copy
    changed=copy.deepcopy(body)
    if field=='content':changed['input']['content']+='x'
    elif field=='action':
        changed['action']='withdraw';changed['statements']=[]
    elif field=='target':changed['target']['fact_id']=str(uuid4())
    elif field=='span':changed['intent_span']['end']-=1
    elif field=='extra':changed['replacement_text']='untrusted'
    else:changed['base_revision']+=1
    before=stored(s.admin)
    error(post(s,b,changed,h),422 if field=='extra' else 409,
          'invalid_request' if field=='extra' else 'idempotency_payload_mismatch')
    assert stored(s.admin)==before


@pytest.mark.parametrize('fault',['version','context','both','foreign','missing','rejected'])
def test_ownership_version_context_priority_and_zero_writes(service,fault):
    s=service;b=seed(s,status='rejected' if fault=='rejected' else 'pending');body=command(b)
    if fault in ('version','both'):body['target']['expected_version']+=10
    if fault in ('context','both'):body['base_revision']+=10
    if fault=='foreign':body['target']['fact_id']=str(seed(s).fid)
    if fault=='missing':body['target']['fact_id']=str(uuid4())
    before=stored(s.admin)
    response=post(s,b,body)
    if fault in ('foreign','missing'):error(response,404,'resource_unavailable')
    else:error(response,409,{'both':'version_conflict','version':'version_conflict','context':'context_conflict','rejected':'fact_rejected_immutable'}[fault])
    assert stored(s.admin)==before


@pytest.mark.parametrize('bad',['quote','utf16','offset','hidden_negation','team','paraphrase','different_duty',
                               'composite','hypothetical_intent','extra_statement','wrong_contract','boolean_version'])
def test_source_identity_and_controlled_grammar_fail_closed(service,bad):
    s=service;b=seed(s);body=command(b)
    expected='conversation_source_invalid'
    if bad=='quote':body['statements'][0]['quote']='我测试了5个导出按钮。'
    elif bad in ('utf16','offset'):body['statements'][0]['end']+=1
    elif bad=='hidden_negation':body['input']['content']='我没有做过。'+body['input']['content']
    elif bad=='team':body=command(b,replacement='我们测试了2个导出按钮。')
    elif bad=='paraphrase':body=command(b,replacement='我测试了2个按钮。');expected='correction_identity_unresolved'
    elif bad=='different_duty':body=command(b,replacement='我实现了本地筛选。');expected='correction_identity_unresolved'
    elif bad=='composite':
        body=command(b,intent='撤回旧职责并补充新职责。');expected='composite_operation_not_supported'
    elif bad=='hypothetical_intent':body=command(b,intent='如果纠正上一条。');expected='correction_intent_invalid'
    elif bad=='extra_statement':body['statements'].append(body['statements'][0]);expected='invalid_request'
    elif bad=='wrong_contract':body['contract_version']=2;expected='invalid_request'
    else:body['target']['expected_version']=True;expected='invalid_request'
    before=stored(s.admin)
    error(post(s,b,body),422,expected)
    assert stored(s.admin)==before


def ambiguous(s,b):
    with s.admin.begin() as db:
        extra=facts.add_turn(db,b.sid,b.token,'我测试了4个导出按钮。')
        facts.add_fact(db,b.pid,b.token,extra.content,[extra.id])
    current(s,b)
    body=command(b,action='disambiguate',target=None,proposed_action='correct')
    h=key(b);response=post(s,b,body,h)
    assert response.status_code==201,response.text
    assert response.json()['state']=='needs_clarification' and response.json()['effects']==[]
    return UUID(response.json()['operation_id']),h,body


def resolution_body(s,b):
    current(s,b)
    return dict(contract_version=1,base_revision=b.revision,selected_fact_id=str(b.fid),expected_version=b.version)


def resolve(s,b,parent,body=None,h=None):
    return s.client.post(f'{ROOT}/sessions/{b.sid}/conversation-operations/{parent}/resolution',
        headers=h or key(b),json=body or resolution_body(s,b))


def test_resolution_reuses_frozen_turn_parent_is_immutable_and_replay_safe(service):
    s=service;b=seed(s);parent,h,original=ambiguous(s,b)
    with s.admin() as db:
        parent_before=db.get(ConversationOperation,parent)
        snapshot={c.name:getattr(parent_before,c.name) for c in ConversationOperation.__table__.columns}
        turns=db.scalar(text('SELECT count(*) FROM conversation_turns'))
    rh=key(b);body=resolution_body(s,b);response=resolve(s,b,parent,body,rh)
    assert response.status_code==201,response.text
    result=response.json();assert result['input_turn_id']==str(snapshot['input_turn_id'])
    with s.admin() as db:
        row=db.get(ConversationOperation,parent)
        assert {c.name:getattr(row,c.name) for c in ConversationOperation.__table__.columns}==snapshot
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==turns
    assert recovery(s,b,h).json()['resolved_by']==result['operation_id']
    before=stored(s.admin)
    assert resolve(s,b,parent,body,rh).status_code==200
    error(resolve(s,b,parent,body,key(b)),409,'conversation_resolution_already_applied')
    assert stored(s.admin)==before


def test_resolution_cannot_replace_identity_or_freeze_new_text(service):
    s=service;b=seed(s);parent,_,_=ambiguous(s,b)
    with s.admin.begin() as db:
        t=facts.add_turn(db,b.sid,b.token,'我实现了本地筛选。')
        other=facts.add_fact(db,b.pid,b.token,t.content,[t.id]);fid=other.id
    body=resolution_body(s,b);body['selected_fact_id']=str(fid);body['expected_version']=1
    before=stored(s.admin)
    error(resolve(s,b,parent,body),422,'correction_identity_unresolved')
    body['input']={'content':'do not replace frozen text'}
    error(resolve(s,b,parent,body),422,'invalid_request')
    assert stored(s.admin)==before


@pytest.mark.parametrize('state',['reserved','running','unknown','stopped','ended','six_rounds'])
def test_business_gates_do_not_create_provider_or_run(service,state):
    s=service;b=seed(s)
    with s.admin.begin() as db:
        session=db.get(ExperienceSession,b.sid)
        if state=='stopped':session.mining_status='stopped'
        elif state=='ended':session.status='ended'
        else:
            for i in range(6 if state=='six_rounds' else 1):
                turn=facts.add_turn(db,b.sid,b.token,f'合成已保存回合{i}。')
                db.refresh(session)
                db.add(MiningRun(session_id=b.sid,project_id=b.pid,input_turn_id=turn.id,
                    base_revision=1,reserved_revision=session.context_revision,
                    state='completed' if state=='six_rounds' else state,lease_until=utcnow()+timedelta(minutes=1)))
    current(s,b);before=stored(s.admin)
    with s.admin() as db:run_count=db.scalar(text('SELECT count(*) FROM ai_mining_runs'))
    response=post(s,b)
    if state in ('stopped','six_rounds'):
        assert response.status_code==201,response.text
    else:
        error(response,409,'session_ended' if state=='ended' else 'mining_result_unresolved')
        assert stored(s.admin)==before
    with s.admin() as db:
        assert db.scalar(text('SELECT count(*) FROM ai_mining_runs'))==run_count
        assert db.get(ExperienceSession,b.sid).mining_status==('stopped' if state=='stopped' else 'not_started')


def test_confirmed_current_sources_export_summary_and_legacy_reject_semantics(service):
    s=service;b=seed(s,status='evidence_supported');result=post(s,b).json()
    with s.admin.begin() as db:
        fact=db.get(ExperienceFact,b.fid)
        facts.change_fact(db,b.fid,b.token,status='user_confirmed',expected_version=fact.version)
    h={'Authorization':'Bearer '+b.token}
    data=s.client.get(f'{ROOT}/sessions/{b.sid}/export',headers=h).json()['data']
    fact=data['facts'][0]
    assert fact['statement']=='我测试了2个导出按钮。' and fact['edit_method']=='conversation_correction'
    assert fact['current_citations'][0]['turn_id']==result['input_turn_id']
    assert fact['current_citations'][0]['quote']==fact['statement']
    assert fact['original_source_turn_ids']==[str(b.tid)] and fact['citations']==[]
    with s.admin.begin() as db:
        facts.change_fact(db,b.fid,b.token,status='evidence_supported',expected_version=fact['version'],
                          material_reference='synthetic:second',basis='合成新材料')
    current(s,b)
    assert post(s,b,command(b,action='withdraw')).status_code==201
    data=s.client.get(f'{ROOT}/sessions/{b.sid}/export',headers=h).json()['data']
    fact=data['facts'][0]
    assert fact['current_citations']==[] and len(fact['withdrawal_basis'])==1
    assert fact['withdrawal_basis'][0]['quote']=='撤回上一条。'
    assert fact['status']=='rejected' and len(data['evidence'])==2
    # Existing summary contract never includes this rejected current version.
    from app.mining_api import get_mining_factory
    app.dependency_overrides[get_mining_factory]=lambda:s.admin
    summary=s.client.get(f'{ROOT}/projects/{b.pid}/experience-summary',headers=h)
    assert summary.status_code==200 and summary.json()['confirmed']==[] and summary.json()['text']==''


def test_two_connections_correction_competition_only_one_effect(service):
    s=service;b=seed(s);body=command(b);barrier=Barrier(2)
    def submit():
        h=key(b);barrier.wait(5)
        return post(s,b,body,h)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:submit(),range(2)))
    assert sorted(r.status_code for r in results)==[201,409],[r.text for r in results]
    with s.admin() as db:
        assert db.get(ExperienceFact,b.fid).version==2
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==2
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==1
        assert db.scalar(text('SELECT count(*) FROM fact_change_sources'))==2


def test_concurrent_resolution_one_child_one_effect(service):
    s=service;b=seed(s);parent,_,_=ambiguous(s,b);body=resolution_body(s,b);barrier=Barrier(2)
    def submit():
        h=key(b);barrier.wait(5)
        return resolve(s,b,parent,body,h)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:submit(),range(2)))
    assert sorted(r.status_code for r in results)==[201,409],[r.text for r in results]
    denied=next(r for r in results if r.status_code==409)
    assert denied.json()['error']['code']=='conversation_resolution_already_applied'
    with s.admin() as db:
        assert db.get(ExperienceFact,b.fid).version==2
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==2


@pytest.mark.parametrize('direction',['new_then_turn','new_then_mining_content','new_then_mining_turn',
                                      'new_then_fact','turn_then_new','mining_then_new'])
def test_old_and_new_entries_cannot_consume_same_submission(service,direction):
    s=service;b=seed(s);body=command(b);content=body['input']['content']
    if direction in ('turn_then_new','mining_then_new'):
        with s.admin.begin() as db:
            turn=facts.add_turn(db,b.sid,b.token,content)
            if direction=='mining_then_new':
                db.refresh(db.get(ExperienceSession,b.sid))
                db.add(MiningRun(session_id=b.sid,project_id=b.pid,input_turn_id=turn.id,
                    base_revision=1,reserved_revision=db.get(ExperienceSession,b.sid).context_revision,
                    state='completed',lease_until=utcnow()+timedelta(minutes=1)))
        current(s,b);body['base_revision']=b.revision
        before=stored(s.admin)
        error(post(s,b,body),409,'conversation_input_already_submitted')
    else:
        result=post(s,b,body).json();before=stored(s.admin)
        h={'Authorization':'Bearer '+b.token}
        if direction=='new_then_turn':
            response=s.client.post(f'{ROOT}/sessions/{b.sid}/turns',headers=h,json={'content':content})
        elif direction=='new_then_fact':
            response=s.client.post(f'{ROOT}/projects/{b.pid}/facts',headers=h,
                json={'statement':'我测试了2个导出按钮。','source_turn_ids':[result['input_turn_id']]})
        else:
            from app.mining_api import get_mining_factory,get_provider
            from app.mining_provider import ScriptedProvider
            app.dependency_overrides[get_mining_factory]=lambda:s.admin
            class Never( ScriptedProvider):
                async def mine(self,*args,**kwargs):raise AssertionError('Provider must not run')
            app.dependency_overrides[get_provider]=lambda:Never()
            current(s,b)
            mh=headers('mining_run',f'session:{b.sid}',b.token)[0]
            data={'project_id':str(b.pid),'base_revision':b.revision}
            data.update({'content':content} if direction.endswith('content') else {'input_turn_id':result['input_turn_id']})
            response=s.client.post(f'{ROOT}/sessions/{b.sid}/mining-runs',headers=mh,json=data)
        error(response,409,'conversation_input_already_submitted')
    assert stored(s.admin)==before


@pytest.mark.parametrize('origin',['current','historical','origin_turn','new_correction','legacy_edit'])
def test_rejected_contribution_cannot_revive_with_different_key_or_source(service,origin):
    s=service;b=seed(s)
    with s.admin.begin() as db:
        facts.change_fact(db,b.fid,b.token,statement='我测试了2个导出按钮。',expected_version=1)
        facts.change_fact(db,b.fid,b.token,status='rejected',expected_version=2)
        turn=facts.add_turn(db,b.sid,b.token,'我测试了2个导出按钮。')
        # A different legitimate fact is eligible for correction, but may not
        # take on a rejected current/history statement through the new route.
        live=facts.add_fact(db,b.pid,b.token,'我测试了4个导出按钮。',[turn.id]);other_id=live.id
    before=stored(s.admin)
    h={'Authorization':'Bearer '+b.token}
    if origin in ('new_correction','legacy_edit'):
        b.fid=other_id;current(s,b)
        if origin=='new_correction':response=post(s,b,command(b,replacement='我测试了3个导出按钮。'))
        else:response=s.client.patch(f'{ROOT}/facts/{b.fid}',headers=h,
            json={'action':'edit','expected_version':b.version,'statement':'我测试了3个导出按钮。'})
    else:
        statement='我测试了3个导出按钮。' if origin=='historical' else '我测试了2个导出按钮。'
        response=s.client.post(f'{ROOT}/projects/{b.pid}/facts',headers=h,
            json={'statement':statement if origin!='origin_turn' else '不同文字也不能重用撤回来源',
                  'source_turn_ids':[str(b.tid if origin=='origin_turn' else turn.id)]})
    error(response,409,'fact_rejected_immutable')
    assert stored(s.admin)==before


def test_legacy_successful_receipt_still_replays_after_new_operation(service):
    s=service;b=seed(s)
    old_headers=headers('add_turn',f'session:{b.sid}',b.token)[0]
    url=f'{ROOT}/sessions/{b.sid}/turns';old={'content':'合成自由补充，已经保存。'}
    original=s.client.post(url,headers=old_headers,json=old)
    assert original.status_code==201
    current(s,b);assert post(s,b).status_code==201
    before=stored(s.admin)
    replay=s.client.post(url,headers=old_headers,json=old)
    assert replay.status_code==201 and replay.headers['Idempotency-Replayed']=='true'
    from datetime import datetime
    old_result,new_result=original.json(),replay.json()
    assert datetime.fromisoformat(old_result.pop('created_at'))==datetime.fromisoformat(new_result.pop('created_at'))
    assert new_result==old_result and stored(s.admin)==before


@pytest.mark.parametrize('attack',['wrong_bearer','wrong_scope','missing_key','expired_key','foreign_id'])
def test_recovery_authentication_and_expiry_are_readonly(service,attack,monkeypatch):
    s=service;b=seed(s);h=key(b);result=post(s,b,h=h).json();before=stored(s.admin)
    if attack=='wrong_bearer':
        h['Authorization']='Bearer '+headers()[1]
        response=recovery(s,b,h);error(response,401,'idempotency_credential_invalid')
    elif attack=='wrong_scope':
        h=headers(KIND,f'session:{uuid4()}',b.token)[0]
        error(recovery(s,b,h),401,'idempotency_credential_invalid')
    elif attack=='missing_key':
        h.pop('Idempotency-Key');error(recovery(s,b,h),422,'idempotency_key_invalid')
    elif attack=='expired_key':
        from app import idempotency
        monkeypatch.setattr(idempotency,'utcnow',lambda:utcnow()+timedelta(hours=25))
        error(recovery(s,b,h),410,'idempotency_key_expired')
    else:
        other=seed(s);before=stored(s.admin)
        response=s.client.get(f'{ROOT}/sessions/{other.sid}/conversation-operations/{result["operation_id"]}',
                              headers={'Authorization':'Bearer '+other.token})
        error(response,404,'resource_unavailable')
    assert stored(s.admin)==before


@pytest.mark.parametrize('stage',['turn','fact','source','commit'])
def test_injected_storage_failure_rolls_back_turn_fact_sources_receipt(service,stage,monkeypatch,caplog):
    from sqlalchemy.exc import IntegrityError
    s=service;b=seed(s);before=stored(s.admin)
    canary='UNTRUSTED_RESPONSE_AND_SECRET_CANARY'
    def fail(*args,**kwargs):raise IntegrityError('synthetic',{},Exception(canary))
    listener=None
    if stage in ('turn','fact'):
        method='add_turn' if stage=='turn' else 'change_fact';original=getattr(facts,method)
        def injected(*args,**kwargs):original(*args,**kwargs);fail()
        monkeypatch.setattr(facts,method,injected)
    elif stage=='source':
        def corrupt(db,context,instances):
            for row in db.new:
                if isinstance(row,FactChangeSource):row.quote=canary
        event.listen(s.runtime,'before_flush',corrupt);listener=('before_flush',corrupt)
    else:
        event.listen(s.runtime,'before_commit',fail);listener=('before_commit',fail)
    try:error(post(s,b),500,'conversation_integrity_failed')
    finally:
        if listener:event.remove(s.runtime,*listener)
    assert stored(s.admin)==before and canary not in caplog.text


@pytest.mark.parametrize('first',['correction','delete','end'])
def test_correction_and_delete_end_linearization(service,first):
    s=service;b=seed(s);h=key(b);body=command(b)
    if first=='correction':
        result=post(s,b,body,h);assert result.status_code==201
        response=s.client.delete(f'{ROOT}/sessions/{b.sid}',headers={'Authorization':'Bearer '+b.token})
        assert response.status_code==204
    else:
        ready=Event();release=Event()
        def control():
            with s.admin.begin() as db:
                session=facts.authorize(db,b.sid,b.token,lock=True)
                if first=='end':facts.end_session(db,b.sid,b.token)
                else:db.delete(session);db.flush()
                ready.set();assert release.wait(5)
        with ThreadPoolExecutor(2) as pool:
            future=pool.submit(control);assert ready.wait(5)
            attempt=pool.submit(post,s,b,body,h)
            # Observe a real blocked Session row lock, not merely a timer.
            try:
                # Transaction-ID locks have pg_locks.database=NULL. Scope by
                # actual activity DB/login instead of filtering that NULL column.
                deadline=time.monotonic()+3
                observed=False
                while time.monotonic()<deadline:
                    with s.admin() as db:
                        observed=db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND usename=:r AND wait_event_type='Lock' AND wait_event='transactionid')"),{'r':s.role})
                    if observed:break
                    time.sleep(.02)
                assert observed,'Expected isolated runtime Session lock wait'
            finally:release.set()
            future.result(10);response=attempt.result(10)
        error(response,409 if first=='end' else 404,'session_ended' if first=='end' else 'resource_unavailable')
    with s.admin() as db:
        assert db.scalar(text('SELECT count(*) FROM fact_change_sources'))==0
        if first=='correction':
            assert db.scalar(text("SELECT count(*) FROM conversation_operations WHERE state='deleted'"))==1
            assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==0
    if first=='correction':error(recovery(s,b,h),410,'conversation_resource_deleted')


def test_runtime_cannot_modify_audit_money_create_or_set_role(service):
    s=service;b=seed(s);assert post(s,b).status_code==201
    attacks=[
        'UPDATE conversation_operations SET id=id',
        'DELETE FROM conversation_operations',
        "UPDATE fact_change_sources SET quote='fake'",
        'DELETE FROM fact_change_sources',
        'UPDATE paid_funding SET ceiling=1',
        'DELETE FROM paid_calls',
        'CREATE TABLE forbidden(a int)',
        f'SET ROLE "{s.auditor}"',
        "UPDATE conversation_turns SET role='assistant'",
        "UPDATE experience_facts SET origin='ai_extracted'",
    ]
    before=stored(s.admin)
    for sql in attacks:
        with pytest.raises(DBAPIError),s.runtime.begin() as db:db.execute(text(sql))
    assert stored(s.admin)==before


@pytest.mark.parametrize('unsafe',['superuser','membership','ddl','funds','source_update','login_owner','owner_superuser','owner_money','public_execute','fact_extra_column'])
def test_runtime_admission_rejects_high_privileges_or_bad_definer(service,unsafe):
    s=service;b=seed(s);before=stored(s.admin)
    with s.admin.begin() as db:
        q=f'"{s.schema}"';r=f'"{s.role}"';a=f'"{s.auditor}"'
        if unsafe=='superuser':db.execute(text(f'ALTER ROLE {r} SUPERUSER'))
        elif unsafe=='membership':db.execute(text(f'GRANT {a} TO {r}'))
        elif unsafe=='ddl':db.execute(text(f'GRANT CREATE ON SCHEMA {q} TO {r}'))
        elif unsafe=='funds':db.execute(text(f'GRANT UPDATE ON {q}.paid_funding TO {r}'))
        elif unsafe=='source_update':db.execute(text(f'GRANT UPDATE ON {q}.fact_change_sources TO {r}'))
        elif unsafe=='login_owner':db.execute(text(f'ALTER ROLE {a} LOGIN'))
        elif unsafe=='owner_superuser':db.execute(text(f'ALTER ROLE {a} SUPERUSER'))
        elif unsafe=='owner_money':db.execute(text(f'GRANT UPDATE ON {q}.paid_funding TO {a}'))
        elif unsafe=='fact_extra_column':db.execute(text(f'GRANT UPDATE(origin) ON {q}.experience_facts TO {r}'))
        else:db.execute(text(f'GRANT EXECUTE ON FUNCTION {q}.maintenance_validate(uuid) TO PUBLIC'))
    error(post(s,b),503,'conversation_runtime_unapproved')
    assert stored(s.admin)==before


def test_unicode_correction_indices_are_python_codepoints(service):
    s=service;b=seed(s,statement='我制作了3张🧪原型图。');body=command(b,replacement='我制作了2张🧪原型图。')
    response=post(s,b,body);assert response.status_code==201,response.text
    with s.admin() as db:
        source=db.scalar(select(FactChangeSource).where(FactChangeSource.source_role=='statement'))
        turn=db.get(ConversationTurn,source.turn_id)
        assert turn.content[source.start_cp:source.end_cp]==source.quote==body['statements'][0]['quote']
        assert len(source.quote.encode('utf-16-le'))//2==len(source.quote)+1


def worker_url(url):
    # Validate the source before normalizing CI's literal localhost. Do not
    # resolve arbitrary names or widen the child's fixed numeric-loopback gate.
    if (url.get_backend_name() != 'postgresql' or url.host not in ('localhost', '127.0.0.1')
            or url.database not in ('pathwise_test', 'pathwise_e2e')):
        raise ValueError('offline_worker_database_invalid')
    return url.set(host='127.0.0.1')


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1'])
@pytest.mark.parametrize('database', ['pathwise_test', 'pathwise_e2e'])
def test_worker_url_normalizes_only_literal_test_loopback(host, database):
    from sqlalchemy.engine import URL
    source = URL.create('postgresql+psycopg', username='b2b_run_fake', password='public-fake-value',
                        host=host, port=15487, database=database, query={'connect_timeout': '3'})
    normalized = worker_url(source)
    assert normalized == source.set(host='127.0.0.1')
    assert source.host == host  # immutable URL; credentials/port/options unchanged


@pytest.mark.parametrize('host', [None, '', 'LOCALHOST', 'localhost.', 'localhost.evil',
                                'evil-localhost', '192.0.2.1', '127.0.0.2', '::1'])
def test_worker_url_rejects_unapproved_host_before_subprocess(host, monkeypatch):
    from sqlalchemy.engine import URL
    import socket, subprocess
    def forbidden(*args, **kwargs):
        pytest.fail('URL validation must not resolve, connect or launch a child')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr('sqlalchemy.engine.Engine.connect', forbidden)
    with pytest.raises(ValueError, match='^offline_worker_database_invalid$'):
        worker_url(URL.create('postgresql+psycopg', host=host, database='pathwise_test'))


@pytest.mark.parametrize('database', [None, '', 'pathwise_dev', 'pathwise_probe', 'postgres'])
def test_worker_url_rejects_non_test_database(database):
    from sqlalchemy.engine import URL
    with pytest.raises(ValueError, match='^offline_worker_database_invalid$'):
        worker_url(URL.create('postgresql+psycopg', host='localhost', database=database))


def worker(s,b,h,body,mode):
    import json,subprocess,sys
    from pathlib import Path
    env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR','TEMP','TMP') if k in os.environ}
    env['PYTHONIOENCODING']='utf-8'
    # Disposable generated DB credentials travel only to this child via stdin.
    data=dict(url=worker_url(s.runtime.kw['bind'].url).render_as_string(hide_password=False),
              schema=s.schema,sid=str(b.sid),headers=h,body=body,mode=mode)
    return subprocess.run([sys.executable,str(Path(__file__).with_name('maintenance_process_worker.py'))],
        input=json.dumps(data),text=True,encoding='utf-8',capture_output=True,timeout=30,env=env)


@pytest.mark.parametrize('mode,exit_code,count',[('before_commit',71,0),('after_commit',72,1)])
def test_real_process_exit_and_new_process_get_only_recovery(service,mode,exit_code,count):
    import json
    s=service;b=seed(s);body=command(b);h=key(b);before=stored(s.admin)
    crashed=worker(s,b,h,body,mode)
    assert crashed.returncode==exit_code,(crashed.returncode,crashed.stdout,crashed.stderr)
    assert crashed.stdout=='' and crashed.stderr==''
    with s.admin() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==count
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==1+count
        assert db.get(ExperienceFact,b.fid).version==1+count
    stable=stored(s.admin)
    restarted=worker(s,b,h,body,'recover')
    assert restarted.returncode==0 and restarted.stderr==''
    result=json.loads(restarted.stdout)
    assert result['status']==(200 if count else 404)
    if count:assert result['result']['effects'][0]['after_version']==2
    else:assert stable==before
    assert stored(s.admin)==stable


def test_same_key_concurrent_posts_get_one_operation_without_version_change(service):
    s=service;b=seed(s);body=command(b);h=key(b);barrier=Barrier(2)
    def submit():barrier.wait(5);return post(s,b,body,h)
    with ThreadPoolExecutor(2) as pool:responses=list(pool.map(lambda _:submit(),range(2)))
    assert sorted(r.status_code for r in responses)==[200,201]
    assert responses[0].json()==responses[1].json()
    with s.admin() as db:
        assert db.get(ExperienceFact,b.fid).version==2
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==1


def test_success_receipt_recovers_after_end_without_reopening(service):
    s=service;b=seed(s);h=key(b);body=command(b);result=post(s,b,body,h).json()
    with s.admin.begin() as db:facts.end_session(db,b.sid,b.token)
    before=stored(s.admin)
    assert post(s,b,body,h).json()==result
    assert recovery(s,b,h).json()==result
    assert stored(s.admin)==before


def test_future_key_is_refused_without_creating_longer_receipt(service):
    s=service;b=seed(s);h=headers(KIND,f'session:{b.sid}',b.token,issued=int((utcnow()+timedelta(minutes=2)).timestamp()))[0]
    before=stored(s.admin)
    error(post(s,b,h=h),422,'idempotency_clock_skew')
    assert stored(s.admin)==before


def test_rejected_memory_and_legacy_manual_material_reject_remain_compatible(service):
    s=service;b=seed(s,status='evidence_supported')
    with s.admin.begin() as db:
        old_pointer=db.get(ExperienceFact,b.fid).evidence_id
        facts.change_fact(db,b.fid,b.token,status='rejected',expected_version=b.version)
        facts.change_fact(db,b.fid,b.token,memory_state='needs_check',expected_version=b.version+1)
    with s.admin() as db:
        fact=db.get(ExperienceFact,b.fid)
        assert fact.status=='rejected' and fact.evidence_id==old_pointer and fact.memory_state=='needs_check'


def test_operation_id_get_and_parent_key_remain_readonly_after_later_edits(service):
    s=service;b=seed(s);h=key(b);result=post(s,b,h=h).json()
    with s.admin.begin() as db:
        facts.change_fact(db,b.fid,b.token,statement='我测试了1个导出按钮。',expected_version=2)
    before=stored(s.admin)
    response=s.client.get(f'{ROOT}/sessions/{b.sid}/conversation-operations/{result["operation_id"]}',
                          headers={'Authorization':'Bearer '+b.token})
    assert response.status_code==200
    assert response.json()['effects'][0]['applied_status']=='pending'
    assert response.json()['effects'][0]['after_version']==2 and response.json()['effects'][0]['current_version']==3
    assert stored(s.admin)==before
    with s.admin() as db:
        dto=session_view(db,db.get(ExperienceSession,b.sid)).model_dump(mode='json')['facts'][0]
        assert dto['statement']=='我测试了1个导出按钮。' and dto['edit_method']=='legacy_manual'
        assert dto['current_citations']==[] and len(dto['maintenance_history_sources'])==2


def test_expiry_does_not_erase_live_submission_or_allow_new_key(service,monkeypatch):
    from app import fact_maintenance
    s=service;b=seed(s);parent,h,body=ambiguous(s,b);before=stored(s.admin)
    with monkeypatch.context() as patch:
        patch.setattr(fact_maintenance,'utcnow',lambda:utcnow()+timedelta(hours=25))
        response=s.client.get(f'{ROOT}/sessions/{b.sid}/conversation-operations/{parent}',
                              headers={'Authorization':'Bearer '+b.token})
        error(response,410,'conversation_operation_expired')
    current(s,b)
    body['base_revision']=b.revision
    error(post(s,b,body,key(b)),409,'conversation_input_already_submitted')
    with s.admin() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==1
    assert stored(s.admin)==before


def test_key_expiring_after_turn_is_rolled_back_before_commit(service,monkeypatch):
    from app import idempotency
    s=service;b=seed(s);before=stored(s.admin);original=facts.add_turn
    def save_then_expire(*args,**kwargs):
        turn=original(*args,**kwargs)
        monkeypatch.setattr(idempotency,'utcnow',lambda:utcnow()+timedelta(hours=25))
        return turn
    monkeypatch.setattr(facts,'add_turn',save_then_expire)
    error(post(s,b),410,'idempotency_key_expired')
    assert stored(s.admin)==before


def test_top_level_only_and_no_extra_user_role_or_freestanding_statement(service):
    from app import fact_maintenance,idempotency
    from app.maintenance_errors import ConversationError
    s=service;b=seed(s);body=command(b);h=key(b)
    before=stored(s.admin)
    for extra in ({'actor':'user_confirmed'},{'replacement_text':'fabricated'},
                  {'input':{'content':body['input']['content'],'role':'assistant'}}):
        error(post(s,b,{**body,**extra}),422,'invalid_request')
    parsed=idempotency.parse(h['Idempotency-Key'],b.token,KIND,f'session:{b.sid}')
    with s.runtime() as db,db.begin():
        with db.begin_nested():
            with pytest.raises(ConversationError,match='conversation_top_level_required'):
                fact_maintenance.apply(db,b.sid,b.token,parsed,Command.model_validate(body))
    assert stored(s.admin)==before


def test_correction_holds_session_until_commit_and_delete_waits(service):
    s=service;b=seed(s);ready=Event();release=Event();delete_pid=[]
    def hold(db):ready.set();assert release.wait(5)
    event.listen(s.runtime,'before_commit',hold)
    def delete():
        with s.admin.begin() as db:
            delete_pid.append(db.scalar(text('SELECT pg_backend_pid()')))
            session=facts.authorize(db,b.sid,b.token,lock=True)
            db.delete(session);db.flush()
    try:
        with ThreadPoolExecutor(2) as pool:
            writing=pool.submit(post,s,b);assert ready.wait(5)
            deleting=pool.submit(delete)
            try:
                deadline=time.monotonic()+3;observed=False
                while time.monotonic()<deadline:
                    if delete_pid:
                        with s.admin() as db:
                            observed=db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=:pid AND datname=current_database() AND wait_event_type='Lock' AND wait_event='transactionid')"),{'pid':delete_pid[0]})
                        if observed:break
                    time.sleep(.02)
                assert observed,'DELETE did not wait for the real correction Session lock'
            finally:release.set()
            assert writing.result(10).status_code==201
            deleting.result(10)
    finally:event.remove(s.runtime,'before_commit',hold)
    with s.admin() as db:
        assert db.scalar(text("SELECT count(*) FROM conversation_operations WHERE state='deleted'"))==1
        assert db.scalar(text('SELECT count(*) FROM fact_change_sources'))==0
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==0


def test_missing_new_read_acl_fails_closed_for_new_and_legacy_write(service):
    s=service;b=seed(s);before=stored(s.admin)
    with s.admin.begin() as db:
        db.execute(text(f'REVOKE SELECT ON "{s.schema}".conversation_operations FROM "{s.role}"'))
    error(post(s,b),503,'conversation_runtime_unapproved')
    def restricted_legacy():
        with s.runtime() as db,db.begin():yield db
    app.dependency_overrides[get_db]=restricted_legacy
    response=s.client.post(f'{ROOT}/sessions/{b.sid}/turns',headers={'Authorization':'Bearer '+b.token},
                           json={'content':'合成新原话，不应在权限缺失时写入。'})
    error(response,503,'database_unavailable')
    assert stored(s.admin)==before


def test_legacy_model_completion_suppresses_rejected_history_without_new_run_or_provider(service):
    s=service;b=seed(s)
    with s.admin.begin() as db:
        facts.change_fact(db,b.fid,b.token,statement='我测试了2个导出按钮。',expected_version=1)
        facts.change_fact(db,b.fid,b.token,status='rejected',expected_version=2)
        session=db.get(ExperienceSession,b.sid);session.mining_status='active'
        turn=facts.add_turn(db,b.sid,b.token,'我测试了3个导出按钮。');db.refresh(session)
        run=MiningRun(id=uuid4(),session_id=b.sid,project_id=b.pid,input_turn_id=turn.id,
            base_revision=1,reserved_revision=session.context_revision,state='running',
            lease_until=utcnow()+timedelta(minutes=1))
        db.add(run);db.flush();rid,tid=run.id,turn.id
    mining.complete(s.admin,b.sid,b.token,rid,{'candidates':[{'citation':{
        'turn_id':str(tid),'quote':'我测试了3个导出按钮。','start':0,'end':11}}],'questions':[]})
    with s.admin() as db:
        assert db.scalar(text('SELECT count(*) FROM experience_facts'))==1
        assert db.get(ExperienceFact,b.fid).status=='rejected'
        assert db.get(MiningRun,rid).state=='completed'
        assert db.scalar(text('SELECT count(*) FROM ai_mining_runs'))==1
        assert db.scalar(text('SELECT count(*) FROM paid_calls'))==0


@pytest.mark.parametrize('old,new',[
    ('我测试了第3个导出按钮。','我测试了第2个导出按钮。'),
    ('我测试了3号导出按钮。','我测试了2号导出按钮。'),
    ('我在2025年测试了3个导出按钮。','我在2026年测试了3个导出按钮。'),
    ('我测试了3.5个导出按钮。','我测试了2.5个导出按钮。'),
])
def test_numeric_identity_is_not_inferred_for_ordinals_ids_dates_decimals(service,old,new):
    s=service;b=seed(s,statement=old);before=stored(s.admin)
    error(post(s,b,command(b,replacement=new)),422,'correction_identity_unresolved')
    assert stored(s.admin)==before
