"""0011 is inert metadata, exercised only in random disposable schemas.

Approvals, money and credentials here are exclusively synthetic test fixtures.
No real adapter/SecretRef/transport is reachable.
"""
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.script import ScriptDirectory
from alembic.config import Config
import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import DBAPIError

from test_http_api import api
from test_idempotency import headers
from test_mining_paid_binding import binding, new_run, claim_plan
from test_deepseek_bridge import role_capability
from test_deepseek_mining_integration import offline_guard, test_database_only
from app.cost_ledger import digest
from app.models import ExperienceSession
from app.mining_paid_models import MiningPaidIdentity, MiningPaidLimit, MiningPaidPlan, MiningPaidBinding

TABLES=('mining_paid_identities','mining_paid_limits','mining_paid_plans','mining_paid_bindings')
OLD='0010_response_diagnostics'
NEW='0011_mining_paid_metadata'


def candidate(e, run=None, plan_changes=None):
    if run is None:
        run=new_run(e); claim_plan(e,run)
    with e.factory.begin() as db:
        source=dict(db.execute(text(f'SELECT * FROM "{e.schema}".binding_plans WHERE run_id=:r'),{'r':run.rid}).mappings().one())
        source.pop('profile_version');source.pop('created_at')
        source.update(provider='deepseek_official',model='deepseek-flash',config_version='candidate-v1',prompt_version='fixture-v1',schema_version='mining-output-v2')
        source.update(plan_changes or {})
        db.add(MiningPaidIdentity(session_id=run.sid,actor_scope=run.actor_scope,session_scope=run.session_scope,issuer_version='synthetic-only-v1'))
        db.flush()
        db.add(MiningPaidPlan(**source))
    row=e.control.invoke('bind',run.rid)
    bound={k:v for k,v in source.items() if k!='session_id'}
    bound.update(call_id=row['call_id'],actor_scope=run.actor_scope,session_scope=run.session_scope)
    return run,bound


def insert_binding(e, values):
    # Trusted fixture writer only. Candidate installs no runtime writer/grant.
    with e.factory.begin() as db: db.add(MiningPaidBinding(**values))


def audit(e, ledger=None):
    with e.factory() as db:
        return db.scalar(text(f'SELECT "{e.schema}".mining_paid_audit_ok(:l)'),{'l':ledger or e.ledger_id})


def migration_config(e, conn):
    cfg=Config(str(Path(__file__).parents[1]/'alembic.ini'))
    cfg.attributes['connection']=conn
    return cfg


def test_candidate_head_empty_roundtrip_and_no_authority(migrated_connection):
    conn,cfg=migrated_connection
    assert ScriptDirectory.from_config(cfg).get_current_head()==NEW
    funding=conn.execute(text('SELECT * FROM paid_funding')).one()
    assert funding.ceiling==funding.held==funding.spent==0 and not funding.frozen
    for t in (*TABLES,'paid_grants','paid_scopes','paid_calls','paid_audit','controlled_probe'):
        assert conn.scalar(text(f'SELECT count(*) FROM {t}'))==0
    assert conn.scalar(text("SELECT count(*) FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname='binding_runtime'"))==0
    command.check(cfg);conn.commit()
    command.downgrade(cfg,OLD);conn.commit()
    assert not set(TABLES).intersection(inspect(conn).get_table_names());conn.commit()
    command.upgrade(cfg,NEW);conn.commit();command.check(cfg)
    assert conn.execute(text('SELECT * FROM paid_funding')).one()==funding


def test_previous_head_business_data_and_idempotency_survive_upgrade(api,migrated_connection):
    client,factory=api;conn,cfg=migrated_connection
    command.downgrade(cfg,OLD);conn.commit()
    h,_=headers()
    body={'raw_input':'Synthetic pre-0011: implemented a local course filter.'}
    first=client.post('/api/v1/experience/sessions',headers=h,json=body)
    assert first.status_code==201
    before=client.get('/api/v1/experience/sessions/'+first.json()['session_id'],headers={'Authorization':h['Authorization']}).json()
    conn.commit();command.upgrade(cfg,NEW);conn.commit()
    replay=client.post('/api/v1/experience/sessions',headers=h,json=body)
    assert replay.status_code==201 and replay.json()==first.json()
    assert client.get('/api/v1/experience/sessions/'+first.json()['session_id'],headers={'Authorization':h['Authorization']}).json()==before
    with factory() as db: assert db.scalar(select(MiningPaidBinding)) is None


