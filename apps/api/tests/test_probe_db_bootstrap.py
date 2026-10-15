"""All DB adapters are fake. Never read recovery/real keys or create SQL objects."""
from contextlib import nullcontext
import ctypes
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import probe_db_bootstrap as boot
from app import probe_db_credentials as cred

FAKE = 'PUBLIC_FAKE_DATABASE_PASSWORD_ONLY_' + 'x' * 32


@pytest.fixture(autouse=True)
def prohibit_real_connections(monkeypatch):
    monkeypatch.setattr(cred.psycopg, 'connect', Mock(side_effect=AssertionError('real DB prohibited')))


class FakeVault:
    def __init__(self):
        self.values = {}
        self.calls = []

    def exists(self, role):
        self.calls.append(('exists', role))
        return role in self.values

    def write_new(self, role, password):
        assert role not in self.values
        self.calls.append(('write', role))
        self.values[role] = password
        return 123

    def read(self, role, revision):
        assert revision == 123
        self.calls.append(('read', role))
        return self.values[role]


class FakeAdmin:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def step(self, name):
        self.calls.append(name)
        if name == self.failure:
            raise ValueError(FAKE + ' sensitive driver details')

    def precheck(self): self.step('precheck')
    def lock(self): self.step('lock')
    def protect_sql_logs(self): self.step('logs')
    def create_role(self, role, password):
        assert len(password) >= 43
        self.step(role)
    def create_database(self): self.step('database')
    def database_acl(self): self.step('acl')
    def verify_catalogs(self): self.step('verify')


def run(admin=None, vault=None, confirm=lambda _: True, schema=None):
    return boot.initialize(admin or FakeAdmin(), vault or FakeVault(), confirm,
        schema_check=schema or (lambda *_: None))


def test_rng_uses_32_os_random_bytes_per_role(monkeypatch):
    fn = Mock(side_effect=['A' * 43, 'B' * 43])
    monkeypatch.setattr(boot.secrets, 'token_urlsafe', fn)
    value = boot.new_passwords()
    assert fn.call_args_list[0].args == (32,)
    assert fn.call_args_list[1].args == (32,)
    assert value[cred.ROLES[0]] != value[cred.ROLES[1]]


def test_actual_csprng_shape_and_distinctness():
    values = [boot.new_passwords() for _ in range(16)]
    all_passwords = [v[r] for v in values for r in cred.ROLES]
    assert len(set(all_passwords)) == 32
    assert all(len(v) == 43 for v in all_passwords)


def test_broken_rng_stops(monkeypatch):
    monkeypatch.setattr(boot.secrets, 'token_urlsafe', lambda _: FAKE)
    admin, vault = FakeAdmin(), FakeVault()
    result = run(admin, vault)
    assert not result['success'] and not vault.values
    assert not any(r in admin.calls for r in cred.ROLES)


def test_success_saves_both_before_roles_and_only_safe_metadata(capsys, caplog):
    admin, vault = FakeAdmin(), FakeVault()
    def confirmed(phrase):
        assert phrase == boot.CONFIRMATION
        assert not vault.values and admin.calls == ['precheck']
        return True
    original = admin.create_role
    def create(role, password):
        assert set(vault.values) == set(cred.ROLES)
        original(role, password)
    admin.create_role = create
    result = run(admin, vault, confirmed)
    assert result['success']
    assert admin.calls == ['precheck','lock','precheck','logs',*cred.ROLES,'database','acl','verify']
    assert all(v not in json.dumps(result) + capsys.readouterr().out + caplog.text for v in vault.values.values())
    assert all(set(v) == {'role','secret_ref','secret_revision'} for v in result['database_credentials'].values())


def test_cancel_has_no_mutations():
    admin, vault = FakeAdmin(), FakeVault()
    result = run(admin, vault, lambda _: False)
    assert result['safe_code'] == 'cancelled_no_changes'
    assert admin.calls == ['precheck'] and not vault.values


