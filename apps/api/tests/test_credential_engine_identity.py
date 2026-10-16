"""Real Engine + real check_role, fake SQL IO only. No credentials or DB."""
from dataclasses import dataclass, field, replace
import socket
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app import probe_db_credentials as credentials
from app.controlled_probe import ExperimentControl
from app.deepseek_contract import ProbeError

RUNNER = 'pathwise_probe_runner'
OWNER = 'pathwise_probe_owner'
LEDGER = '00000000-0000-4000-8000-000000000001'
SCHEMA = 'test_' + 'a' * 32


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    guards = []
    for target, name in ((credentials, 'WindowsDatabaseVault'),
                         (credentials, 'connect_local'),
                         (credentials.psycopg, 'connect'),
                         (socket, 'socket'), (socket, 'getaddrinfo')):
        guard = Mock(side_effect=AssertionError('offline test attempted external IO'))
        monkeypatch.setattr(target, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


@dataclass
class Session:
    database: str = 'pathwise_probe'
    current_user: str = RUNNER
    session_user: str = RUNNER
    address: str | None = '127.0.0.1'
    port: int | None = 5432
    denied_privileges: set = field(default_factory=set)


class FakeConnection:
    def __init__(self, session):
        self.session = session
        self.queries = []
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.exited = True

    def execute(self, statement):
        sql = str(statement)
        assert sql == ('SELECT current_database(),current_user,session_user,'
                       'host(inet_server_addr()),inet_server_port()')
        self.queries.append(('identity', sql))
        s = self.session
        return type('Rows', (), {'one': lambda _: (
            s.database, s.current_user, s.session_user, s.address, s.port)})()

    def scalar(self, statement, parameters):
        sql = str(statement)
        # Preserve the actual permission-query coverage, not a blanket True.
        for clause in ('current_user=session_user', 'r.rolsuper', 'r.rolcreatedb',
                       'r.rolcreaterole', 'r.rolbypassrls', 'pg_auth_members',
                       'has_database_privilege', 'has_schema_privilege',
                       'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER'):
            assert clause in sql
        assert set(parameters) == {'s'}
        self.queries.append(('privileges', parameters['s']))
        return not self.session.denied_privileges


def metadata(role=RUNNER):
    return dict(role=role, secret_ref=credentials.REFS[role], secret_revision=123)


def check(monkeypatch, session=None, *, role=RUNNER, url=None,
          live=True, schema='public', expected_error=None):
    creator = Mock(side_effect=AssertionError('creator must not run'))
    engine = (credentials.credential_engine(metadata(role), expected_role=role)
              if url is None else create_engine(url, creator=creator, hide_parameters=True))
    connection = FakeConnection(session or Session())
    connect = Mock(return_value=connection)
    monkeypatch.setattr(engine, 'connect', connect)
    try:
        control = ExperimentControl(engine, schema, LEDGER)
        if expected_error:
            with pytest.raises(ProbeError, match='^' + expected_error + '$'):
                control.check_role(live=live)
        else:
            control.check_role(live=live)
        creator.assert_not_called()
        return connection, connect.call_count
    finally:
        engine.dispose()


@pytest.mark.parametrize('role', [OWNER, RUNNER])
def test_engine_real_url_metadata_is_complete_passwordless_and_lazy(role):
    engine = credentials.credential_engine(metadata(role), expected_role=role)
    try:
        u = engine.url
        assert (u.drivername, u.username, u.host, u.port, u.database) == (
            'postgresql+psycopg', role, '127.0.0.1', 5432, 'pathwise_probe')
        assert u.password is None and not u.query
        assert '123' not in str(u) and 'Pathwise/' not in str(u)
    finally:
        engine.dispose()


def test_secretref_runner_passes_real_checker_same_connection(monkeypatch):
    connection, calls = check(monkeypatch)
    assert calls == 1 and connection.exited
    assert [q[0] for q in connection.queries] == ['identity', 'privileges']
    assert connection.queries[1][1] == 'public'


@pytest.mark.parametrize('privilege', ['superuser', 'createdb', 'createrole',
    'bypassrls', 'membership', 'database_create', 'persistent_schema_create',
    'table_insert', 'table_update', 'table_delete', 'table_truncate', 'table_trigger'])
def test_existing_privilege_rejections_still_run(monkeypatch, privilege):
    connection, calls = check(monkeypatch, Session(denied_privileges={privilege}),
        expected_error='controlled_restricted_login_required')
    assert calls == 1 and connection.exited
    assert [q[0] for q in connection.queries] == ['identity', 'privileges']


@pytest.mark.parametrize('session', [
    Session(database='pathwise_dev'), Session(database='postgres'),
    Session(database='pathwise_test'), Session(current_user=OWNER),
    Session(session_user=OWNER), Session(current_user='postgres', session_user='postgres'),
    Session(current_user='other', session_user='other'),
    Session(address='::1'), Session(address='192.0.2.1'), Session(address=None),
    Session(port=5433), Session(port=None)])
def test_actual_live_identity_mismatch_is_rejected(monkeypatch, session):
    connection, calls = check(monkeypatch, session,
        expected_error='controlled_session_identity_mismatch')
    assert calls == 1 and connection.exited
    assert [q[0] for q in connection.queries] == ['identity']


@pytest.mark.parametrize('role', [OWNER, 'postgres', 'other_restricted'])
def test_live_non_runner_rejected_even_if_url_and_login_agree(monkeypatch, role):
    u = URL.create('postgresql+psycopg', username=role, host='127.0.0.1',
        database='pathwise_probe', port=5432)
    check(monkeypatch, Session(current_user=role, session_user=role), url=u,
          expected_error='controlled_session_identity_mismatch')


@pytest.mark.parametrize('changes,error', [
    ({'host':'remote.invalid'}, 'controlled_local_database_required'),
    ({'host':None}, 'controlled_local_database_required'),
    ({'database':'pathwise_dev'}, 'controlled_live_database_required'),
    ({'port':5433}, 'controlled_live_database_required')])
def test_url_rejection_still_happens_before_connect(monkeypatch, changes, error):
    u = URL.create('postgresql+psycopg', username=RUNNER, host='127.0.0.1',
        database='pathwise_probe', port=5432).set(**changes)
    # URL.set(host=None) retains the old value; construct an actually empty host.
    if 'host' in changes and changes['host'] is None:
        u = URL.create('postgresql+psycopg', username=RUNNER,
                       database='pathwise_probe', port=5432)
    connection, calls = check(monkeypatch, url=u, expected_error=error)
    assert calls == 0 and not connection.queries


@pytest.mark.parametrize('host,port', [('localhost', None), ('127.0.0.1', 5432)])
def test_legacy_valid_runner_url_works(monkeypatch, host, port):
    u = URL.create('postgresql+psycopg', username=RUNNER, host=host,
                   port=port, database='pathwise_probe')
    connection, calls = check(monkeypatch, url=u)
    assert calls == 1 and len(connection.queries) == 2


def test_live_missing_declared_login_rejected(monkeypatch):
    u = URL.create('postgresql+psycopg', host='127.0.0.1', database='pathwise_probe')
    check(monkeypatch, url=u, expected_error='controlled_session_identity_mismatch')


def test_existing_password_bearing_legacy_url_still_checks_actual_runner(monkeypatch):
    u = URL.create('postgresql+psycopg', username=RUNNER,
        password='PUBLIC_FAKE_DATABASE_PASSWORD', host='localhost', database='pathwise_probe')
    connection, calls = check(monkeypatch, url=u)
    assert calls == 1 and connection.queries[-1] == ('privileges', 'public')


def test_live_wrong_schema_still_rejected_before_connect(monkeypatch):
    connection, calls = check(monkeypatch, schema='other',
        expected_error='controlled_live_database_required')
    assert calls == 0 and not connection.queries


def test_each_check_validates_the_connection_it_obtains(monkeypatch):
    engine = credentials.credential_engine(metadata(), expected_role=RUNNER)
    good = FakeConnection(Session())
    bad = FakeConnection(Session(database='pathwise_dev'))
    connect = Mock(side_effect=[good, bad])
    monkeypatch.setattr(engine, 'connect', connect)
    try:
        control = ExperimentControl(engine, 'public', LEDGER)
        control.check_role(live=True)
        with pytest.raises(ProbeError, match='^controlled_session_identity_mismatch$'):
            control.check_role(live=True)
        assert connect.call_count == 2
        assert good.exited and bad.exited
        assert [q[0] for q in bad.queries] == ['identity']
    finally:
        engine.dispose()


@pytest.mark.parametrize('database', ['pathwise_test', 'pathwise_e2e'])
@pytest.mark.parametrize('schema', [SCHEMA, 'test_eval_' + 'b' * 32])
@pytest.mark.parametrize('host,address,port', [
    ('127.0.0.1','127.0.0.1',5432), ('127.0.0.1','127.0.0.1',35432),
    ('localhost','127.0.0.1',5432), ('localhost','::1',5432)])
def test_offline_isolation_keeps_random_logins_schemas_and_ports(
        monkeypatch, database, schema, host, address, port):
    role = 'controlled_test_' + 'c' * 32
    u = URL.create('postgresql+psycopg', username=role, host=host,
                   port=port, database=database)
    s = Session(database=database, current_user=role, session_user=role,
                address=address, port=port)
    connection, calls = check(monkeypatch, s, url=u, live=False, schema=schema)
    assert calls == 1 and connection.queries[1] == ('privileges', schema)


@pytest.mark.parametrize('address,client_port,server_port', [
    ('172.18.0.2',5432,5432), ('172.17.0.2',15432,5432),
    ('fd00::2',35432,15432)])
def test_offline_container_forwarding_preserves_existing_isolation(
        monkeypatch,address,client_port,server_port):
    u = URL.create('postgresql+psycopg', username='test_runner',
        host='127.0.0.1',port=client_port,database='pathwise_test')
    s = Session(database='pathwise_test',current_user='test_runner',
                session_user='test_runner',address=address,port=server_port)
    connection,calls = check(monkeypatch,s,url=u,live=False,schema=SCHEMA)
    assert calls == 1 and connection.queries[1] == ('privileges',SCHEMA)


def test_live_never_accepts_container_forwarding(monkeypatch):
    check(monkeypatch,Session(address='172.18.0.2'),
          expected_error='controlled_session_identity_mismatch')


@pytest.mark.parametrize('database,schema', [
    ('pathwise_probe',SCHEMA), ('pathwise_dev',SCHEMA),
    ('pathwise_test','public'), ('pathwise_e2e','test_bad')])
def test_offline_database_or_schema_guard_not_relaxed(monkeypatch, database, schema):
    u = URL.create('postgresql+psycopg', username='test_runner',
                   host='127.0.0.1', database=database)
    connection, calls = check(monkeypatch, url=u, live=False, schema=schema,
        expected_error='controlled_test_database_required')
    assert calls == 0 and not connection.queries


@pytest.mark.parametrize('changes', [dict(database='pathwise_e2e'),
    dict(current_user='different'), dict(session_user='different')])
def test_offline_actual_session_must_match_declared_target(monkeypatch, changes):
    u = URL.create('postgresql+psycopg', username='test_runner',
        host='127.0.0.1', database='pathwise_test', port=5432)
    s = replace(Session(), database='pathwise_test',
                current_user='test_runner', session_user='test_runner')
    check(monkeypatch, replace(s, **changes), url=u, live=False, schema=SCHEMA,
          expected_error='controlled_session_identity_mismatch')


@pytest.mark.parametrize('changes', [dict(role=OWNER), dict(secret_ref='wrong'),
    dict(secret_revision=0), dict(secret_revision=True), dict(secret_revision='123')])
def test_invalid_secretref_metadata_fails_without_io(changes):
    with pytest.raises(credentials.LocalDatabaseError):
        credentials.credential_engine(metadata() | changes, expected_role=RUNNER)


def test_stale_positive_revision_is_rejected_before_database_connection(monkeypatch):
    vault = Mock()
    vault.read.side_effect = credentials.LocalDatabaseError('credential_missing_or_rotated')
    monkeypatch.setattr(credentials, 'WindowsDatabaseVault', lambda: vault)
    created = Mock()
    monkeypatch.setattr(credentials, 'create_engine', created)
    credentials.credential_engine(metadata() | {'secret_revision': 124}, expected_role=RUNNER)
    vault.read.assert_not_called()
    with pytest.raises(credentials.LocalDatabaseError, match='^credential_missing_or_rotated$'):
        created.call_args.kwargs['creator']()
    vault.read.assert_called_once_with(RUNNER, 124)
