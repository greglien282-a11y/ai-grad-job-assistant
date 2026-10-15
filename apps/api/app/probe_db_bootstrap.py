"""Fixed-target local initialization; no migration, billing or provider code."""
from contextlib import contextmanager
import json
from pathlib import Path
import secrets

from psycopg import sql

from app.probe_db_credentials import ROLES, REFS, LocalDatabaseError, connect_local

DATABASE = 'pathwise_probe'
CONFIRMATION = 'CREATE pathwise_probe AND TWO RESTRICTED ROLES'


def new_passwords():
    # Exactly 32 OS-CSPRNG bytes per draw (256 random bits), URL-safe encoding.
    first, second = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    if first == second:
        # Fail, never silently reduce entropy or spin/retry a broken RNG.
        raise LocalDatabaseError('random_generation_failed')
    return dict(zip(ROLES, (first, second)))


class LocalPostgresAdmin:
    """Private operator adapter. All SQL objects/targets are constants."""
    def __init__(self, connection):
        self.connection = connection

    def precheck(self):
        c = self.connection
        with c.transaction():
            c.execute('SET TRANSACTION READ ONLY')
            row = c.execute("SELECT current_database(),current_user,rolsuper,rolcreatedb,rolcreaterole,"
                "current_setting('server_version_num')::int FROM pg_roles WHERE rolname=current_user").fetchone()
            # Superuser is needed for the session-only SQL-log protections below.
            if not row or row[:5] != ('postgres', 'postgres', True, True, True) or not 160000 <= row[5] < 170000:
                raise LocalDatabaseError('maintenance_identity_or_permissions_changed')
            found = c.execute("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='pathwise_probe'),"
                "EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pathwise_probe_owner'),"
                "EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pathwise_probe_runner')").fetchone()
            if any(found):
                raise LocalDatabaseError('target_already_exists')
            # Extensions/audit hooks may capture verifiers despite core settings.
            settings = c.execute("SELECT current_setting('shared_preload_libraries'),"
                "current_setting('session_preload_libraries'),current_setting('local_preload_libraries')").fetchone()
            if any(settings):
                raise LocalDatabaseError('unreviewed_database_logging_hooks')

    def lock(self):
        if not self.connection.execute('SELECT pg_try_advisory_lock(718430921)').fetchone()[0]:
            raise LocalDatabaseError('database_initialization_busy')
        self.connection.commit()

    def protect_sql_logs(self):
        # Session-only, no ALTER SYSTEM/config/service changes. Never plaintext
        # SQL passwords, even if an external DBA observes activity or auditing.
        for statement in ("SET log_statement='none'", "SET log_min_error_statement='panic'",
            "SET log_min_duration_statement=-1", "SET log_min_duration_sample=-1",
            "SET log_statement_sample_rate=0"):
            self.connection.execute(statement)
        self.connection.commit()

    def create_role(self, role, password):
        if role not in ROLES:
            raise LocalDatabaseError('role_target_rejected')
        verifier = None
        try:
            verifier = self.connection.pgconn.encrypt_password(password.encode('utf8'),
                role.encode('ascii'), b'scram-sha-256').decode('ascii')
            if not verifier.startswith('SCRAM-SHA-256$'):
                raise LocalDatabaseError('scram_unavailable')
            with self.connection.transaction():
                self.connection.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                    'NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}').format(sql.Identifier(role), sql.Literal(verifier)))
        finally:
            verifier = None

    def create_database(self):
        c = self.connection
        c.autocommit = True
        try:
            # template0, not template1 or any user database. No PUBLIC race:
            # keep connections disabled until database ACLs are committed.
            c.execute('CREATE DATABASE pathwise_probe OWNER pathwise_probe_owner TEMPLATE template0 ALLOW_CONNECTIONS false')
        finally:
            c.autocommit = False

    def database_acl(self):
        with self.connection.transaction():
            self.connection.execute('REVOKE ALL ON DATABASE pathwise_probe FROM PUBLIC')
            self.connection.execute('GRANT CONNECT ON DATABASE pathwise_probe TO pathwise_probe_owner,pathwise_probe_runner')
            self.connection.execute('ALTER DATABASE pathwise_probe ALLOW_CONNECTIONS true')

    def verify_catalogs(self):
        with self.connection.transaction():
            self.connection.execute('SET TRANSACTION READ ONLY')
            row = self.connection.execute("SELECT pg_get_userbyid(datdba),datallowconn,"
                "NOT EXISTS(SELECT 1 FROM aclexplode(COALESCE(datacl,acldefault('d',datdba))) a WHERE a.grantee=0) "
                "FROM pg_database WHERE datname='pathwise_probe'").fetchone()
            if row != (ROLES[0], True, True):
                raise LocalDatabaseError('database_acl_verification_failed')
            rows = self.connection.execute("SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
                "rolreplication,rolbypassrls,rolinherit,"
                "EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid) "
                "FROM pg_roles r WHERE rolname IN ('pathwise_probe_owner','pathwise_probe_runner') ORDER BY rolname").fetchall()
            if rows != [(role, True, False, False, False, False, False, False, False) for role in ROLES]:
                raise LocalDatabaseError('role_verification_failed')