@pytest.mark.parametrize('failure', ['precheck','lock','logs',*cred.ROLES,'database','acl','verify'])
def test_partial_failure_is_safe_and_never_cleans_or_retries(failure, caplog, capsys):
    admin, vault = FakeAdmin(failure), FakeVault()
    result = run(admin, vault)
    assert not result['success'] and not result['automatic_cleanup']
    assert failure in admin.calls
    assert all('drop' not in str(v).lower() and 'delete' not in str(v).lower() for v in admin.calls + vault.calls)
    if failure in (*cred.ROLES,'database','acl','verify'):
        assert set(vault.values) == set(cred.ROLES)
    output = json.dumps(result) + caplog.text + capsys.readouterr().out
    assert FAKE not in output and 'sensitive driver details' not in output


def test_credentials_already_present_stop_before_confirmation():
    admin, vault, confirm = FakeAdmin(), FakeVault(), Mock()
    vault.values[cred.ROLES[1]] = FAKE
    assert not run(admin, vault, confirm)['success']
    confirm.assert_not_called()
    assert admin.calls == ['precheck']


def test_recheck_failure_after_confirmation_does_not_write():
    admin, vault = FakeAdmin(), FakeVault()
    def precheck():
        admin.calls.append('precheck')
        if len(admin.calls) > 1:
            raise RuntimeError(FAKE)
    admin.precheck = precheck
    assert not run(admin, vault)['success'] and not vault.values


def test_vault_write_unknown_keeps_attempted_state():
    vault = FakeVault()
    def fail(role, password):
        vault.values[role] = password
        raise RuntimeError(FAKE)
    vault.write_new = fail
    admin = FakeAdmin()
    result = run(admin, vault)
    assert result['steps']['credential_' + cred.ROLES[0]] == 'attempted'
    assert cred.ROLES[0] in vault.values
    assert not any(r in admin.calls for r in cred.ROLES)


def test_readback_mismatch_stops_before_sql():
    vault, admin = FakeVault(), FakeAdmin()
    vault.read = lambda *_: 'wrong'
    assert not run(admin, vault)['success']
    assert not any(r in admin.calls for r in cred.ROLES)


class FakeConnection:
    def __init__(self, answers=()):
        self.answers = iter(answers)
        self.statements = []
        self.autocommit = False
        self.pgconn = SimpleNamespace(encrypt_password=Mock(return_value=b'SCRAM-SHA-256$PUBLIC_FAKE_VERIFIER'))
        self.closed = False
    def transaction(self): return nullcontext()
    def execute(self, query, *args):
        self.statements.append(query.as_string(None) if hasattr(query, 'as_string') else query)
        return self
    def fetchone(self): return next(self.answers)
    def fetchall(self): return next(self.answers)
    def commit(self): pass
    def close(self): self.closed = True


def test_native_libpq_scram_not_cleartext_sql():
    c = FakeConnection()
    boot.LocalPostgresAdmin(c).create_role(cred.ROLES[0], FAKE)
    c.pgconn.encrypt_password.assert_called_once_with(FAKE.encode(),cred.ROLES[0].encode(),b'scram-sha-256')
    statement = c.statements[0]
    assert FAKE not in statement and 'SCRAM-SHA-256$' in statement
    for required in ('LOGIN','NOSUPERUSER','NOCREATEDB','NOCREATEROLE','NOREPLICATION','NOBYPASSRLS','NOINHERIT'):
        assert required in statement


@pytest.mark.parametrize('role', ['postgres','pathwise_dev','custom'])
def test_role_target_guard(role):
    c = FakeConnection()
    with pytest.raises(cred.LocalDatabaseError): boot.LocalPostgresAdmin(c).create_role(role, FAKE)
    assert not c.statements


def test_database_no_user_template_and_no_public_connection_window():
    c = FakeConnection()
    admin = boot.LocalPostgresAdmin(c)
    admin.create_database()
    assert 'TEMPLATE template0 ALLOW_CONNECTIONS false' in c.statements[0] and not c.autocommit
    admin.database_acl()
    assert c.statements[1:] == ['REVOKE ALL ON DATABASE pathwise_probe FROM PUBLIC',
        'GRANT CONNECT ON DATABASE pathwise_probe TO pathwise_probe_owner,pathwise_probe_runner',
        'ALTER DATABASE pathwise_probe ALLOW_CONNECTIONS true']
    assert 'pathwise_dev' not in '\n'.join(c.statements)


@pytest.mark.parametrize('existing', [(True,False,False),(False,True,False),(False,False,True)])
def test_existing_database_or_each_role_refuses(existing):
    c = FakeConnection([('postgres','postgres',True,True,True,160015), existing])
    with pytest.raises(cred.LocalDatabaseError): boot.LocalPostgresAdmin(c).precheck()
    assert all(s.startswith(('SELECT','SET TRANSACTION')) for s in c.statements)


