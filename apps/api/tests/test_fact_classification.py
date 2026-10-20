"""C2a M/C matrix. Synthetic PostgreSQL schemas and real restricted LOGINs."""
from types import SimpleNamespace
from datetime import timedelta
from uuid import uuid4
import secrets

import pytest
from alembic import command
from sqlalchemy import create_engine, event, null, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import facts
from app.fact_classification import FIELDS, HEAD, LEGACY, require_legacy
from app.maintenance_errors import ConversationError
from app.maintenance_permissions import check_append_runtime
from app.models import ExperienceFact, ExperienceSession, FactChange, FactSource, MiningRun, utcnow
from app.mining_api import get_mining_factory, get_provider
from app.mining_provider import ScriptedProvider
from app.main import app
from test_http_api import api, create, add, patch
from test_maintenance_api import service, seed, key, post as maintenance_post, command as maintenance_body, error, READS
from test_append_api import append_service, post as append_post, recover, body as append_body
from test_fact_source_maintenance import stored

OLD = '0014_append_batch'
VALID = [LEGACY, ('legacy_unspecified','legacy_unknown','unclassified-v1'),
         ('personal_action','in_progress','explicit-typed-v1'),
         ('personal_action','completed','explicit-typed-v1'),
         ('plan','planned','explicit-typed-v1'), ('plan','in_progress','explicit-typed-v1'),
         ('background','not_applicable','explicit-typed-v1'),
         ('boundary','not_applicable','explicit-typed-v1')]


@pytest.fixture
def legacy_mining_runtime(append_service):
    """Independent LOGIN for pre-admission checks, no B2 role expansion."""
    s=append_service;role='c2a_mining_'+uuid4().hex;password=secrets.token_urlsafe(32)
    with s.admin.begin() as db:
        db.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{s.schema}" TO "{role}"'))
        for table in READS+('ai_mining_capacity','ai_mining_receipts'):
            db.execute(text(f'GRANT SELECT ON "{s.schema}".{table} TO "{role}"'))
        db.execute(text(f'GRANT UPDATE(id) ON "{s.schema}".ai_mining_capacity TO "{role}"'))
        db.execute(text(f'GRANT UPDATE(updated_at,context_revision) ON "{s.schema}".experience_sessions TO "{role}"'))
    engine=create_engine(s.admin.kw['bind'].url.set(username=role,password=password),poolclass=NullPool,
                         hide_parameters=True,connect_args={'options':'-csearch_path='+s.schema})
    try:yield sessionmaker(engine,expire_on_commit=False)
    finally:
        engine.dispose()
        with s.admin.begin() as db:
            db.execute(text(f'DROP OWNED BY "{role}" RESTRICT'));db.execute(text(f'DROP ROLE "{role}"'))


def typed(s, b, values=VALID[3], *, status='user_confirmed', mutate_snapshot=None, mutate_history=None,
          fact_values=None, with_run=False):
    """Trusted owner-only fixture INSERT. Never change an existing classification."""
    with s.admin.begin() as db:
        turn = facts.add_turn(db, b.sid, b.token, '合成分类资料原话。')
        attrs=dict(session_id=b.sid, project_id=b.pid, statement=turn.content, status=status,
                   **{k: (null() if v is None else v) for k,v in zip(FIELDS, values)})
        if with_run:
            run=MiningRun(session_id=b.sid,project_id=b.pid,input_turn_id=turn.id,
                base_revision=1,reserved_revision=1,state='completed',lease_until=utcnow()+timedelta(minutes=1))
            db.add(run);db.flush();attrs.update(origin='ai_extracted',ai_run_id=run.id)
        if status!='pending':attrs['version']=2
        if fact_values or status!='pending':
            # Raw initial INSERT, not an UPDATE blocked by classification_guard;
            # bypass only the ORM's version=1 insertion default, never SQL guards.
            fid=uuid4()
            db.execute(ExperienceFact.__table__.insert().values(id=fid,**{**attrs,**(fact_values or {})}))
            f=db.get(ExperienceFact,fid)
        else:
            f=ExperienceFact(**attrs);db.add(f);db.flush()
        db.add(FactSource(session_id=b.sid, fact_id=f.id, turn_id=turn.id)); db.flush()
        after = facts.snapshot(db, f)
        initial={**after,'version':1,'status':'pending','memory_state':'unspecified','evidence_id':None}
        if mutate_snapshot:
            mutate_snapshot(after)
        change=FactChange(fact_id=f.id, session_id=b.sid, action='created', actor='system',
                          after=initial if status!='pending' else after)
        db.add(change)
        if status!='pending':
            db.add(FactChange(fact_id=f.id,session_id=b.sid,action='status_changed',actor='user',
                              before=initial,after=after))
        if mutate_history:
            mutate_history(db,f,change)
        return SimpleNamespace(fid=f.id, tid=turn.id)


