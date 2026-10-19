"""Fail-closed role admission. This module grants nothing and opens no factory.

An independently reviewed deployment must supply a restricted service factory.
Tests use real LOGIN roles, separate from non-LOGIN trigger-function owners.
"""
from sqlalchemy import text

from app.maintenance_errors import ConversationError


def check_runtime(db):
    _check_runtime(db, append=False)


def check_append_runtime(db):
    _check_runtime(db, append=True)
    if not db.scalar(text("""SELECT EXISTS(SELECT 1 FROM pg_proc
        WHERE pronamespace=current_schema()::regnamespace AND proname='maintenance_validate'
          AND position('append_v2_bijection' in prosrc)>0)""")):
        raise ConversationError(503, 'append_schema_unavailable')


def _check_runtime(db, *, append):
    role = db.execute(text('''SELECT current_user,session_user,rolsuper,rolcreatedb,
        rolcreaterole,rolreplication,rolbypassrls,rolinherit
        FROM pg_roles WHERE rolname=current_user''')).one()
    if role[0] != role[1] or any(role[2:]):
        raise ConversationError(503, 'conversation_runtime_unapproved')
    if db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname<>current_user
        AND pg_has_role(current_user,oid,'MEMBER'))''')):
        raise ConversationError(503, 'conversation_runtime_unapproved')
    if db.scalar(text('''SELECT has_database_privilege(current_database(),'CREATE')
        OR has_schema_privilege(current_schema(),'CREATE')''')):
        raise ConversationError(503, 'conversation_runtime_unapproved')
    for table in ('experience_sessions','experience_projects','conversation_turns','experience_facts',
                  'fact_changes','fact_sources','fact_evidence','ai_mining_runs',
                  'conversation_operations','fact_change_sources'):
        if not db.scalar(text("SELECT has_table_privilege(current_user,to_regclass(:table),'SELECT')"), {'table': table}):
            raise ConversationError(503, 'conversation_runtime_unapproved')
    functions = db.execute(text('''SELECT p.oid,p.prosecdef,p.proconfig,
        (r.rolcanlogin OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
          OR EXISTS(SELECT 1 FROM pg_roles other WHERE other.oid<>r.oid AND pg_has_role(r.oid,other.oid,'MEMBER'))
          OR has_table_privilege(r.oid,'paid_funding','INSERT,UPDATE,DELETE')),
        pg_has_role(current_user,p.proowner,'MEMBER'),
        has_function_privilege(current_user,p.oid,'EXECUTE'),
        EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
        FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
        WHERE p.pronamespace=current_schema()::regnamespace AND p.proname LIKE 'maintenance_%'
    ''')).all()
    if len(functions) != 6 or any(not f[1] or f[2] != ['search_path=pg_catalog'] or any(f[3:]) for f in functions):
        raise ConversationError(503, 'conversation_runtime_unapproved')
    # No table owner, DDL, extra writers, money or call-function privileges.
    insertable = {'conversation_turns', 'fact_changes', 'conversation_operations', 'fact_change_sources'}
    updatable = {'experience_sessions', 'experience_facts', 'conversation_operations'}
    if append:
        insertable |= {'experience_facts', 'fact_sources'}
        updatable = {'experience_sessions'}
    rows = db.execute(text('''SELECT c.relname,c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user),
        has_any_column_privilege(current_user,c.oid,'INSERT'),
        has_any_column_privilege(current_user,c.oid,'UPDATE'),
        has_table_privilege(current_user,c.oid,'DELETE,TRUNCATE,TRIGGER,REFERENCES')
        FROM pg_class c WHERE c.relnamespace=current_schema()::regnamespace AND c.relkind='r'
    ''')).all()
    if any(owner or deleting or (ins and name not in insertable) or (upd and name not in updatable)
           for name, owner, ins, upd, deleting in rows):
        raise ConversationError(503, 'conversation_runtime_unapproved')
    # UPDATE(id) is solely the PostgreSQL permission needed for FOR UPDATE;
    # the immutable trigger rejects actual receipt mutation (including no-op).
    allowed_columns = {
        'experience_sessions': {'updated_at', 'context_revision'},
        'experience_facts': {'statement', 'status', 'evidence_id', 'updated_at', 'version'},
        'conversation_operations': {'id'},
    }
    if append:
        allowed_columns = {'experience_sessions': {'updated_at', 'context_revision'}}
        for table in insertable:
            if not db.scalar(text("SELECT has_table_privilege(current_user,to_regclass(:table),'INSERT')"), {'table': table}):
                raise ConversationError(503, 'conversation_runtime_unapproved')
    for table, columns in allowed_columns.items():
        if db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_attribute a
            WHERE a.attrelid=to_regclass(:table) AND a.attnum>0 AND NOT a.attisdropped
              AND a.attname<>ALL(:allowed)
              AND has_column_privilege(current_user,a.attrelid,a.attnum,'UPDATE'))'''),
            {'table': table, 'allowed': sorted(columns)}):
            raise ConversationError(503, 'conversation_runtime_unapproved')
    if db.scalar(text('''SELECT EXISTS(SELECT 1 FROM pg_proc p
        WHERE p.pronamespace=current_schema()::regnamespace
        AND (p.proname LIKE 'paid_%' OR p.proname LIKE 'controlled_%' OR p.proname LIKE 'binding_%'
          OR (p.prosecdef AND p.prorettype<>'trigger'::regtype))
        AND has_function_privilege(current_user,p.oid,'EXECUTE'))''')):
        raise ConversationError(503, 'conversation_runtime_unapproved')