@pytest.mark.parametrize('identity', [
    ('pathwise_dev','postgres',True,True,True,160015),
    ('postgres','other',True,True,True,160015),
    ('postgres','postgres',False,True,True,160015),
    ('postgres','postgres',True,True,True,170000)])
def test_identity_permissions_version_refuse(identity):
    c = FakeConnection([identity])
    with pytest.raises(cred.LocalDatabaseError): boot.LocalPostgresAdmin(c).precheck()


def test_unknown_audit_hooks_refuse():
    c = FakeConnection([('postgres','postgres',True,True,True,160015),(False,False,False),('pgaudit','','')])
    with pytest.raises(cred.LocalDatabaseError): boot.LocalPostgresAdmin(c).precheck()


@pytest.mark.parametrize('database,role', [('pathwise_dev','postgres'),('postgres',cred.ROLES[0]),('elsewhere','postgres')])
def test_connect_target_guard(database,role):
    with pytest.raises(cred.LocalDatabaseError): cred.connect_local(database=database,role=role,password=FAKE)


def test_connect_exact_host_scram_and_no_environment(monkeypatch):
    fn = Mock(return_value=object())
    monkeypatch.setattr(cred.psycopg,'connect',fn)
    monkeypatch.setenv('PGHOSTADDR','evil.example')
    def connect(**kw):
        assert 'PGHOSTADDR' not in cred.os.environ
        assert kw['host'] == kw['hostaddr'] == '127.0.0.1'
        assert kw['port'] == 5432 and kw['require_auth'] == 'scram-sha-256'
        return object()
    fn.side_effect = connect
    cred.connect_local(role=cred.ROLES[1],password=FAKE,database='pathwise_probe')
    assert cred.os.environ['PGHOSTADDR'] == 'evil.example'


def metadata(role): return {'role':role,'secret_ref':cred.REFS[role],'secret_revision':123}


@pytest.mark.parametrize('changes', [dict(role='postgres'),dict(secret_ref='Pathwise/DeepSeek/foo'),
    dict(secret_revision=0),dict(secret_revision=True),dict(host='other'),dict(password=FAKE)])
def test_secret_config_strict(changes):
    with pytest.raises(cred.LocalDatabaseError): cred.secret_config(metadata(cred.ROLES[1]) | changes,expected_role=cred.ROLES[1])


def test_lazy_engine_and_role_binding(monkeypatch):
    vault = Mock()
    vault.read.return_value = FAKE
    monkeypatch.setattr(cred,'WindowsDatabaseVault',lambda: vault)
    created = Mock()
    monkeypatch.setattr(cred,'create_engine',created)
    fn = Mock(return_value=object())
    monkeypatch.setattr(cred,'connect_local',fn)
    cred.credential_engine(metadata(cred.ROLES[1]),expected_role=cred.ROLES[1])
    vault.read.assert_not_called()
    assert created.call_args.args == ('postgresql+psycopg://',)
    created.call_args.kwargs['creator']()
    vault.read.assert_called_once_with(cred.ROLES[1],123)
    assert fn.call_args.kwargs == {'role':cred.ROLES[1],'password':FAKE,'database':'pathwise_probe'}
    with pytest.raises(cred.LocalDatabaseError): cred.credential_engine(metadata(cred.ROLES[0]),expected_role=cred.ROLES[1])


def load_cli(name):
    import sys
    path = Path(__file__).parents[3] / 'scripts' / name
    if str(path.parent) not in sys.path:
        sys.path.insert(0,str(path.parent))
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_noninteractive_never_reads_recovery_or_vault(monkeypatch,capsys):
    cli = load_cli('initialize_probe_database.py')
    monkeypatch.setattr(cli.sys,'argv',['initialize_probe_database.py'])
    monkeypatch.setattr(cli.sys,'stdin',SimpleNamespace(isatty=lambda: False))
    reader = Mock(side_effect=AssertionError('secret must not be read'))
    monkeypatch.setattr(cli,'recovery_admin',reader)
    monkeypatch.setattr(cli,'WindowsDatabaseVault',reader)
    assert cli.main() == 2
    reader.assert_not_called()
    assert 'interactive_windows_terminal_required' in capsys.readouterr().out