@pytest.mark.parametrize('field,value', [
    ('memory_state','certain'), ('memory_state',None), ('memory_state',True),
    ('origin','ai_extracted'), ('origin',None), ('origin',{}),
    ('ai_run_id',str(uuid4())), ('ai_run_id','null'), ('ai_run_id',False),
    ('ai_run_id',{}), ('ai_run_id',[]), ('ai_run_id',0),
])
def test_review_typed_current_trust_metadata_rejects_mismatch(append_service,field,value):
    s=append_service;b=seed(s);before=stored(s.admin)
    with pytest.raises(IntegrityError):
        typed(s,b,status='pending',mutate_snapshot=lambda a:a.update({field:value}))
    assert stored(s.admin)==before


@pytest.mark.parametrize('fault', ['version','before','actor','status','memory',
                                 'evidence','source_kind','source_turn_ids','source_change_id'])
def test_review_typed_created_semantics_rejects_malformed_history(append_service,fault):
    s=append_service;b=seed(s);before=stored(s.admin)
    def corrupt(db,f,c):
        if fault=='before':c.before={**c.after}
        elif fault=='actor':c.actor='user'
        elif fault not in ('version','status','memory'):
            field,value={'status':('status','user_confirmed'), 'memory':('memory_state','certain'),
                'evidence':('evidence_id',str(uuid4())), 'source_kind':('source_kind','user_edit'),
                'source_turn_ids':('source_turn_ids',[]), 'source_change_id':('source_change_id',str(uuid4()))}[fault]
            c.after={**c.after,field:value}
    attrs={'version':{'version':2},'status':{'status':'user_confirmed'},
           'memory':{'memory_state':'certain'}}.get(fault)
    with pytest.raises(IntegrityError):typed(s,b,status='pending',mutate_history=corrupt,fact_values=attrs)
    assert stored(s.admin)==before


@pytest.mark.parametrize('field,value', [('statement','另一条正文'),('status','rejected'),
    ('memory_state','certain'),('origin','ai_extracted'),('ai_run_id',str(uuid4())),
    ('evidence_id',str(uuid4())),('progress_stage','in_progress')])
def test_review_all_same_version_snapshots_must_match(append_service,field,value):
    s=append_service;b=seed(s);before=stored(s.admin)
    def extra(db,f,c):
        db.add(FactChange(fact_id=f.id,session_id=f.session_id,action='memory_changed',actor='user',
            before=dict(c.after),after={**c.after,field:value}))
    with pytest.raises(IntegrityError):typed(s,b,status='pending',mutate_history=extra)
    assert stored(s.admin)==before


@pytest.mark.parametrize('field', ['memory_state','origin','ai_run_id'])
def test_review_current_metadata_keys_cannot_be_missing(append_service,field):
    s=append_service;b=seed(s);before=stored(s.admin)
    # Valid created/v1, separate confirmed/v2: failure must concern current state.
    with pytest.raises(IntegrityError,match='classification_current_mismatch'):
        typed(s,b,mutate_snapshot=lambda a:a.pop(field))
    assert stored(s.admin)==before


@pytest.mark.parametrize('value', [None,'null',False,{},[],0,'00000000-0000-0000-0000-000000000001'])
def test_review_nonnull_run_current_snapshot_requires_exact_uuid_string(append_service,value):
    s=append_service;b=seed(s);before=stored(s.admin)
    with pytest.raises(IntegrityError,match='classification_current_mismatch'):
        typed(s,b,with_run=True,mutate_snapshot=lambda a:a.update(ai_run_id=value))
    assert stored(s.admin)==before
    with s.admin() as db:assert db.scalar(text('SELECT count(*) FROM ai_mining_runs'))==0


