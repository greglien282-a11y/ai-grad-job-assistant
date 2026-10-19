"""B2-a: real PostgreSQL, disposable schemas, no new HTTP write path.

The fixture writer is trusted migration-owner test code, not a public command.
No Provider, paid ledger, credential resolver or network transport is used.
"""
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import facts
from app.models import ConversationTurn, ExperienceFact, ExperienceSession, FactChange, utcnow
from app.fact_maintenance_models import ConversationOperation, FactChangeSource
from test_http_api import api, create, add, patch
from test_deepseek_bridge import role_capability
from test_deepseek_mining_integration import offline_guard, test_database_only


TABLES = ('conversation_operations', 'fact_change_sources')
OLD = '0012_request_manifest'
NEW = '0013_fact_maintenance'
UNICODE = '我制作了🧪原型图。'


def tag():
    return sha256(uuid4().bytes).hexdigest()  # synthetic, no production key


def base(db):
    project, turn, token = facts.create_experience(db, '我测试了3个导出按钮。')
    return SimpleNamespace(sid=project.session_id, pid=project.id, tid=turn.id, token=token)


def append_operation(db, b, *, operation=None, source=None, after=None, statement=UNICODE, extra=None, before_audit=None):
    """Construct the prospective atomic write as one trusted fixture transaction."""
    session = facts.authorize(db, b.sid, b.token, write=True)
    revision = session.context_revision
    # Trusted DB-attack fixture: insert directly so B2-b's shared HTTP/domain
    # duplicate guard cannot mask the database uniqueness/audit assertions.
    # No production bypass option is added; the real INSERT triggers still run.
    turn = ConversationTurn(session_id=b.sid, role='user', content=UNICODE)
    db.add(turn); db.flush()
    citation = {'turn_id': str(turn.id), 'start': 0, 'end': len(UNICODE), 'quote': UNICODE}
    fact = facts.add_fact(db, b.pid, b.token, statement, [turn.id], citations=[citation])
    change = db.scalar(select(FactChange).where(FactChange.fact_id == fact.id))
    if after is not None:
        change.after = after(change.after.copy())
    if extra=='change':
        facts.add_fact(db,b.pid,b.token,'我测试了界面。',[turn.id])
    if extra=='turn':
        facts.add_turn(db,b.sid,b.token,'另一条未归入回执的回答。')
    if before_audit is not None:
        before_audit(db, fact, turn, change)
    db.flush()
    db.refresh(session)
    op = ConversationOperation(id=uuid4(), key_digest=tag(), state='applied',
        session_id=b.sid, input_turn_id=turn.id, kind='root', action='append',
        submission_tag=tag(), request_tag=tag(),
        proposal_spans=[{'role': 'statement', 'start': 0, 'end': len(UNICODE)}],
        base_revision=revision, result_revision=session.context_revision,
        effect_count=1, outcome_code='created', decision_contract='explicit-target-v1',
        expires_at=utcnow()+timedelta(hours=23))
    for k, v in (operation or {}).items():
        setattr(op, k, v)
    db.add(op)
    db.flush()
    src = FactChangeSource(id=uuid4(), operation_id=op.id, effect_slot=1,
        change_id=change.id, fact_id=fact.id, session_id=b.sid, turn_id=turn.id,
        source_role='statement', reason='addition', start_cp=0, end_cp=len(UNICODE),
        quote=UNICODE, after_version=1)
    for k, v in (source or {}).items():
        setattr(src, k, v)
    db.add(src)
    db.flush()
    return SimpleNamespace(oid=op.id, fid=fact.id, cid=change.id, srcid=src.id, tid=turn.id)