def test_native_vault_fake_api_roundtrip_and_no_overwrite(monkeypatch):
    # Actual ctypes buffer and native wrapper; Fake API only, never CredReadW.
    store = {}
    buffers = []
    last_error = [1168]
    class API:
        def CredReadW(self,target,kind,flags,out):
            if target not in store:
                last_error[0]=1168
                return False
            c = cred.Credential()
            c.Type=1;c.TargetName=target;c.UserName=store[target][0]
            blob=ctypes.create_string_buffer(store[target][1]);buffers.append(blob)
            c.CredentialBlob=ctypes.cast(blob,ctypes.POINTER(ctypes.c_byte))
            c.CredentialBlobSize=len(store[target][1]);c.LastWritten.dwLowDateTime=123
            buffers.append(c)
            ctypes.cast(out,ctypes.POINTER(ctypes.POINTER(cred.Credential)))[0]=ctypes.pointer(c)
            return True
        def CredWriteW(self,p,flags):
            c=ctypes.cast(p,ctypes.POINTER(cred.Credential)).contents
            assert c.Persist==2 and c.Type==1
            store[c.TargetName]=(c.UserName,ctypes.string_at(c.CredentialBlob,c.CredentialBlobSize))
            return True
        def CredFree(self,p): pass
    monkeypatch.setattr(ctypes,'get_last_error',lambda:last_error[0],raising=False)
    v=object.__new__(cred.WindowsDatabaseVault);v.api=API()
    assert not v.exists(cred.ROLES[0])
    assert v.write_new(cred.ROLES[0],FAKE)==123
    assert v.read(cred.ROLES[0],123)==FAKE
    assert v.metadata(cred.ROLES[0])==metadata(cred.ROLES[0])
    with pytest.raises(cred.LocalDatabaseError):v.write_new(cred.ROLES[0],FAKE)
    with pytest.raises(cred.LocalDatabaseError):v.read(cred.ROLES[0],124)
    with pytest.raises(cred.LocalDatabaseError):v.exists('postgres')
    assert len(store)==1 and all(not any(blob.raw) for blob in buffers if isinstance(blob,ctypes.Array))


def test_schema_only_new_database_and_runner_login(monkeypatch):
    owner=FakeConnection([('pathwise_probe',cred.ROLES[0]),(True,),(0,)])
    runner=FakeConnection([('pathwise_probe',cred.ROLES[1],True,False,False,False,False)])
    connect=Mock(side_effect=[owner,runner]);monkeypatch.setattr(boot,'connect_local',connect)
    vault=FakeVault();vault.values={r:FAKE for r in cred.ROLES}
    boot.configure_schema(vault,{r:metadata(r) for r in cred.ROLES})
    assert owner.closed and runner.closed
    assert all(c.kwargs['database']=='pathwise_probe' for c in connect.call_args_list)
    assert owner.statements[0]=='REVOKE CREATE ON SCHEMA public FROM PUBLIC'
    assert 'pathwise_dev' not in '\n'.join(owner.statements+runner.statements)


def test_catalog_verification_all_restricted_flags_and_public():
    roles=[(r,True,False,False,False,False,False,False,False) for r in cred.ROLES]
    c=FakeConnection([(cred.ROLES[0],True,True),roles])
    boot.LocalPostgresAdmin(c).verify_catalogs()
    assert 'aclexplode' in c.statements[1] and 'pg_auth_members' in c.statements[2]


@pytest.mark.parametrize('database_result', [(cred.ROLES[0],True,False),('postgres',True,True),(cred.ROLES[0],False,True)])
def test_wrong_database_acl_fails_verification(database_result):
    with pytest.raises(cred.LocalDatabaseError):boot.LocalPostgresAdmin(FakeConnection([database_result])).verify_catalogs()


@pytest.mark.parametrize('flag', range(1,9))
def test_each_role_privilege_drift_fails(flag):
    rows=[list((r,True,False,False,False,False,False,False,False)) for r in cred.ROLES]
    rows[1][flag]=not rows[1][flag]
    c=FakeConnection([(cred.ROLES[0],True,True),[tuple(r) for r in rows]])
    with pytest.raises(cred.LocalDatabaseError):boot.LocalPostgresAdmin(c).verify_catalogs()


