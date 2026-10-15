"""Local probe DB credentials only. Never imported by Web/API startup."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import logging
import os

from sqlalchemy import create_engine
import psycopg

ROLES = ('pathwise_probe_owner', 'pathwise_probe_runner')
REFS = {role: 'Pathwise/PostgreSQL/127.0.0.1:5432/pathwise_probe/' + role for role in ROLES}


class LocalDatabaseError(Exception):
    """Only fixed safe codes may cross the operator boundary."""


@contextmanager
def local_private_io():
    """One-shot operator process only: no inherited libpq targets or logging."""
    previous = logging.root.manager.disable
    saved = {k: v for k, v in os.environ.items() if k.upper().startswith('PG')}
    logging.disable(logging.CRITICAL)
    for key in saved:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        os.environ.update(saved)
        logging.disable(previous)


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


class WindowsDatabaseVault:
    """Exact two targets, never CredEnumerate. Caller must hold the init mutex.

    CredWrite has no atomic create-if-absent flag: cooperative processes are
    serialized; hostile code under the same Windows user remains trusted.
    """
    def __init__(self):
        if os.name != 'nt':
            raise LocalDatabaseError('windows_required')
        self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    @contextmanager
    def _entry(self, role):
        if role not in REFS:
            raise LocalDatabaseError('credential_target_rejected')
        ptr = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(REFS[role], 1, 0, ctypes.byref(ptr)):
            if ctypes.get_last_error() != 1168:
                raise LocalDatabaseError('credential_access_failed')
            yield None
            return
        try:
            if ptr.contents.Type != 1 or ptr.contents.TargetName != REFS[role] or ptr.contents.UserName != role:
                raise LocalDatabaseError('credential_binding_invalid')
            yield ptr.contents
        finally:
            if ptr.contents.CredentialBlob:
                ctypes.memset(ptr.contents.CredentialBlob, 0, ptr.contents.CredentialBlobSize)
            self.api.CredFree(ptr)

    def exists(self, role):
        with self._entry(role) as entry:
            return entry is not None

    def metadata(self, role):
        with self._entry(role) as entry:
            if entry is None:
                return None
            return {'role': role, 'secret_ref': REFS[role], 'secret_revision':
                entry.LastWritten.dwHighDateTime << 32 | entry.LastWritten.dwLowDateTime}

    def read(self, role, revision):
        with self._entry(role) as entry:
            if (entry is None or (entry.LastWritten.dwHighDateTime << 32 |
                entry.LastWritten.dwLowDateTime) != revision or
                not 64 <= entry.CredentialBlobSize <= 256):
                raise LocalDatabaseError('credential_missing_or_rotated')
            value = ctypes.string_at(entry.CredentialBlob, entry.CredentialBlobSize).decode('utf-16-le')
            if len(value) < 43 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in value):
                raise LocalDatabaseError('credential_format_invalid')
            return value

    def write_new(self, role, password):
        if self.exists(role):
            raise LocalDatabaseError('credential_already_exists')
        blob = ctypes.create_string_buffer(password.encode('utf-16-le'))
        try:
            entry = Credential(Type=1, TargetName=REFS[role], UserName=role, Persist=2,
                CredentialBlobSize=len(password.encode('utf-16-le')),
                CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte)))
            if not self.api.CredWriteW(ctypes.byref(entry), 0):
                raise LocalDatabaseError('credential_write_failed')
            with self._entry(role) as readback:
                if readback is None:
                    raise LocalDatabaseError('credential_readback_failed')
                revision = readback.LastWritten.dwHighDateTime << 32 | readback.LastWritten.dwLowDateTime
            if self.read(role, revision) != password:
                raise LocalDatabaseError('credential_readback_failed')
            return revision
        finally:
            ctypes.memset(blob, 0, ctypes.sizeof(blob))


@contextmanager
def initialization_mutex():
    if os.name != 'nt':
        raise LocalDatabaseError('windows_required')
    api = ctypes.WinDLL('kernel32.dll', use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.ReleaseMutex.argtypes = [wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.CreateMutexW(None, False, 'Local\\PathwiseProbeDatabaseInitialization')
    acquired = False
    try:
        if not handle or api.WaitForSingleObject(handle, 0) != 0:
            raise LocalDatabaseError('initialization_busy_or_abandoned')
        acquired = True
        yield
    finally:
        if acquired:
            api.ReleaseMutex(handle)
        if handle:
            api.CloseHandle(handle)


def connect_local(*, role, password, database, readonly=False):
    if (role not in (*ROLES, 'postgres') or database not in ('postgres', 'pathwise_probe')
        or (database == 'postgres' and role != 'postgres')):
        raise LocalDatabaseError('database_target_rejected')
    with local_private_io():
        return psycopg.connect(host='127.0.0.1', hostaddr='127.0.0.1', port=5432,
            dbname=database, user=role, password=password, passfile=os.devnull,
            connect_timeout=5, require_auth='scram-sha-256', application_name='pathwise_probe_operator',
            options='-c statement_timeout=10000 -c lock_timeout=5000' +
                    (' -c default_transaction_read_only=on' if readonly else ''))


def secret_config(value, *, expected_role):
    if (not isinstance(value, dict) or set(value) != {'role', 'secret_ref', 'secret_revision'}
        or expected_role not in ROLES or value['role'] != expected_role
        or value['secret_ref'] != REFS[expected_role]
        or type(value['secret_revision']) is not int or value['secret_revision'] <= 0):
        raise LocalDatabaseError('database_secret_config_invalid')
    return dict(value)


def credential_engine(value, *, expected_role):
    config = secret_config(value, expected_role=expected_role)
    def creator():
        password = None
        try:
            password = WindowsDatabaseVault().read(config['role'], config['secret_revision'])
            return connect_local(role=config['role'], password=password, database='pathwise_probe')
        finally:
            password = None
    # No secret in SQLAlchemy URL, engine repr, exception args or JSON.
    return create_engine('postgresql+psycopg://', creator=creator, hide_parameters=True, echo=False)