def correction(db, b, fid, *, action='correct', parent=None):
    session = facts.authorize(db, b.sid, b.token, write=True)
    revision = session.context_revision
    old = db.get(ExperienceFact, fid)
    version = old.version
    content = '纠正上一条。我测试了2个导出按钮。' if action == 'correct' else '撤回上一条。'
    turn = facts.add_turn(db, b.sid, b.token, content) if parent is None else db.get(ConversationTurn, parent.input_turn_id)
    if action == 'correct':
        facts.change_fact(db, fid, b.token, statement=content[6:], expected_version=version)
    else:
        facts.change_fact(db, fid, b.token, status='rejected', expected_version=version)
    change = db.scalar(select(FactChange).where(FactChange.fact_id == fid).order_by(FactChange.after['version'].as_integer().desc()))
    db.refresh(session)
    spans = [{'role': 'intent', 'start': 0, 'end': 6}]
    if action == 'correct':
        spans.append({'role': 'statement', 'start': 6, 'end': len(content)})
    op = ConversationOperation(id=uuid4(), key_digest=tag(), state='applied', session_id=b.sid,
        input_turn_id=turn.id, kind='resolution' if parent else 'root', action=action,
        parent_operation_id=parent.id if parent else None, submission_tag=None if parent else tag(),
        request_tag=tag(), proposal_spans=spans, base_revision=revision,
        result_revision=session.context_revision, target_fact_id=fid, target_version=version,
        effect_count=1, outcome_code='corrected' if action=='correct' else 'withdrawn',
        decision_contract='explicit-target-v1', expires_at=utcnow()+timedelta(hours=23))
    db.add(op); db.flush()
    for span in spans:
        db.add(FactChangeSource(id=uuid4(), operation_id=op.id, effect_slot=1,
            change_id=change.id, fact_id=fid, session_id=b.sid, turn_id=turn.id,
            source_role=span['role'], reason='explicit_correction' if action=='correct' else 'explicit_withdrawal',
            start_cp=span['start'], end_cp=span['end'], quote=content[span['start']:span['end']],
            before_version=version, after_version=version+1))
    db.flush()
    return op.id


def initial(factory):
    with factory.begin() as db:
        b=base(db)
    return b


def test_unicode_append_read_history_and_later_edit(api):
    _, factory=api; b=initial(factory)
    assert len(UNICODE)==9 and len(UNICODE.encode('utf-16le'))//2==10
    with factory.begin() as db: r=append_operation(db,b)
    with factory.begin() as db:
        src=db.get(FactChangeSource,r.srcid)
        assert src.quote==UNICODE and src.end_cp==9
        assert db.get(FactChange,r.cid).after['statement']==UNICODE
        facts.change_fact(db,r.fid,b.token,statement='我制作了另一张原型图。',expected_version=1)
    with factory() as db:
        assert db.get(ExperienceFact,r.fid).version==2
        assert db.get(FactChangeSource,r.srcid).quote==UNICODE
        assert db.get(FactChange,r.cid).after['statement']==UNICODE
        assert db.scalar(text('SELECT count(*) FROM ai_mining_runs'))==0


@pytest.mark.parametrize('action', ['correct','withdraw'])
def test_correction_or_withdrawal_exact_effect(api,action):
    _,factory=api; b=initial(factory)
    with factory.begin() as db:
        f=facts.add_fact(db,b.pid,b.token,'我测试了3个导出按钮。',[b.tid]); fid=f.id
        facts.change_fact(db,fid,b.token,status='user_confirmed',expected_version=1)
    with factory.begin() as db: oid=correction(db,b,fid,action=action)
    with factory() as db:
        f=db.get(ExperienceFact,fid)
        assert f.version==3 and f.status==('pending' if action=='correct' else 'rejected')
        assert db.scalar(select(ConversationOperation.effect_count).where(ConversationOperation.id==oid))==1
        assert len(db.scalars(select(FactChangeSource).where(FactChangeSource.operation_id==oid)).all())==(2 if action=='correct' else 1)