@contextmanager
def recovery_admin(path):
    """Only the documented protected recovery file, never .env or URL discovery."""
    from app.probe_preview import LocalPreviewStore, _acl
    path = Path(path).absolute()
    LocalPreviewStore(path.parent)._check_links(path)
    _acl(path)
    value = None
    password = None
    connection = None
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if (not isinstance(value, dict) or value.get('admin_user') != 'postgres'
            or type(value.get('port')) is not int or value['port'] != 5432
            or not isinstance(value.get('admin_password'), str) or not value['admin_password']):
            raise LocalDatabaseError('recovery_structure_invalid')
        password = value['admin_password']
        connection = connect_local(role='postgres', password=password, database='postgres')
        password = None
        value.clear()
        yield LocalPostgresAdmin(connection)
    finally:
        password = None
        if isinstance(value, dict):
            value.clear()
        if connection is not None:
            connection.close()


def configure_schema(vault, metadata):
    password = None
    connection = None
    try:
        password = vault.read(ROLES[0], metadata[ROLES[0]]['secret_revision'])
        connection = connect_local(role=ROLES[0], password=password, database=DATABASE)
        password = None
        with connection.transaction():
            connection.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        # Only this newly created database; no schema/table in any other DB.
        with connection.transaction():
            connection.execute('SET TRANSACTION READ ONLY')
            if connection.execute("SELECT current_database(),current_user").fetchone() != (DATABASE, ROLES[0]):
                raise LocalDatabaseError('owner_identity_verification_failed')
            if not connection.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0]:
                raise LocalDatabaseError('owner_schema_verification_failed')
            if connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname!='information_schema'").fetchone()[0] != 0:
                raise LocalDatabaseError('unexpected_application_objects')
    finally:
        password = None
        if connection is not None:
            connection.close()
    connection = None
    try:
        password = vault.read(ROLES[1], metadata[ROLES[1]]['secret_revision'])
        connection = connect_local(role=ROLES[1], password=password, database=DATABASE, readonly=True)
        password = None
        with connection.transaction():
            row = connection.execute("SELECT current_database(),current_user,"
                "has_database_privilege(current_user,current_database(),'CONNECT'),"
                "has_database_privilege(current_user,current_database(),'CREATE'),"
                "has_database_privilege(current_user,current_database(),'TEMP'),"
                "has_schema_privilege(current_user,'public','CREATE'),"
                "EXISTS(SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_temp_%' "
                "AND has_schema_privilege(current_user,oid,'CREATE'))").fetchone()
            if row != (DATABASE, ROLES[1], True, False, False, False, False):
                raise LocalDatabaseError('runner_privileges_verification_failed')
    finally:
        password = None
        if connection is not None:
            connection.close()


def initialize(admin, vault, confirm, *, schema_check=configure_schema):
    """Dependency-injected for offline tests. Never invoke on import.

    Statuses are attempted/completed: a lost commit response is not evidence
    that an object is absent. No compensation DROP/delete or blind rerun.
    """
    result = {'success': False, 'steps': {}, 'database_credentials': {}, 'automatic_cleanup': False}
    passwords = {}
    step = 'precheck'
    try:
        admin.precheck()
        if any(vault.exists(role) for role in ROLES):
            raise LocalDatabaseError('credential_already_exists')
        if not confirm(CONFIRMATION):
            result['safe_code'] = 'cancelled_no_changes'
            return result
        admin.lock()
        admin.precheck()
        if any(vault.exists(role) for role in ROLES):
            raise LocalDatabaseError('credential_already_exists')
        admin.protect_sql_logs()
        passwords = new_passwords()
        for role in ROLES:
            step = 'credential_' + role
            result['steps'][step] = 'attempted'
            revision = vault.write_new(role, passwords[role])
            if vault.read(role, revision) != passwords[role]:
                raise LocalDatabaseError('credential_readback_failed')
            result['database_credentials'][role] = {'role': role, 'secret_ref': REFS[role], 'secret_revision': revision}
            result['steps'][step] = 'completed'
        for role in ROLES:
            step = 'role_' + role
            result['steps'][step] = 'attempted'
            admin.create_role(role, passwords.pop(role))
            result['steps'][step] = 'completed'
        step = 'database'
        result['steps'][step] = 'attempted'
        admin.create_database()
        result['steps'][step] = 'completed'
        step = 'database_acl'
        result['steps'][step] = 'attempted'
        admin.database_acl()
        result['steps'][step] = 'completed'
        step = 'schema_and_validation'
        result['steps'][step] = 'attempted'
        schema_check(vault, result['database_credentials'])
        admin.verify_catalogs()
        result['steps'][step] = 'completed'
        result['success'] = True
    except BaseException:
        # Never serialize exception text, SQL, traceback, passwords or verifier.
        result['safe_code'] = 'initialization_stopped'
        result['stopped_at'] = step
        result['instruction'] = '保留现状；不要重试、删库、删角色或删除凭据。先人工核验 attempted/completed 状态。'
    finally:
        passwords.clear()
    return result