@pytest.mark.parametrize('with_run', [False,True])
@pytest.mark.parametrize('before_sql_null', [False,True])
def test_review_valid_versioned_memory_and_origin_and_identical_snapshots(append_service,with_run,before_sql_null):
    s=append_service;b=seed(s)
    def arrange(db,f,c):
        c.before=null() if before_sql_null else None
        # No new per-version uniqueness rule: identical snapshots are safe.
        after=facts.snapshot(db,f)
        db.add(FactChange(fact_id=f.id,session_id=f.session_id,action='memory_changed',
                          actor='user',before={**after,'memory_state':'unspecified'},after=after))
    t=typed(s,b,with_run=with_run,fact_values={'memory_state':'certain'},mutate_history=arrange)
    with s.admin() as db:
        changes=db.scalars(select(FactChange).where(FactChange.fact_id==t.fid)).all()
        initial=next(c for c in changes if c.action=='created')
        assert initial.after['version']==1 and initial.after['status']=='pending'
        assert initial.after['memory_state']=='unspecified' and initial.before is None
        f=db.get(ExperienceFact,t.fid)
        assert f.version==2 and f.memory_state=='certain'
        current=[c.after for c in changes if c.after['version']==2]
        assert len(current)==2 and current[0]==current[1]
        assert all(a['ai_run_id']==(str(f.ai_run_id) if with_run else None) for a in [initial.after,*current])


@pytest.mark.parametrize('fault,reason', [('duplicate_created','classification_original_source_invalid'),
    ('actor','ck_change_actor'),('run_fk','fk_fact_ai_run')])
def test_review_existing_constraints_already_block_invalid_records(append_service,fault,reason):
    s=append_service;b=seed(s);before=stored(s.admin)
    def corrupt(db,f,c):
        if fault=='actor':c.actor='unknown'
        if fault=='duplicate_created':
            db.add(FactChange(fact_id=f.id,session_id=f.session_id,action='created',actor='system',after=dict(c.after)))
    with pytest.raises(IntegrityError,match=reason):
        typed(s,b,status='pending',mutate_history=corrupt,
              fact_values={'ai_run_id':uuid4()} if fault=='run_fk' else None)
    assert stored(s.admin)==before


@pytest.mark.parametrize('field', ['citations','original_source_turn_ids','source_turn_ids',
                                 'source_kind','source_change_id','version_string','version_numeric'])
def test_review_exact_current_provenance_and_version_cohorts(append_service,field):
    s=append_service;b=seed(s);before=stored(s.admin)
    def extra(db,f,c):
        after=facts.snapshot(db,f)
        if field=='version_string':after['version']=str(f.version)
        elif field=='version_numeric':after.update(version=float(f.version),statement='同版本错误正文')
        elif isinstance(after[field],list):after[field]=[*after[field],str(uuid4())]
        else:after[field]='错误来源'
        db.add(FactChange(fact_id=f.id,session_id=f.session_id,action='memory_changed',
                          actor='user',before=facts.snapshot(db,f),after=after))
    with pytest.raises(IntegrityError,match='classification_current_mismatch'):
        typed(s,b,mutate_history=extra)
    assert stored(s.admin)==before


def bind_mining(s, *, restricted=False):
    class CountingProvider(ScriptedProvider):
        calls=0
        async def mine(self,context):
            self.calls+=1
            return await super().mine(context)
    provider = CountingProvider()
    app.dependency_overrides[get_mining_factory] = lambda: s.append_runtime if restricted else s.admin
    app.dependency_overrides[get_provider] = lambda: provider
    return provider


@pytest.mark.parametrize('values', VALID)
def test_M01_C01_valid_combinations_snapshots_and_legacy_result(append_service, values):
    s=append_service; b=seed(s); r=typed(s,b,values)
    with s.admin() as db:
        f=db.get(ExperienceFact,r.fid)
        assert tuple(getattr(f,k) for k in FIELDS)==values
        snapshot=db.scalar(select(FactChange.after).where(FactChange.fact_id==r.fid))
        if values==LEGACY:
            assert all(k not in snapshot for k in FIELDS)
        else:
            assert tuple(snapshot[k] for k in FIELDS)==values
        assert f.memory_state=='unspecified'
        assert db.scalar(text('SELECT count(*) FROM ai_mining_runs'))==0
        assert db.scalar(text('SELECT count(*) FROM paid_calls'))==0