@pytest.mark.parametrize('kind', ['quote','utf16','wrong_span','reason','slot','version','role',
    'missing_after','null_after','number_after','changed_after','changed_current','count','revision',
    'missing_revision','missing_tag','expires','progress','extra_span_key','boolean_offset','float_offset'])
def test_invalid_atomic_source_or_receipt_rolls_back(api,kind):
    _,factory=api; b=initial(factory)
    op={};src={};after=None;statement=UNICODE
    if kind=='quote':src['quote']='我编造了成果。'
    if kind=='utf16':src['end_cp']=10
    if kind=='wrong_span':src['start_cp']=1
    if kind=='reason':src['reason']='explicit_correction'
    if kind=='slot':src['effect_slot']=2
    if kind=='version':src['after_version']=2
    if kind=='role':src['source_role']='intent'
    if kind=='missing_after':after=lambda a:{k:v for k,v in a.items() if k!='statement'}
    if kind=='null_after':after=lambda a:dict(a,statement=None)
    if kind=='number_after':after=lambda a:dict(a,statement=17)
    if kind=='changed_after':after=lambda a:dict(a,statement='我编造了成果。')
    if kind=='changed_current':statement='我编造了成果。'
    if kind=='count':op['effect_count']=2
    if kind=='revision':op['result_revision']=9999
    if kind=='missing_revision':op['base_revision']=None
    if kind=='missing_tag':op['request_tag']=None
    if kind=='expires':op['expires_at']=utcnow()+timedelta(hours=25)
    if kind=='progress':op.update(action='progress',outcome_code='progress_recorded',progress_stage='completed')
    if kind=='extra_span_key':op['proposal_spans']=[dict(role='statement',start=0,end=9,quote=UNICODE)]
    if kind=='boolean_offset':op['proposal_spans']=[dict(role='statement',start=False,end=9)]
    if kind=='float_offset':op['proposal_spans']=[dict(role='statement',start=0.5,end=9)]
    with pytest.raises(IntegrityError),factory.begin() as db:
        append_operation(db,b,operation=op,source=src,after=after,statement=statement)
    with factory() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==1
        for t in (*TABLES,'experience_facts','fact_changes'):
            assert db.scalar(text(f'SELECT count(*) FROM {t}'))==0


@pytest.mark.parametrize('table,sql', [
    ('conversation_operations',"UPDATE conversation_operations SET request_tag=repeat('a',64)"),
    ('conversation_operations','DELETE FROM conversation_operations'),
    ('conversation_operations','TRUNCATE conversation_operations CASCADE'),
    ('fact_change_sources',"UPDATE fact_change_sources SET quote='tampered'"),
    ('fact_change_sources','DELETE FROM fact_change_sources'),
    ('fact_change_sources','TRUNCATE fact_change_sources'),
    ('fact_changes',"UPDATE fact_changes SET after='{}'::jsonb"),
    ('experience_facts',"UPDATE experience_facts SET statement='tampered'"),
    ('experience_facts',"UPDATE experience_facts SET statement='tampered',version=version+1"),
    ('experience_facts',"UPDATE experience_facts SET version=version+2"),
    ('experience_facts','DELETE FROM experience_facts')])
def test_committed_audit_is_immutable(api,table,sql):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:r=append_operation(db,b)
    with pytest.raises(IntegrityError),factory.begin() as db:db.execute(text(sql))
    with factory() as db:
        assert db.get(FactChangeSource,r.srcid).quote==UNICODE
        assert db.get(ExperienceFact,r.fid).statement==UNICODE