def test_schema_failure_preserves_credentials():
    admin,vault=FakeAdmin(),FakeVault()
    def failed(*_):raise RuntimeError(FAKE)
    result=run(admin,vault,schema=failed)
    assert not result['success'] and result['stopped_at']=='schema_and_validation'
    assert len(vault.values)==2 and result['steps']['database']=='completed'


@pytest.mark.parametrize('changes', [dict(admin_user='pathwise_dev'),dict(port=5433),dict(admin_password=''),dict(port='5432')])
def test_recovery_rejects_changed_identity_before_connect(tmp_path,monkeypatch,changes):
    from app import probe_preview
    monkeypatch.setattr(probe_preview,'_acl',lambda *_:None)
    path=tmp_path/'fake-recovery.json'
    path.write_text(json.dumps(dict(admin_user='postgres',port=5432,admin_password=FAKE)|changes))
    fn=Mock();monkeypatch.setattr(boot,'connect_local',fn)
    with pytest.raises(cred.LocalDatabaseError):
        with boot.recovery_admin(path):pass
    fn.assert_not_called()


def test_recovery_only_local_maintenance_and_close(tmp_path,monkeypatch):
    from app import probe_preview
    monkeypatch.setattr(probe_preview,'_acl',lambda *_:None)
    path=tmp_path/'fake-recovery.json'
    path.write_text(json.dumps(dict(admin_user='postgres',port=5432,admin_password=FAKE)))
    c=FakeConnection();fn=Mock(return_value=c);monkeypatch.setattr(boot,'connect_local',fn)
    with boot.recovery_admin(path) as admin:assert admin.connection is c
    assert c.closed
    assert fn.call_args.kwargs==dict(role='postgres',password=FAKE,database='postgres')


@pytest.mark.parametrize('script,command', [('setup_probe_ledger.py',None),('controlled_live_probe.py','report')])
def test_secret_config_cli_compatibility_no_actual_connections(script,command,tmp_path,monkeypatch,capsys):
    import sys
    cli=load_cli(script)
    value={'database_credential':metadata(cred.ROLES[0] if command is None else cred.ROLES[1])}
    if command:value['ledger_id']='11111111-1111-4111-8111-111111111111'
    path=tmp_path/'config.json';path.write_text(json.dumps(value))
    args=[script,command,'--config',str(path)] if command else [script,'--owner-config',str(path),'--runtime-role',cred.ROLES[1]]
    monkeypatch.setattr(sys,'argv',args)
    engine=Mock()
    engine.connect.side_effect=RuntimeError(FAKE)
    created=Mock(return_value=engine);monkeypatch.setattr(cli,'credential_engine',created)
    if command:
        control=Mock();control.report.return_value={'state':'approved'}
        monkeypatch.setattr(cli,'ExperimentControl',lambda *_:control)
        monkeypatch.setattr(cli,'operator_preview_store',lambda:None)
        assert cli.main()==0
    else:
        monkeypatch.setattr(cli,'confirmation',lambda *_:None)
        assert cli.main()==2
    assert created.call_args.kwargs['expected_role']==value['database_credential']['role']
    assert FAKE not in capsys.readouterr().out
    engine.dispose.assert_called_once()


def test_credential_status_never_reads_admin_or_database(monkeypatch,capsys):
    import sys
    cli=load_cli('initialize_probe_database.py')
    monkeypatch.setattr(sys,'argv',['initialize_probe_database.py','--credential-status'])
    cli.os=SimpleNamespace(name='nt')
    cli.sys=SimpleNamespace(stdin=SimpleNamespace(isatty=lambda:True),stdout=SimpleNamespace(isatty=lambda:True))
    monkeypatch.setattr(cli,'local_private_io',nullcontext)
    monkeypatch.setattr(cli,'initialization_mutex',nullcontext)
    reader=Mock(side_effect=AssertionError('must not read admin'))
    monkeypatch.setattr(cli,'recovery_admin',reader)
    vault=Mock();vault.metadata.side_effect=lambda r:metadata(r)
    monkeypatch.setattr(cli,'WindowsDatabaseVault',lambda:vault)
    assert cli.main()==0
    reader.assert_not_called()
    assert vault.metadata.call_count==2 and FAKE not in capsys.readouterr().out