@pytest.mark.parametrize('values', [
    ('plan','completed','explicit-typed-v1'), ('personal_action','planned','explicit-typed-v1'),
    ('background','completed','explicit-typed-v1'), ('boundary','in_progress','explicit-typed-v1'),
    ('legacy_unspecified','completed','legacy-v0'), ('legacy_unspecified','legacy_unknown','explicit-typed-v1'),
    ('personal_action','completed','legacy-v0'), ('plan','planned','unclassified-v1'),
    ('unknown','not_applicable','explicit-typed-v1'), ('boundary','not_applicable','unknown'),
    (None,'legacy_unknown','legacy-v0'), ('legacy_unspecified',None,'legacy-v0')])
def test_C01_database_rejects_illegal_pairs_zero_write(append_service, values):
    s=append_service; b=seed(s); before=stored(s.admin)
    with pytest.raises(IntegrityError): typed(s,b,values)
    assert stored(s.admin)==before


@pytest.mark.parametrize('fault',['missing','partial','null','wrong','evidence','source','no_change'])
def test_C01_typed_current_snapshot_and_origin_must_match(append_service,fault):
    s=append_service; b=seed(s); before=stored(s.admin)
    def corrupt(snapshot):
        if fault=='missing':
            for k in FIELDS: snapshot.pop(k)
        elif fault=='partial': snapshot.pop('classification_contract')
        elif fault=='null': snapshot['fact_kind']=None
        elif fault=='wrong': snapshot['progress_stage']='in_progress'
        elif fault=='evidence': snapshot['evidence_id']=str(uuid4())
        elif fault=='source': snapshot['original_source_turn_ids']=[]
    with pytest.raises(IntegrityError):
        if fault=='no_change':
            with s.admin.begin() as db:
                db.add(ExperienceFact(session_id=b.sid,project_id=b.pid,statement='无快照合成资料',
                       **dict(zip(FIELDS,VALID[3]))));db.flush()
        else: typed(s,b,mutate_snapshot=corrupt)
    assert stored(s.admin)==before


@pytest.mark.parametrize('route',['session','summary','export','edit','confirm','memory','reject','verify','turn','fact','end','maintenance','append','mining'])
def test_C04_C06_typed_old_routes_auth_first_and_zero_write(append_service,legacy_mining_runtime,route):
    s=append_service;b=seed(s);foreign=seed(s);t=typed(s,b,status='pending')
    provider=bind_mining(s,restricted=True)
    if route=='mining':app.dependency_overrides[get_mining_factory]=lambda:legacy_mining_runtime
    from app.experience_api import get_db
    def restricted_db():
        with s.append_runtime() as db,db.begin():yield db
    app.dependency_overrides[get_db]=restricted_db
    root='/api/v1/experience'; h={'Authorization':'Bearer '+b.token}
    if route=='session': method,url,payload='get',f'{root}/sessions/{b.sid}',None
    elif route=='summary': method,url,payload='get',f'{root}/projects/{b.pid}/experience-summary',None
    elif route=='export': method,url,payload='get',f'{root}/sessions/{b.sid}/export',None
    elif route in ('edit','confirm','memory','reject','verify'):
        action={'memory':'set_memory','verify':'verify_material'}.get(route,route)
        payload=dict(action=action,expected_version=1)
        if route=='edit':payload['statement']='旧编辑不能洗成 legacy。'
        if route=='memory':payload['memory_state']='certain'
        if route=='verify':payload.update(material_reference='synthetic',basis='synthetic')
        method,url='patch',f'{root}/facts/{t.fid}'
    elif route=='turn': method,url,payload='post',f'{root}/sessions/{b.sid}/turns',{'content':'未保存补充'}
    elif route=='fact':method,url,payload='post',f'{root}/projects/{b.pid}/facts',{'statement':'未保存事实','source_turn_ids':[str(b.tid)]}
    elif route=='end':method,url,payload='post',f'{root}/sessions/{b.sid}/end',None
    elif route in ('append','maintenance'):
        suffix='conversation-appends' if route=='append' else 'conversation-operations'
        method,url='post',f'{root}/sessions/{b.sid}/{suffix}'
        payload=append_body(b) if route=='append' else maintenance_body(b)
    else:
        from test_idempotency import headers
        method,url,payload='post',f'{root}/sessions/{b.sid}/mining-runs',dict(project_id=str(b.pid),base_revision=1,input_turn_id=str(b.tid))
    def request(token):
        hh={'Authorization':'Bearer '+token}
        if route in ('append','maintenance'):
            from test_idempotency import headers
            hh=headers('conversation_maintenance_v1',f'session:{b.sid}',token)[0]
        elif route=='mining':
            from test_idempotency import headers
            hh=headers('mining_run',f'session:{b.sid}',token)[0]
        return s.client.request(method,url,headers=hh,**({'json':payload} if payload is not None else {}))
    before=stored(s.admin)
    error(request(foreign.token),404,'resource_unavailable')
    code={'summary':'summary_contract_upgrade_required','export':'export_contract_upgrade_required'}.get(route,'fact_contract_upgrade_required')
    error(request(b.token),409,code)
    assert stored(s.admin)==before and provider.calls==0