def test_session_delete_minimal_tombstone_and_no_partial_erasure(api):
    client,factory=api;b=initial(factory)
    with factory.begin() as db:r=append_operation(db,b)
    fields='session_id input_turn_id kind action parent_operation_id submission_tag request_tag proposed_action proposal_spans progress_stage base_revision result_revision target_fact_id target_version effect_count outcome_code decision_contract completed_at'.split()
    with pytest.raises(IntegrityError),factory.begin() as db:
        db.execute(text("UPDATE conversation_operations SET state='deleted',"+','.join(k+'=NULL' for k in fields)))
    with factory() as db:
        old=db.get(ConversationOperation,r.oid)
        retained=(old.id,old.contract_version,old.key_digest,old.created_at,old.expires_at)
    assert client.delete(f'/api/v1/experience/sessions/{b.sid}',headers={'Authorization':'Bearer '+b.token}).status_code==204
    with factory() as db:
        row=db.get(ConversationOperation,r.oid)
        assert row.state=='deleted' and all(getattr(row,k) is None for k in fields)
        assert retained==(row.id,row.contract_version,row.key_digest,row.created_at,row.expires_at)
        for t in ('fact_change_sources','fact_changes','conversation_turns','experience_facts'):
            assert db.scalar(text(f'SELECT count(*) FROM {t}'))==0
    with pytest.raises(IntegrityError),factory.begin() as db:
        db.execute(text('DELETE FROM conversation_operations'))  # unexpired
    with pytest.raises(IntegrityError),factory.begin() as db:
        # No fresh deleted tombstone can be fabricated to reserve/release a key.
        db.add(ConversationOperation(id=uuid4(),key_digest=tag(),state='deleted',expires_at=utcnow()+timedelta(hours=1)))


@pytest.mark.parametrize('case',['assistant','cross_session','old_turn','old_change','duplicate_key','duplicate_submission'])
def test_cross_scope_retrofit_and_duplicate_rejected(api,case):
    _,factory=api;b=initial(factory);other=initial(factory)
    if case in ('duplicate_key','duplicate_submission'):
        with factory.begin() as db:r=append_operation(db,b)
    with pytest.raises(IntegrityError),factory.begin() as db:
        if case=='assistant':
            r=append_operation(db,b)
            # Existing turn immutability also independently rejects this attack.
            db.execute(text("UPDATE conversation_turns SET role='assistant' WHERE id=:i"),{'i':r.tid})
        elif case=='cross_session':append_operation(db,b,source={'session_id':other.sid})
        elif case=='old_turn':append_operation(db,b,operation={'input_turn_id':b.tid})
        elif case=='old_change':
            # Old FactChange must not gain a newly claimed conversational source.
            with factory.begin() as prior:old=append_operation(prior,other)
            append_operation(db,b,source={'change_id':old.cid,'fact_id':old.fid})
        else:
            old=db.get(ConversationOperation,r.oid)
            append_operation(db,b,operation={('key_digest' if case=='duplicate_key' else 'submission_tag'):getattr(old,'key_digest' if case=='duplicate_key' else 'submission_tag')})


def test_rejected_patch_shared_function_and_memory_compatibility(api):
    client,factory=api;data,h=create(client);f=add(client,data,h)
    rejected=patch(client,f,h,'reject').json()
    with factory() as db:
        before=db.get(ExperienceSession,db.get(ExperienceFact,f['id']).session_id).context_revision
        changes=db.scalar(text('SELECT count(*) FROM fact_changes'))
    assert patch(client,rejected,h,'edit',statement='Synthetic replacement').status_code==409
    assert patch(client,f,h,'edit',statement='Synthetic stale replacement').status_code==409
    with pytest.raises(facts.StateConflict),factory.begin() as db:
        facts.change_fact(db,rejected['id'],data['access_token'],statement='Synthetic replacement',expected_version=rejected['version'])
    with factory() as db:
        assert db.scalar(text('SELECT context_revision FROM experience_sessions'))==before
        assert db.scalar(text('SELECT count(*) FROM fact_changes'))==changes
        assert db.get(ExperienceFact,f['id']).status=='rejected'
    memory=patch(client,rejected,h,'set_memory',memory_state='needs_check')
    assert memory.status_code==200 and memory.json()['status']=='rejected'
    exported=client.get(f'/api/v1/experience/sessions/{data["session_id"]}/export',headers=h)
    assert exported.status_code==200 and len(exported.json()['data']['history'])==changes+1


