"""One random owned entry, public fake values only; no DB or provider IO.

Production writer gates have no noninteractive bypass. This test loads its
functions in an isolated host and replaces only terminal input/interaction.
Never accepts an account, target or Key argument. No credential enumeration.
"""
import base64
import ctypes
from ctypes import wintypes
import json
import hashlib
import re
import os
from pathlib import Path
import socket
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from app.controlled_probe_io import WindowsCredentialSecret
from app.deepseek_contract import ProbeError
from app.windows_operator import powershell


def main():
    if os.name != 'nt':
        raise SystemExit('Windows native fake test only')
    account = 'native_test_' + uuid4().hex
    target = 'Pathwise/DeepSeek/' + account
    writer = Path(__file__).resolve().with_name('set-probe-secret.ps1')
    api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.POINTER(ctypes.c_void_p)]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    result = dict(mode='windows_native_fake_credential', passed=False,
                  cleanup_verified=False, real_key_reads=0, real_provider_requests=0,
                  real_authorizations_created=0)
    owned = False

    def absent():
        pointer = ctypes.c_void_p()
        ctypes.set_last_error(0)
        ok = api.CredReadW(target, 1, 0, ctypes.byref(pointer))
        error = ctypes.get_last_error()
        if ok:
            api.CredFree(pointer)
            return False
        return error == 1168

    def writer_call(*, rotate=False, revision=0, busy=False):
        value = 'PATHWISE_PUBLIC_FAKE_ROTATED' if rotate else 'PATHWISE_PUBLIC_FAKE_FIRST'
        encoded = base64.b64encode(str(writer).encode('utf8')).decode('ascii')
        # No production switch or environment variable bypasses terminal gates.
        # Only this fake test replaces the assertion/input functions in memory.
        code = f"""$ErrorActionPreference='Stop';
        $p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'));
        $source=[IO.File]::ReadAllText($p);
        $begin=$source.IndexOf('Add-Type -TypeDefinition');
        $end=$source.LastIndexOf('$result=Invoke-PathwiseSecret');
        . ([scriptblock]::Create($source.Substring($begin,$end-$begin)));
        function Assert-PathwiseInteractive {{ }}
        $script:inputCalls=0;
        function Read-Host {{ param([string]$Prompt,[switch]$AsSecureString)
          $script:inputCalls++;
          if($AsSecureString){{ConvertTo-SecureString '{value}' -AsPlainText -Force}}
          else{{'ROTATE {account} {revision}'}} }}
        """
        code += f"""
        $r=Invoke-PathwiseSecret '{account}' ${str(rotate).lower()} ([uint64]{revision});
        @{{result=$r;input_calls=$script:inputCalls}}|ConvertTo-Json -Compress
        """
        if busy:
            # Parent Python thread holds the same named mutex while a separate
            # PowerShell process attempts the writer. No nested shell launch.
            sid = powershell('[Security.Principal.WindowsIdentity]::GetCurrent().User.Value')
            if sid.returncode:
                raise ValueError('fake_mutex_identity_failed')
            identity = sid.stdout.decode('utf-8-sig').strip()
            if not re.fullmatch(r'S-1-[0-9-]+', identity):
                raise ValueError('fake_mutex_identity_failed')
            name = 'Global\\PathwiseDeepSeekCredential_' + hashlib.sha256(
                (identity + '|' + target.upper()).encode('utf8')).hexdigest().upper()
            kernel = ctypes.WinDLL('kernel32.dll', use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.CreateMutexW(None, False, name)
            acquired = False
            try:
                if not handle or kernel.WaitForSingleObject(handle, 0) != 0:
                    raise ValueError('fake_mutex_acquisition_failed')
                acquired = True
                proc = powershell(code)
            finally:
                if acquired:
                    kernel.ReleaseMutex(handle)
                if handle:
                    kernel.CloseHandle(handle)
        else:
            proc = powershell(code)
        if proc.returncode:
            raise ValueError('native_fake_writer_host_failed')
        data = json.loads(proc.stdout.decode('utf-8-sig'))
        assert value not in json.dumps(data)
        # Fixed diagnostic vocabulary only; never child exception text or keys.
        result['last_writer_status'] = data['result']['status']
        code = data['result'].get('safe_code')
        result['last_writer_code'] = code if code and code.startswith('controlled_secret_') else None
        return data

    def policy(data):
        row = data['result']
        assert row['status'] == 'stored' and row['account_ref'] == account and row['secret_ref'] == target
        return SimpleNamespace(account_ref=account, secret_ref=target, secret_revision=row['secret_revision'])

    try:
        if not absent():
            raise ValueError('random_target_not_provably_absent')
        # Only this random target may be cleaned if any later stage fails.
        owned = True
        with patch.object(socket, 'socket', side_effect=AssertionError('no network')), \
             patch.object(socket, 'getaddrinfo', side_effect=AssertionError('no DNS')):
            first = policy(writer_call())
            assert WindowsCredentialSecret().resolve(first) == 'PATHWISE_PUBLIC_FAKE_FIRST'
            result['native_write_read'] = True
            rejected = writer_call()
            assert rejected['result']['safe_code'] == 'controlled_secret_exists' and rejected['input_calls'] == 0
            assert WindowsCredentialSecret().resolve(first) == 'PATHWISE_PUBLIC_FAKE_FIRST'
            result['default_existing_refused_unchanged'] = True
            result['last_stage'] = 'wrong_revision'
            wrong = writer_call(rotate=True, revision=first.secret_revision + 1)
            assert wrong['result']['safe_code'] == 'controlled_secret_binding_changed' and wrong['input_calls'] == 0
            result['last_stage'] = 'lock_contention'
            busy = writer_call(busy=True)
            assert busy['result']['safe_code'] == 'controlled_secret_lock_busy' and busy['input_calls'] == 0
            result['cooperative_lock_contention'] = True
            result['last_stage'] = 'rotation'
            time.sleep(.02)
            rotated = policy(writer_call(rotate=True, revision=first.secret_revision))
            assert rotated.secret_revision != first.secret_revision
            for stale in (first, SimpleNamespace(**(vars(rotated) | {'account_ref': 'wrong-account'}))):
                try:
                    WindowsCredentialSecret().resolve(stale)
                except ProbeError as error:
                    assert str(error) == 'controlled_secret_binding_changed'
                else:
                    raise AssertionError('binding not enforced')
            assert WindowsCredentialSecret().resolve(rotated) == 'PATHWISE_PUBLIC_FAKE_ROTATED'
            rejected = writer_call(rotate=True, revision=first.secret_revision)
            assert rejected['result']['safe_code'] == 'controlled_secret_binding_changed' and rejected['input_calls'] == 0
            result['rotation_revision_binding'] = True
            result['account_binding'] = True
            result['passed'] = True
    except BaseException:
        result['safe_error'] = 'native_fake_verification_failed'
    finally:
        if owned:
            try:
                api.CredDeleteW(target, 1, 0)
                result['cleanup_verified'] = absent()
            except BaseException:
                result['cleanup_verified'] = False
            result['cleanup_win32_error'] = 1168 if result['cleanup_verified'] else None
            if not result['cleanup_verified']:
                result['blocked_cleanup_target'] = target
                result['passed'] = False
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['passed'] and result['cleanup_verified'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