def test_valid_binding_audits_orphan_and_preserves_delete_tombstone(binding):
    e=binding;run,values=candidate(e)
    assert audit(e) is False  # existing unbound call must not look attributed
    insert_binding(e,values)
    assert audit(e) is True and audit(e,uuid4()) is False
    before=e.control.read(run.rid)
    assert e.client.delete('/api/v1/experience/sessions/'+str(run.sid),headers={'Authorization':'Bearer '+run.token}).status_code==204
    with e.factory() as db:
        assert db.get(ExperienceSession,run.sid) is None
        assert db.get(MiningPaidIdentity,run.sid) is None
        assert db.get(MiningPaidPlan,run.rid) is None
        row=db.get(MiningPaidBinding,run.rid)
        assert row.binding_state=='tombstoned' and row.tombstoned_at>=row.created_at
        assert row.call_id==before[0].call_id
    assert audit(e) is True
    assert e.control.read(run.rid)[1:]==before[1:]  # reserved/held, no refund


@pytest.mark.parametrize('field',['ledger_id','call_id','root_run_id','operation_hash','request_sha','account_sha','actor_scope','session_scope','config_version','grant_id'])
def test_binding_cannot_misattribute_call_or_request(binding,field):
    e=binding;run,values=candidate(e)
    bad=uuid4() if field.endswith('_id') else digest('different') if field.endswith(('_sha','_hash','_scope')) else 'different'
    with pytest.raises(DBAPIError): insert_binding(e,values|{field:bad})
    assert audit(e) is False
    with e.factory() as db: assert db.get(MiningPaidBinding,run.rid) is None