@pytest.mark.parametrize('status',['pending','user_confirmed','evidence_supported'])
def test_other_status_text_edits_still_require_confirmation(api,status):
    client,_=api;data,h=create(client);f=add(client,data,h)
    if status!='pending':f=patch(client,f,h,'confirm').json()
    if status=='evidence_supported':f=patch(client,f,h,'verify_material',material_reference='synthetic',basis='synthetic').json()
    response=patch(client,f,h,'edit',statement='Synthetic updated contribution')
    assert response.status_code==200
    assert response.json()['status']=='pending' and response.json()['evidence_id'] is None


def test_reject_commits_before_waiting_edit_no_resurrection(api):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:
        f=facts.add_fact(db,b.pid,b.token,'我测试了3个导出按钮。',[b.tid]);fid=f.id
    locked=Event();attempted=Event()
    def reject():
        with factory.begin() as db:
            facts.change_fact(db,fid,b.token,status='rejected',expected_version=1)
            locked.set();assert attempted.wait(5)
    def edit():
        assert locked.wait(5)
        with pytest.raises(facts.VersionConflict),factory.begin() as db:
            attempted.set()
            facts.change_fact(db,fid,b.token,statement='我测试了2个导出按钮。',expected_version=1)
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(reject),pool.submit(edit)]
        for f in futures:f.result(10)
    with factory() as db:
        assert db.get(ExperienceFact,fid).status=='rejected'
        assert db.scalar(text('SELECT count(*) FROM fact_changes'))==2


def test_head_empty_roundtrip_and_alembic_metadata(migrated_connection):
    conn,cfg=migrated_connection
    assert ScriptDirectory.from_config(cfg).get_current_head()==NEW
    command.check(cfg);conn.commit()
    command.downgrade(cfg,OLD);conn.commit()
    assert not set(TABLES).intersection(inspect(conn).get_table_names());conn.commit()
    command.upgrade(cfg,NEW);conn.commit();command.check(cfg);conn.commit()
    assert conn.scalar(text('SELECT ceiling+held+spent FROM paid_funding'))==0


@pytest.mark.parametrize('state',['live','deleted'])
def test_nonempty_downgrade_refused(api,migrated_connection,state):
    client,factory=api;b=initial(factory)
    with factory.begin() as db:append_operation(db,b)
    if state=='deleted':assert client.delete(f'/api/v1/experience/sessions/{b.sid}',headers={'Authorization':'Bearer '+b.token}).status_code==204
    conn,cfg=migrated_connection;conn.commit()
    with pytest.raises(RuntimeError,match='maintenance_nonempty_downgrade_refused'):command.downgrade(cfg,OLD)
    conn.rollback()
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==NEW


def test_failed_upgrade_is_atomic_and_old_business_survives(api,migrated_connection):
    client,_=api;conn,cfg=migrated_connection
    command.downgrade(cfg,OLD);conn.commit()
    data,h=create(client);f=add(client,data,h)
    def fail(connection,cursor,statement,parameters,context,many):
        if 'CREATE FUNCTION' in statement and 'maintenance_guard()' in statement:raise RuntimeError('synthetic_migration_failure')
    event.listen(conn,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='synthetic_migration_failure'):command.upgrade(cfg,NEW)
        conn.rollback()
    finally:event.remove(conn,'before_cursor_execute',fail)
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==OLD
    assert not set(TABLES).intersection(inspect(conn).get_table_names());conn.commit()
    assert patch(client,f,h,'confirm').status_code==200
    command.upgrade(cfg,NEW);conn.commit()
    assert patch(client,f,h,'edit',statement='Synthetic stale edit').status_code==409