@pytest.mark.parametrize('attack',['edit','legacy','source_update','source_delete','source_insert','source_move_in','history_delete','history_update','history_insert','fact_delete','truncate'])
def test_C01_C03_no_typed_mutation_or_origin_erasure(append_service,attack):
    s=append_service;b=seed(s);t=typed(s,b);before=stored(s.admin)
    sql={
        'edit':"UPDATE experience_facts SET statement='changed',version=version+1 WHERE id=:id",
        'legacy':"UPDATE experience_facts SET fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0' WHERE id=:id",
        'source_update':"UPDATE fact_sources SET citations='[]' WHERE fact_id=:id",
        'source_delete':'DELETE FROM fact_sources WHERE fact_id=:id',
        'source_insert':'INSERT INTO fact_sources(fact_id,turn_id,session_id) VALUES(:id,:tid,:sid)',
        'source_move_in':'UPDATE fact_sources SET fact_id=:id WHERE fact_id=:old_id',
        'history_delete':'DELETE FROM fact_changes WHERE fact_id=:id',
        'history_update':"UPDATE fact_changes SET after=after-'fact_kind' WHERE fact_id=:id",
        'history_insert':"INSERT INTO fact_changes(id,created_at,fact_id,session_id,action,actor,after) SELECT :cid,now(),fact_id,session_id,'status_changed','user',after FROM fact_changes WHERE fact_id=:id LIMIT 1",
        'fact_delete':'DELETE FROM experience_facts WHERE id=:id',
        'truncate':'TRUNCATE fact_sources',
    }[attack]
    with pytest.raises(IntegrityError),s.admin.begin() as db:
        db.execute(text(sql),{'id':t.fid,'tid':b.tid,'sid':b.sid,'cid':uuid4(),'old_id':b.fid})
    assert stored(s.admin)==before
    assert s.client.delete(f'/api/v1/experience/sessions/{b.sid}',headers={'Authorization':'Bearer '+b.token}).status_code==204


@pytest.mark.parametrize('fault',['column','constraint','trigger','version','permission','history_permission'])
def test_C03_C06_schema_and_permissions_fail_closed(append_service,fault):
    s=append_service;b=seed(s);before=stored(s.admin)
    # Test-owned catalog/ACL damage only. No bypass option in application code.
    with s.admin.begin() as db:
        if fault=='column':db.execute(text('ALTER TABLE experience_facts DROP COLUMN progress_stage CASCADE'))
        elif fault=='constraint':db.execute(text('ALTER TABLE experience_facts DROP CONSTRAINT ck_fact_classification'))
        elif fault=='trigger':db.execute(text('ALTER TABLE experience_facts DISABLE TRIGGER classification_consistent'))
        elif fault=='version':db.execute(text("COMMENT ON TABLE experience_facts IS 'pathwise-classification-schema-v2'"))
        elif fault=='permission':
            db.execute(text(f'REVOKE SELECT ON experience_facts FROM "{s.append_role}"'))
            db.execute(text(f'GRANT SELECT(id,session_id,project_id) ON experience_facts TO "{s.append_role}"'))
        else:db.execute(text(f'REVOKE SELECT ON fact_changes FROM "{s.append_role}"'))
    after_damage=stored(s.admin)
    with pytest.raises(ConversationError) as caught,s.append_runtime.begin() as db:
        facts.authorize(db,b.sid,b.token)
        require_legacy(db,b.sid)
    assert caught.value.status==503
    assert stored(s.admin)==after_damage
    if fault not in ('column',):assert after_damage==before