@pytest.mark.parametrize('field',['run_id','root_run_id','call_id','operation_hash'])
def test_run_root_call_operation_uniqueness(binding,field):
    e=binding;_,values=candidate(e);insert_binding(e,values)
    with pytest.raises(DBAPIError): insert_binding(e,values)
    # PostgreSQL UNIQUE indexes themselves must cover every named identity.
    with e.factory() as db:
        assert db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_index x JOIN pg_attribute a
          ON a.attrelid=x.indrelid AND a.attnum=ANY(x.indkey)
          WHERE x.indrelid=CAST(:t AS regclass) AND x.indisunique AND x.indnkeyatts=1 AND a.attname=:f)'''),
          dict(t=f'"{e.schema}".mining_paid_bindings',f=field))


@pytest.mark.parametrize('table',TABLES)
def test_any_candidate_record_blocks_dangerous_downgrade(binding,table):
    e=binding
    if table in (TABLES[2],TABLES[3]):
        run,values=candidate(e)
        if table==TABLES[3]: insert_binding(e,values)
    else:
        run=new_run(e)
        with e.factory.begin() as db:
            if table==TABLES[0]:
                db.add(MiningPaidIdentity(session_id=run.sid,actor_scope=run.actor_scope,session_scope=run.session_scope,issuer_version='synthetic-only-v1'))
            else:
                db.add(MiningPaidLimit(ledger_id=e.ledger_id,kind='user',scope=digest('synthetic user'),evidence_sha=digest('zero-limit evidence')))
    with e.factory.kw['bind'].connect() as conn:
        cfg=migration_config(e,conn)
        with pytest.raises(RuntimeError,match='mining_paid_nonempty_downgrade_blocked'):
            with conn.begin(): command.downgrade(cfg,OLD)
        assert conn.scalar(text('SELECT version_num FROM alembic_version'))==NEW
        assert set(TABLES).issubset(inspect(conn).get_table_names())


@pytest.mark.parametrize('action',['UPDATE mining_paid_plans SET config_version=\'tamper\'',
    'DELETE FROM mining_paid_plans','DELETE FROM mining_paid_identities',
    'UPDATE mining_paid_identities SET actor_scope=repeat(\'f\',64)',
    'UPDATE mining_paid_bindings SET binding_state=\'tombstoned\',tombstoned_at=clock_timestamp()',
    'DELETE FROM mining_paid_bindings'])
def test_immutable_records_and_fake_tombstones_rejected(binding,action):
    e=binding;_,values=candidate(e);insert_binding(e,values)
    with pytest.raises(DBAPIError,match='mining_paid_immutable'):
        with e.factory.begin() as db: db.execute(text(action))
    assert audit(e) is True


def test_other_unattributed_call_is_not_accepted(binding):
    e=binding;_,values=candidate(e)
    second=new_run(e,case='S02',turn='b');claim_plan(e,second);e.control.invoke('bind',second.rid)
    with pytest.raises(DBAPIError,match='mining_paid_unattributed_call'): insert_binding(e,values)
    assert audit(e) is False


@pytest.mark.parametrize('state',['approved','reconciled'])
def test_historical_experiment_blocks_new_binding_without_mutation(binding,state):
    from app.controlled_probe_models import ControlledProbe
    e=binding
    # Build a legal plan before adding the mutually exclusive history fixture.
    run,values=candidate(e)
    # A simultaneous historical call/experiment is deliberately inconsistent;
    # metadata must reject it rather than normalize/reset either ledger.
    with e.factory.begin() as db:
        db.add(ControlledProbe(id=1,pool_id=1,grant_id=uuid4(),policy_hash=digest('history'),
            policy={'execution':'offline_mock'},revoked=False,state=state,reserved='.1',actual_cny=0 if state=='reconciled' else None))
    with pytest.raises(DBAPIError,match='mining_paid_experimental_ledger_blocked'): insert_binding(e,values)
    assert audit(e) is False
    with e.factory() as db: assert db.get(ControlledProbe,1).state==state


@pytest.mark.parametrize('sql',[
    'UPDATE paid_funding SET ceiling=ceiling+1', 'DELETE FROM paid_grants',
    'UPDATE paid_calls SET reserved=0', 'INSERT INTO mining_paid_limits(ledger_id,kind,scope,evidence_sha) SELECT ledger_id,\'user\',repeat(\'a\',64),repeat(\'b\',64) FROM paid_funding',
    'DELETE FROM mining_paid_bindings', 'SELECT mining_paid_erasure()',
    'SELECT mining_paid_audit_ok(gen_random_uuid())'])
def test_restricted_login_has_no_new_paid_power(binding,sql):
    e=binding
    with pytest.raises(DBAPIError,match='permission denied'):
        with e.control.engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{e.schema}"'))
            conn.execute(text(sql))


def test_ledger_fk_and_zero_limit_defaults(binding):
    e=binding
    with pytest.raises(DBAPIError):
        with e.factory.begin() as db:
            db.add(MiningPaidLimit(ledger_id=uuid4(),kind='user',scope=digest('fake'),evidence_sha=digest('evidence')))
    with e.factory.begin() as db:
        limit=MiningPaidLimit(ledger_id=e.ledger_id,kind='user',scope=digest('fake'),evidence_sha=digest('evidence'))
        db.add(limit);db.flush()
        assert limit.ceiling==limit.calls_limit==limit.concurrent_limit==0


def test_new_function_owner_search_path_acl_and_no_dispatch(migrated_connection):
    conn,_=migrated_connection
    rows=conn.execute(text('''SELECT p.proname,p.prosecdef,p.proconfig,p.proowner=current_user::regrole AS owned,
      EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee<>p.proowner) AS extra
      FROM pg_proc p WHERE p.pronamespace=current_schema()::regnamespace AND p.proname LIKE 'mining_paid_%' ''')).all()
    assert len(rows)==3
    for row in rows:
        assert row.owned and not row.extra and row.proconfig==['search_path=pg_catalog']
        assert row.prosecdef==(row.proname=='mining_paid_erasure')


def test_failed_upgrade_rolls_back_tables_functions_triggers_and_version(migrated_connection):
    conn,cfg=migrated_connection
    command.downgrade(cfg,OLD);conn.commit()
    before=conn.execute(text('SELECT * FROM paid_funding')).one();conn.commit()
    def fail_after_trigger(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('CREATE TRIGGER mining_paid_erasure '): raise RuntimeError('synthetic injected migration failure')
    event.listen(conn,'after_cursor_execute',fail_after_trigger)
    try:
        with pytest.raises(RuntimeError,match='synthetic injected migration failure'):
            with conn.begin(): command.upgrade(cfg,NEW)
    finally: event.remove(conn,'after_cursor_execute',fail_after_trigger)
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==OLD
    assert not set(TABLES).intersection(inspect(conn).get_table_names())
    assert conn.scalar(text("SELECT count(*) FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'mining_paid_%'"))==0
    assert conn.execute(text('SELECT * FROM paid_funding')).one()==before
    conn.commit();command.upgrade(cfg,NEW);conn.commit();command.check(cfg)


def test_default_privilege_grants_do_not_leak_to_candidate(binding):
    e=binding
    with e.factory.kw['bind'].connect() as conn:
        cfg=migration_config(e,conn)
        command.downgrade(cfg,OLD);conn.commit()
        for object_kind in ('TABLES','FUNCTIONS'):
            conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{e.schema}" GRANT ALL ON {object_kind} TO "{e.role}"'))
        conn.commit()
        try:
            command.upgrade(cfg,NEW);conn.commit()
            for table in TABLES:
                assert not conn.scalar(text('SELECT has_table_privilege(:r,:t,\'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER\')'),dict(r=e.role,t=f'"{e.schema}".{table}'))
            for fn in ('mining_paid_guard()','mining_paid_erasure()','mining_paid_audit_ok(uuid)'):
                assert not conn.scalar(text('SELECT has_function_privilege(:r,:f,\'EXECUTE\')'),dict(r=e.role,f=f'"{e.schema}".{fn}'))
        finally:
            conn.rollback()
            for object_kind in ('TABLES','FUNCTIONS'):
                conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{e.schema}" REVOKE ALL ON {object_kind} FROM "{e.role}"'))
            conn.commit()


def test_upgrade_preserves_unattributed_history_and_reports_block(binding):
    e=binding;run=new_run(e);claim_plan(e,run);e.control.invoke('bind',run.rid)
    before=e.control.read(run.rid)
    with e.factory.kw['bind'].connect() as conn:
        cfg=migration_config(e,conn)
        funding=conn.execute(text('SELECT * FROM paid_funding')).one();conn.commit()
        command.downgrade(cfg,OLD);conn.commit();command.upgrade(cfg,NEW);conn.commit()
        assert conn.execute(text('SELECT * FROM paid_funding')).one()==funding
        assert conn.scalar(text('SELECT count(*) FROM mining_paid_bindings'))==0
    assert audit(e) is False and e.control.read(run.rid)==before


def test_upgrade_preserves_reconciled_experiment_and_exclusivity(binding):
    from app.controlled_probe_models import ControlledProbe
    e=binding
    with e.factory.kw['bind'].connect() as conn:
        cfg=migration_config(e,conn)
        command.downgrade(cfg,OLD);conn.commit()
        with e.factory.begin() as db:
            db.add(ControlledProbe(id=1,pool_id=1,grant_id=uuid4(),policy_hash=digest('historical fixture'),
                policy={'execution':'offline_mock'},revoked=False,state='reconciled',reserved='.1',actual_cny=0))
        before=conn.execute(text('SELECT * FROM controlled_probe')).one();conn.commit()
        command.upgrade(cfg,NEW);conn.commit()
        assert conn.execute(text('SELECT * FROM controlled_probe')).one()==before
    assert audit(e) is False
    run=new_run(e);claim_plan(e,run)
    with pytest.raises(DBAPIError,match='controlled_exclusive_pool'): e.control.invoke('bind',run.rid)
    with pytest.raises(DBAPIError,match='mining_paid_experimental_ledger_blocked'): candidate(e,run)


def test_runtime_cannot_set_role_to_migration_owner(binding):
    e=binding
    with e.factory() as db: owner=db.scalar(text('SELECT current_user'))
    with pytest.raises(DBAPIError,match='permission denied'):
        with e.control.engine.begin() as conn:
            conn.execute(text('SET ROLE '+conn.dialect.identifier_preparer.quote_identifier(owner)))


@pytest.mark.parametrize('field,code',[
    ('root_run_id','run'),('session_id','run'),('receipt_hash','receipt'),
    ('ledger_id','ledger'),('account_sha','grant'),('policy_sha','grant')])
def test_plan_cannot_forge_root_receipt_ledger_or_account(binding,field,code):
    value=uuid4() if field.endswith('_id') else digest('synthetic mismatch')
    with pytest.raises(DBAPIError,match=f'mining_paid_{code}_mismatch'):
        candidate(binding,plan_changes={field:value})


@pytest.mark.parametrize('direction',['upgrade','downgrade'])
def test_busy_migration_stops_without_partial_schema(api,migrated_connection,direction):
    _,factory=api;conn,cfg=migrated_connection
    if direction=='upgrade': command.downgrade(cfg,OLD);conn.commit()
    version=OLD if direction=='upgrade' else NEW
    with factory.kw['bind'].begin() as busy:
        busy.execute(text('SELECT * FROM paid_funding FOR UPDATE'))
        with pytest.raises(DBAPIError,match='could not obtain lock'):
            with conn.begin():
                if direction=='upgrade': command.upgrade(cfg,NEW)
                else: command.downgrade(cfg,OLD)
    assert conn.scalar(text('SELECT version_num FROM alembic_version'))==version
    assert set(TABLES).issubset(inspect(conn).get_table_names())==(direction=='downgrade')


def test_plan_and_binding_times_are_database_assigned(binding):
    from datetime import datetime,timezone
    e=binding;untrusted=datetime(2000,1,1,tzinfo=timezone.utc)
    run,values=candidate(e,plan_changes={'created_at':untrusted})
    insert_binding(e,values)
    with e.factory() as db:
        assert db.get(MiningPaidPlan,run.rid).created_at>untrusted
        assert db.get(MiningPaidBinding,run.rid).created_at>untrusted


def test_business_login_can_erase_without_any_paid_or_metadata_write_permission(binding):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    from app.experience_api import delete_session
    e=binding;run,values=candidate(e);insert_binding(e,values)
    role='metadata_web_'+uuid4().hex
    password=uuid4().hex  # isolated TEST LOGIN only, never a supplier credential
    owner=e.factory.kw['bind']
    with owner.begin() as conn:
        conn.execute(text("SELECT set_config('pathwise.fixture_password',:p,true)"),{'p':password})
        conn.execute(text(f'''DO $$ BEGIN EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD %L',
          '{role}',current_setting('pathwise.fixture_password')); END $$'''))
    runtime=None
    try:
        with owner.begin() as conn:
            conn.execute(text(f'GRANT USAGE ON SCHEMA "{e.schema}" TO "{role}"'))
            # Only original business tables. All paid/probe/cost/binding tables
            # and all their functions remain outside this Web role's grants.
            business=('experience_sessions','experience_projects','conversation_turns',
                'experience_facts','fact_sources','fact_evidence','fact_changes',
                'idempotency_operations','ai_mining_runs','ai_mining_receipts',
                'ai_mining_questions','ai_answer_questions','ai_mining_capacity')
            conn.execute(text('GRANT SELECT,UPDATE,DELETE ON '+','.join(f'"{e.schema}".{t}' for t in business)+f' TO "{role}"'))
            for table in (*TABLES,'paid_funding','paid_calls','paid_grants','paid_audit'):
                assert not conn.scalar(text('SELECT has_table_privilege(:r,:t,\'INSERT,UPDATE,DELETE\')'),dict(r=role,t=f'"{e.schema}".{table}'))
        runtime=create_engine(owner.url.set(username=role,password=password),poolclass=NullPool,
            connect_args={'options':f'-csearch_path={e.schema}'},hide_parameters=True)
        factory=sessionmaker(runtime,expire_on_commit=False)
        with factory() as db,db.begin():
            assert db.scalar(text('SELECT current_user=session_user AND session_user=:r'),{'r':role})
            assert delete_session(run.sid,run.token,db).status_code==204
        with e.factory() as db:
            assert db.get(MiningPaidBinding,run.rid).binding_state=='tombstoned'
            assert db.get(MiningPaidPlan,run.rid) is None
            assert db.get(MiningPaidIdentity,run.sid) is None
        assert e.control.read(run.rid)[1]=='reserved' and audit(e) is True
    finally:
        if runtime is not None: runtime.dispose()
        with owner.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))