def test_public_and_restricted_role_have_no_new_authority(api,migrated_connection,role_capability):
    assert role_capability, 'isolated PostgreSQL test owner requires CREATEROLE'
    _,factory=api;conn,_=migrated_connection
    schema=conn.scalar(text('SELECT current_schema()'));conn.commit()
    role='maintenance_test_'+uuid4().hex
    with conn.begin():conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'))
    try:
        with conn.begin():conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
        with conn.begin():
            rows=conn.execute(text("SELECT p.oid,p.prosecdef,p.proconfig,p.proowner FROM pg_proc p WHERE p.pronamespace=current_schema()::regnamespace AND p.proname LIKE 'maintenance_%'" )).all()
            assert len(rows)==6
            for oid,secdef,config,owner in rows:
                assert secdef and config==['search_path=pg_catalog']
                assert not conn.scalar(text("SELECT has_function_privilege(:r,:o,'EXECUTE')"),{'r':role,'o':oid})
                assert not conn.scalar(text('SELECT EXISTS(SELECT 1 FROM aclexplode((SELECT proacl FROM pg_proc WHERE oid=:o)) WHERE grantee=0 AND privilege_type=\'EXECUTE\')'),{'o':oid})
            for t in TABLES:
                for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                    assert not conn.scalar(text('SELECT has_table_privilege(:r,:t,:p)'),{'r':role,'t':f'{schema}.{t}','p':privilege})
        for t in TABLES:
            with pytest.raises(DBAPIError),factory.begin() as db:
                db.execute(text(f'SET LOCAL ROLE "{role}"'))
                db.execute(text(f'DELETE FROM {t}'))
    finally:
        conn.rollback()
        with conn.begin():
            conn.execute(text(f'REVOKE USAGE ON SCHEMA "{schema}" FROM "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


def test_needs_clarification_resolution_retains_parent_and_input(api):
    _,factory=api;b=initial(factory)
    content='纠正上一条。我测试了2个导出按钮。'
    with factory.begin() as db:
        f=facts.add_fact(db,b.pid,b.token,'我测试了3个导出按钮。',[b.tid]);fid=f.id
    with factory.begin() as db:
        session=facts.authorize(db,b.sid,b.token,write=True);revision=session.context_revision
        turn=facts.add_turn(db,b.sid,b.token,content);db.refresh(session)
        parent=ConversationOperation(id=uuid4(),key_digest=tag(),state='needs_clarification',
            session_id=b.sid,input_turn_id=turn.id,kind='root',action='disambiguate',
            submission_tag=tag(),request_tag=tag(),proposed_action='correct',
            proposal_spans=[dict(role='intent',start=0,end=6),dict(role='statement',start=6,end=len(content))],
            base_revision=revision,result_revision=session.context_revision,effect_count=0,
            outcome_code='target_ambiguous',decision_contract='explicit-target-v1',expires_at=utcnow()+timedelta(hours=23))
        db.add(parent);db.flush();parent_id=parent.id
    with factory.begin() as db:
        parent=db.get(ConversationOperation,parent_id)
        child=correction(db,b,fid,parent=parent)
    with factory() as db:
        assert db.get(ConversationOperation,parent_id).state=='needs_clarification'
        assert db.get(ConversationOperation,child).parent_operation_id==parent_id
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==2
    # Neither a second resolution nor a resolution chain can reuse the answer.
    with pytest.raises(IntegrityError,match='uq_co_resolution'),factory.begin() as db:
        prior=db.get(ConversationOperation,child)
        values={column.name:getattr(prior,column.name) for column in ConversationOperation.__table__.columns}
        values.update(id=uuid4(),key_digest=tag(),request_tag=tag())
        db.add(ConversationOperation(**values));db.flush()
    with factory.begin() as db:
        db.execute(text('DELETE FROM experience_sessions WHERE id=:s'),{'s':b.sid})
    with factory() as db:
        rows=db.scalars(select(ConversationOperation)).all()
        assert len(rows)==2 and all(row.state=='deleted' and row.parent_operation_id is None for row in rows)
        assert db.scalar(text('SELECT count(*) FROM fact_change_sources'))==0


def test_expired_deleted_cleanup_only(api):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:
        r=append_operation(db,b,operation={'expires_at':utcnow()+timedelta(seconds=2)})
    with factory.begin() as db:
        db.execute(text('DELETE FROM experience_sessions WHERE id=:s'),{'s':b.sid})
    # Test-only wall clock wait, not a mutation of immutable expiry metadata.
    with factory.begin() as db:db.execute(text('SELECT pg_sleep(2)'))
    with factory.begin() as db:
        assert db.execute(text('DELETE FROM conversation_operations WHERE id=:i'),{'i':r.oid}).rowcount==1


@pytest.mark.parametrize('state',['stopped','ended'])
def test_local_maintenance_stopped_allowed_ended_denied(api,state):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:
        s=db.get(ExperienceSession,b.sid)
        if state=='stopped':s.mining_status='stopped'
        else:s.status='ended'
    if state=='ended':
        with pytest.raises(facts.StateConflict),factory.begin() as db:append_operation(db,b)
    else:
        with factory.begin() as db:append_operation(db,b)
        with factory() as db:
            assert db.get(ExperienceSession,b.sid).mining_status=='stopped'
            assert db.scalar(text('SELECT count(*) FROM ai_mining_runs'))==0


def test_assistant_source_insert_denied_by_new_validator(api):
    _,factory=api;b=initial(factory)
    with pytest.raises(IntegrityError,match='maintenance_operation_invalid'),factory.begin() as db:
        assistant=ConversationTurn(session_id=b.sid,role='assistant',content=UNICODE)
        db.add(assistant);db.flush()
        clone=ConversationOperation(id=uuid4(),key_digest=tag(),state='applied',session_id=b.sid,
            input_turn_id=assistant.id,kind='root',action='append',submission_tag=tag(),request_tag=tag(),
            proposal_spans=[dict(role='statement',start=0,end=9)],base_revision=1,
            result_revision=db.scalar(text('SELECT context_revision FROM experience_sessions WHERE id=:s'),{'s':b.sid}),
            effect_count=0,outcome_code='no_new_fact',decision_contract='explicit-target-v1',
            expires_at=utcnow()+timedelta(hours=23))
        db.add(clone);db.flush()


def test_default_grants_are_removed_on_upgrade(migrated_connection,role_capability):
    assert role_capability
    conn,cfg=migrated_connection;command.downgrade(cfg,OLD);conn.commit()
    schema=conn.scalar(text('SELECT current_schema()'));conn.commit()
    role='maintenance_acl_'+uuid4().hex
    with conn.begin():
        conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT ALL ON TABLES TO "{role}"'))
        conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT EXECUTE ON FUNCTIONS TO "{role}"'))
    try:
        command.upgrade(cfg,NEW);conn.commit()
        for table in TABLES:
            assert not conn.scalar(text("SELECT has_table_privilege(:r,:t,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"),{'r':role,'t':f'{schema}.{table}'})
        assert conn.scalar(text("SELECT count(*) FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'maintenance_%' AND has_function_privilege(:r,oid,'EXECUTE')"),{'r':role})==0
        conn.commit()
    finally:
        conn.rollback()
        with conn.begin():
            conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" REVOKE ALL ON TABLES FROM "{role}"'))
            conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" REVOKE EXECUTE ON FUNCTIONS FROM "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


def test_effects_cannot_adopt_old_history_in_same_session(api):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:r=append_operation(db,b)
    with pytest.raises(IntegrityError),factory.begin() as db:
        # Unique(change,role) separately blocks duplication of audited history.
        append_operation(db,b,source={'change_id':r.cid,'fact_id':r.fid})


def test_concurrent_same_submission_has_one_receipt(api):
    _,factory=api;b=initial(factory);submission=tag()
    def write():
        try:
            with factory.begin() as db:append_operation(db,b,operation={'submission_tag':submission})
            return 'committed'
        except DBAPIError as exc:
            assert exc.orig.sqlstate=='23505'
            return 'duplicate'
    with ThreadPoolExecutor(2) as pool:
        outcomes=list(pool.map(lambda _:write(),range(2)))
    assert sorted(outcomes)==['committed','duplicate']
    with factory() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==1
        assert db.scalar(text('SELECT count(*) FROM fact_changes'))==1
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==2


@pytest.mark.parametrize('extra',['change','turn'])
def test_receipt_cannot_hide_unlinked_effects_or_duplicate_answer(api,extra):
    _,factory=api;b=initial(factory)
    with pytest.raises(IntegrityError,match='maintenance_unreceipted_effect'),factory.begin() as db:
        append_operation(db,b,extra=extra)
    with factory() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==1
        assert db.scalar(text('SELECT count(*) FROM fact_changes'))==0


@pytest.mark.parametrize('table,sql',[
    ('conversation_turns','UPDATE conversation_turns SET created_at=clock_timestamp()'),
    ('fact_changes','UPDATE fact_changes SET after=after')])
def test_old_rows_cannot_be_touched_to_fake_insert_xmin(api,table,sql):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:facts.add_fact(db,b.pid,b.token,'我测试了3个导出按钮。',[b.tid])
    with pytest.raises(IntegrityError,match='maintenance_(input|history)_immutable'),factory.begin() as db:
        db.execute(text(sql))
    with factory() as db:
        assert db.scalar(text(f'SELECT count(*) FROM {table}'))==1


def test_concurrent_corrections_only_one_expected_version_commits(api):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:
        f=facts.add_fact(db,b.pid,b.token,'我测试了3个导出按钮。',[b.tid]);fid=f.id
    gate=Event();second=Event()
    def first():
        with factory.begin() as db:
            correction(db,b,fid)
            gate.set();assert second.wait(5)
    def stale():
        assert gate.wait(5)
        with pytest.raises(facts.VersionConflict),factory.begin() as db:
            # Read old version before waiting on the session lock.
            assert db.get(ExperienceFact,fid).version==1
            second.set()
            facts.change_fact(db,fid,b.token,statement='我测试了1个导出按钮。',expected_version=1)
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(first),pool.submit(stale)]
        for future in futures:future.result(10)
    with factory() as db:
        assert db.get(ExperienceFact,fid).version==2
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==1
        assert db.scalar(text('SELECT count(*) FROM fact_change_sources'))==2


@pytest.mark.parametrize('delete_first',[True,False])
def test_delete_maintenance_lock_order_and_tombstone(api,delete_first):
    _,factory=api;b=initial(factory);locked=Event();attempted=Event()
    def first():
        with factory.begin() as db:
            facts.authorize(db,b.sid,b.token,write=True)
            if delete_first:db.execute(text('DELETE FROM experience_sessions WHERE id=:s'),{'s':b.sid})
            else:append_operation(db,b)
            locked.set();assert attempted.wait(5)
    def last():
        assert locked.wait(5)
        if delete_first:
            with pytest.raises(PermissionError),factory.begin() as db:
                attempted.set();append_operation(db,b)
        else:
            with factory.begin() as db:
                attempted.set()
                facts.authorize(db,b.sid,b.token,write=True)
                db.execute(text('DELETE FROM experience_sessions WHERE id=:s'),{'s':b.sid})
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(first),pool.submit(last)]
        for future in futures:future.result(10)
    with factory() as db:
        assert db.get(ExperienceSession,b.sid) is None
        assert db.scalar(text('SELECT count(*) FROM fact_change_sources'))==0
        assert db.scalar(text("SELECT count(*) FROM conversation_operations WHERE state='deleted'"))==int(not delete_first)