def test_C03_restricted_login_cannot_create_typed_or_call_helpers(append_service):
    s=append_service;b=seed(s);before=stored(s.admin)
    with s.append_runtime() as db:
        check_append_runtime(db)
        assert db.scalar(text('SELECT current_user'))==s.append_role
        assert db.scalar(text("SELECT count(*) FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'classification_%' AND has_function_privilege(current_user,oid,'EXECUTE')"))==0
    with pytest.raises(IntegrityError,match='classification_writer_unapproved'),s.append_runtime.begin() as db:
        db.add(ExperienceFact(session_id=b.sid,project_id=b.pid,statement='越权分类',**dict(zip(FIELDS,VALID[3]))));db.flush()
    with pytest.raises(DBAPIError),s.append_runtime.begin() as db:
        db.execute(text("SELECT classification_value('{}'::jsonb)"))
    assert stored(s.admin)==before


def test_C03_database_rejects_legacy_co_even_without_python_gate(append_service):
    from datetime import timedelta
    from app.fact_maintenance_models import ConversationOperation
    from app.models import ConversationTurn,utcnow
    s=append_service;b=seed(s);typed(s,b);before=stored(s.admin)
    with pytest.raises(IntegrityError,match='classification_legacy_operation_refused'),s.runtime.begin() as db:
        turn=ConversationTurn(session_id=b.sid,role='user',content='纠正上一条。我测试了2个导出按钮。')
        db.add(turn);db.flush()
        session=db.get(ExperienceSession,b.sid);db.refresh(session)
        db.add(ConversationOperation(session_id=b.sid,input_turn_id=turn.id,contract_version=1,
            key_digest='a'*64,state='needs_clarification',kind='root',action='disambiguate',
            proposed_action='correct',submission_tag='b'*64,request_tag='c'*64,
            proposal_spans=[{'role':'intent','start':0,'end':6},{'role':'statement','start':6,'end':len(turn.content)}],
            base_revision=1,result_revision=session.context_revision,effect_count=0,outcome_code='target_ambiguous',
            decision_contract='explicit-target-v1',expires_at=utcnow()+timedelta(hours=23)))
        db.flush()
    assert stored(s.admin)==before


@pytest.mark.parametrize('attack',['move_in','citations'])
def test_C03_source_deferred_check_independently_rejects_origin_drift(append_service,attack):
    s=append_service;b=seed(s);t=typed(s,b);before=stored(s.admin)
    # Test-owned fault injection simulates a source write passing the earlier
    # immediate check. COMMIT must independently prove the immutable origin.
    with pytest.raises(IntegrityError,match='classification_original_source_invalid'),s.admin.begin() as db:
        db.execute(text('ALTER TABLE fact_sources DISABLE TRIGGER classification_immutable'))
        if attack=='move_in':
            db.execute(text('UPDATE fact_sources SET fact_id=:new WHERE fact_id=:old'),{'new':t.fid,'old':b.fid})
        else:db.execute(text("UPDATE fact_sources SET citations='[{}]'::jsonb WHERE fact_id=:id"),{'id':t.fid})
    assert stored(s.admin)==before


def test_M01_C03_upgrade_revokes_named_default_execute_grants(append_service,migrated_connection):
    s=append_service;conn,cfg=migrated_connection
    command.downgrade(cfg,OLD);conn.commit()
    conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{s.schema}" GRANT EXECUTE ON FUNCTIONS TO "{s.append_role}"'));conn.commit()
    try:
        command.upgrade(cfg,HEAD);conn.commit()
        with s.append_runtime() as db:
            check_append_runtime(db)
            rows=db.execute(text("SELECT p.proname,has_function_privilege(current_user,p.oid,'EXECUTE'),r.rolcanlogin FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.pronamespace=current_schema()::regnamespace AND p.proname LIKE 'classification_%'")).all()
            assert len(rows)==3 and all(not execute and not login for _,execute,login in rows)
    finally:
        conn.rollback();conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{s.schema}" REVOKE EXECUTE ON FUNCTIONS FROM "{s.append_role}"'));conn.commit()


