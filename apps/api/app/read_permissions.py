"""Admission for an independent SELECT-only LOGIN; never grants privileges."""
from sqlalchemy import text
from app.fact_classification import has_columns, MARKER
from app.maintenance_errors import ConversationError

READ_TABLES=('experience_sessions','experience_projects','conversation_turns','experience_facts',
    'fact_changes','fact_sources','fact_evidence','ai_mining_runs','ai_mining_questions',
    'ai_answer_questions','conversation_operations','fact_change_sources')


def check_reader(db):
    if not has_columns(db):raise ConversationError(503,'experience_read_schema_unavailable')
    comment=db.scalar(text("SELECT obj_description('experience_facts'::regclass,'pg_class')")) or ''
    markers=[line for line in comment.splitlines() if line.startswith('pathwise-classification-schema-')]
    if markers!=[MARKER]:raise ConversationError(503,'experience_read_schema_unavailable')
    role=db.execute(text('''SELECT current_user,session_user,rolcanlogin,rolsuper,rolcreatedb,
        rolcreaterole,rolreplication,rolbypassrls,rolinherit FROM pg_roles WHERE rolname=current_user''')).one()
    bad=role[0]!=role[1] or not role[2] or any(role[3:])
    bad=bad or db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname<>current_user
        AND pg_has_role(current_user,oid,'MEMBER')) OR has_database_privilege(current_database(),'CREATE')
        OR has_schema_privilege(current_schema(),'CREATE')'''))
    if bad:raise ConversationError(503,'experience_read_runtime_unapproved')
    for table in READ_TABLES:
        if not db.scalar(text("SELECT has_table_privilege(current_user,to_regclass(:t),'SELECT')"),{'t':table}):
            raise ConversationError(503,'experience_read_runtime_unapproved')
        if db.scalar(text('SELECT relrowsecurity OR relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:t)'),{'t':table}):
            raise ConversationError(503,'experience_read_runtime_unapproved')
    if db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_class c WHERE c.relnamespace=current_schema()::regnamespace
        AND c.relkind IN ('r','p') AND (pg_has_role(current_user,c.relowner,'MEMBER')
        OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE')
        OR has_table_privilege(current_user,c.oid,'DELETE,TRUNCATE,TRIGGER,REFERENCES')
        OR (c.relname<>ALL(:allowed) AND has_any_column_privilege(current_user,c.oid,'SELECT'))))'''),
        {'allowed':list(READ_TABLES)}):
        raise ConversationError(503,'experience_read_runtime_unapproved')
    functions=db.execute(text('''SELECT p.prosecdef,p.proconfig,
        r.rolcanlogin OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls,
        EXISTS(SELECT 1 FROM pg_roles other WHERE other.oid<>r.oid AND pg_has_role(r.oid,other.oid,'MEMBER')),
        has_table_privilege(r.oid,'paid_funding','INSERT,UPDATE,DELETE'),
        has_function_privilege(current_user,p.oid,'EXECUTE'),
        EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
        FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.pronamespace=current_schema()::regnamespace
        AND (p.proname LIKE 'maintenance_%' OR p.proname LIKE 'classification_%')''')).all()
    if len(functions)!=9 or any(not f[0] or f[1]!=['search_path=pg_catalog'] or any(f[2:]) for f in functions):
        raise ConversationError(503,'experience_read_runtime_unapproved')
    if db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_proc p WHERE p.pronamespace=current_schema()::regnamespace
        AND (p.proname LIKE 'paid_%' OR p.proname LIKE 'controlled_%' OR p.proname LIKE 'binding_%'
          OR (p.prosecdef AND p.prorettype<>'trigger'::regtype))
        AND has_function_privilege(current_user,p.oid,'EXECUTE'))''')):
        raise ConversationError(503,'experience_read_runtime_unapproved')
