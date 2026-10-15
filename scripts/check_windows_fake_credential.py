"""Native Windows smoke: one random owned entry, PUBLIC FAKE values only.

Never enumerates credentials, accepts a Key/target argument, connects to a DB
or calls HTTP. Exercises the actual PowerShell writer and Python reader.
"""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.controlled_probe_io import WindowsCredentialSecret
from app.deepseek_contract import ProbeError
from app.windows_operator import powershell


def main():
    if os.name!='nt':raise SystemExit('Windows native test only; use fake native unit tests in Linux CI')
    account='native_test_'+uuid4().hex
    target='Pathwise/DeepSeek/'+account
    writer=Path(__file__).resolve().with_name('set-probe-secret.ps1')
    api=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
    api.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD]
    api.CredDeleteW.restype=wintypes.BOOL
    result={'mode':'windows_native_fake_credential','passed':False,'cleanup_verified':False,
        'real_key_reads':0,'real_provider_requests':0,'real_authorizations_created':0}

    def write_fake(value):
        assert value in ('PATHWISE_PUBLIC_FAKE_FIRST','PATHWISE_PUBLIC_FAKE_ROTATED')
        path=base64.b64encode(str(writer).encode('utf8')).decode('ascii')
        code=f"""$ErrorActionPreference='Stop';
        function Read-Host {{ param([string]$Prompt,[switch]$AsSecureString)
          ConvertTo-SecureString '{value}' -AsPlainText -Force }}
        $script=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{path}'));
        try {{ & $script -AccountRef '{account}' }} catch {{
          [Console]::Error.WriteLine($_.Exception.GetType().FullName+': '+$_.Exception.Message);exit 2 }}"""
        process=powershell(code)
        if process.returncode:
            # This diagnostic script handles ONLY public fake values in its own
            # random entry; never used for production keys or arbitrary targets.
            result['fake_writer_error']='native_writer_failed'
            raise ValueError('fake writer failed')
        raw=process.stdout
        result['last_stage']='fake_writer_completed'
        data=json.loads(raw.decode('utf-8-sig'))
        assert data['account_ref']==account and data['secret_ref']==target
        return SimpleNamespace(account_ref=account,secret_ref=target,secret_revision=data['secret_revision'])

    try:
        with patch.object(socket,'socket',side_effect=AssertionError('no network')), \
             patch.object(socket,'getaddrinfo',side_effect=AssertionError('no DNS')):
            first=write_fake('PATHWISE_PUBLIC_FAKE_FIRST')
            assert WindowsCredentialSecret().resolve(first)=='PATHWISE_PUBLIC_FAKE_FIRST'
            result['native_write_read']=True
            wrong=SimpleNamespace(**(vars(first)|{'account_ref':'wrong-account'}))
            try:WindowsCredentialSecret().resolve(wrong)
            except ProbeError as error:assert str(error)=='controlled_secret_binding_changed'
            else:raise AssertionError('account binding not enforced')
            result['account_binding']=True
            time.sleep(.02)
            rotated=write_fake('PATHWISE_PUBLIC_FAKE_ROTATED')
            assert first.secret_revision!=rotated.secret_revision
            try:WindowsCredentialSecret().resolve(first)
            except ProbeError as error:assert str(error)=='controlled_secret_binding_changed'
            else:raise AssertionError('old revision accepted')
            assert WindowsCredentialSecret().resolve(rotated)=='PATHWISE_PUBLIC_FAKE_ROTATED'
            result['rotation_revision_binding']=True
            assert api.CredDeleteW(target,1,0)
            try:WindowsCredentialSecret().resolve(rotated)
            except ProbeError as error:assert str(error)=='controlled_secret_unavailable'
            else:raise AssertionError('deleted entry readable')
            result['native_delete']=True
            result['passed']=True
    except BaseException as error:
        result['safe_error']='native_fake_verification_failed'
        result['failure_type']=type(error).__name__
    finally:
        # Delete only our unpredictable test name, even if the writer failed
        # after writing but before returning metadata. No other target is read.
        assert target.startswith('Pathwise/DeepSeek/native_test_') and account[-32:].isalnum()
        api.CredDeleteW(target,1,0)
        try:
            WindowsCredentialSecret().resolve(SimpleNamespace(account_ref=account,secret_ref=target,secret_revision=1))
        except ProbeError as error:result['cleanup_verified']=str(error)=='controlled_secret_unavailable'
    print(json.dumps(result,ensure_ascii=True))
    return 0 if result['passed'] and result['cleanup_verified'] else 2


if __name__=='__main__':raise SystemExit(main())