@pytest.mark.parametrize('fault',['public','owner'])
def test_C03_unsafe_function_owner_or_acl_denies_runtime(append_service,fault):
    s=append_service;b=seed(s);before=stored(s.admin)
    with s.admin.begin() as db:
        if fault=='public':db.execute(text('GRANT EXECUTE ON FUNCTION classification_value(jsonb) TO PUBLIC'))
        else:db.execute(text(f'ALTER FUNCTION classification_value(jsonb) OWNER TO "{s.append_role}"'))
    error(append_post(s,b),503,'conversation_runtime_unapproved')
    assert stored(s.admin)==before


@pytest.mark.parametrize('status',['pending','user_confirmed','evidence_supported','rejected'])
def test_M01_0014_upgrade_preserves_all_old_rows_json_and_http(append_service,migrated_connection,status):
    s=append_service;conn,cfg=migrated_connection
    command.downgrade(cfg,OLD);conn.commit()
    b=seed(s,status=status)
    h={'Authorization':'Bearer '+b.token};bind_mining(s)
    root='/api/v1/experience'
    urls=[f'{root}/sessions/{b.sid}',f'{root}/projects/{b.pid}/experience-summary']
    before_views=[s.client.get(u,headers=h).json() for u in urls]
    before=stored(s.admin)
    export=s.client.get(f'{root}/sessions/{b.sid}/export',headers=h).json()['data']
    command.upgrade(cfg,HEAD);conn.commit();command.check(cfg);conn.commit()
    after=stored(s.admin)
    import json
    for row in after['experience_facts']:
        obj=json.loads(row)
        assert tuple(obj.pop(k) for k in FIELDS)==LEGACY
        assert obj in [json.loads(x) for x in before['experience_facts']]
    for table in before:
        if table!='experience_facts':assert after[table]==before[table]
    assert [s.client.get(u,headers=h).json() for u in urls]==before_views
    assert s.client.get(f'{root}/sessions/{b.sid}/export',headers=h).json()['data']==export
    # Existing confirm/edit/memory/material/reject behavior remains available.
    f=s.client.patch(f'{root}/facts/{b.fid}',headers=h,json={'action':'edit','expected_version':b.version,'statement':'旧事实修改后仍待确认。'})
    if status=='rejected':
        error(f,409,'state_conflict')
        assert stored(s.admin)==after
        return
    assert f.status_code==200 and f.json()['status']=='pending'
    f=patch(s.client,f.json(),h,'set_memory',memory_state='certain');assert f.status_code==200
    f=patch(s.client,f.json(),h,'confirm');assert f.status_code==200
    f=patch(s.client,f.json(),h,'verify_material',material_reference='synthetic',basis='synthetic');assert f.status_code==200
    f=patch(s.client,f.json(),h,'reject');assert f.status_code==200


@pytest.mark.parametrize('old_revision',['0005_answer_questions','0010_response_diagnostics',
    '0011_mining_paid_metadata','0012_request_manifest','0013_fact_maintenance','0014_append_batch'])
def test_M01_genuine_preclassification_schemas_preserve_legacy_reads(api,migrated_connection,old_revision):
    client,factory=api;conn,cfg=migrated_connection
    command.downgrade(cfg,old_revision);conn.commit()
    data,h=create(client);f=add(client,data,h)
    assert patch(client,f,h,'confirm').status_code==200
    url=f'/api/v1/experience/sessions/{data["session_id"]}'
    before=client.get(url,headers=h)
    assert before.status_code==200,before.text
    exported=client.get(url+'/export',headers=h)
    assert exported.status_code==200,exported.text
    command.upgrade(cfg,HEAD);conn.commit()
    after=client.get(url,headers=h)
    assert after.status_code==200 and after.json()==before.json()
    after_export=client.get(url+'/export',headers=h)
    assert after_export.status_code==200 and after_export.json()['data']==exported.json()['data']


@pytest.mark.parametrize('with_legacy',[False,True])
def test_M01_M02_empty_roundtrip_failure_rollback_and_function_fingerprints(migrated_connection,with_legacy):
    conn,cfg=migrated_connection
    command.check(cfg);conn.commit();command.downgrade(cfg,OLD);conn.commit()
    if with_legacy:
        with Session(conn) as db,db.begin():
            p,t,token=facts.create_experience(db,'合成迁移回滚旧资料')
            f=facts.add_fact(db,p.id,token,t.content,[t.id])
            facts.change_fact(db,f.id,token,status='user_confirmed',expected_version=1)
    rows_before=conn.scalars(text('SELECT to_jsonb(c)::text FROM fact_changes c ORDER BY id')).all();conn.commit()
    def fingerprint():return conn.execute(text("SELECT oid,proowner,proacl::text,prosrc,proconfig FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'maintenance_%' ORDER BY oid")).all()
    before=fingerprint();conn.commit()
    def fail(connection,cursor,sql,parameters,context,many):
        if 'CREATE FUNCTION' in sql and 'classification_guard()' in sql:raise RuntimeError('synthetic_c2a_migration_failure')
    event.listen(conn,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='synthetic_c2a_migration_failure'):command.upgrade(cfg,HEAD)
        conn.rollback()
    finally:event.remove(conn,'before_cursor_execute',fail)
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==OLD
    assert conn.scalar(text("SELECT count(*) FROM pg_attribute WHERE attrelid='experience_facts'::regclass AND attname='fact_kind' AND NOT attisdropped"))==0
    assert conn.scalar(text("SELECT count(*) FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'classification_%'"))==0
    assert conn.scalars(text('SELECT to_jsonb(c)::text FROM fact_changes c ORDER BY id')).all()==rows_before
    assert fingerprint()==before;conn.commit()
    command.upgrade(cfg,HEAD);conn.commit();command.downgrade(cfg,OLD);conn.commit()
    assert fingerprint()==before
    assert conn.scalar(text("SELECT count(*) FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'classification_%'"))==0
    conn.commit();command.upgrade(cfg,HEAD);conn.commit();command.check(cfg);conn.commit()


def test_M02_typed_history_cannot_downgrade_or_hide_behind_current_labels(append_service,migrated_connection):
    s=append_service;b=seed(s);t=typed(s,b)
    conn,cfg=migrated_connection
    with pytest.raises(RuntimeError,match='classification_nonempty_downgrade_refused'):command.downgrade(cfg,OLD)
    conn.rollback()
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==HEAD;conn.commit()
    # Owner-only corruption arranges a historical typed marker with legacy
    # current labels. This is an attack fixture, not a supported reclassification.
    with s.admin.begin() as db:
        db.execute(text('ALTER TABLE experience_facts DISABLE TRIGGER classification_immutable'))
        db.execute(text('ALTER TABLE experience_facts DISABLE TRIGGER classification_consistent'))
        db.execute(text("UPDATE experience_facts SET fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0' WHERE id=:id"),{'id':t.fid})
        db.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        db.execute(text('ALTER TABLE experience_facts ENABLE TRIGGER classification_immutable'))
        db.execute(text('ALTER TABLE experience_facts ENABLE TRIGGER classification_consistent'))
    before=stored(s.admin);bind_mining(s)
    for url,code in [(f'/api/v1/experience/sessions/{b.sid}','fact_contract_upgrade_required'),
                     (f'/api/v1/experience/projects/{b.pid}/experience-summary','summary_contract_upgrade_required'),
                     (f'/api/v1/experience/sessions/{b.sid}/export','export_contract_upgrade_required')]:
        error(s.client.get(url,headers={'Authorization':'Bearer '+b.token}),409,code)
    with pytest.raises(RuntimeError,match='classification_nonempty_downgrade_refused'):command.downgrade(cfg,OLD)
    conn.rollback()
    error(s.client.patch(f'/api/v1/experience/facts/{t.fid}',headers={'Authorization':'Bearer '+b.token},json={'action':'edit','expected_version':1,'statement':'不能洗回 legacy。'}),409,'fact_contract_upgrade_required')
    assert stored(s.admin)==before


def test_C06_no_typed_route_or_factory_and_v2_receipts_still_recover(append_service):
    s=append_service;b=seed(s);h=key(b);result=append_post(s,b,h=h)
    assert result.status_code==201
    typed(s,b)
    before=stored(s.admin)
    assert recover(s,b,h).json()==result.json()
    assert append_post(s,b,append_body(b),h).json()==result.json()
    for url in [f'/api/v2/experience/projects/{b.pid}/experience-summary',f'/api/v2/experience/sessions/{b.sid}/export']:
        assert s.client.get(url,headers=h).status_code==404
    value=append_body(b);value['contract_version']=3
    error(append_post(s,b,value),422,'invalid_request')
    assert stored(s.admin)==before
