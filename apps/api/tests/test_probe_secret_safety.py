"""Public fake values only. No DB, real credentials or provider requests."""
import base64
import ctypes
import os
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import psycopg
import pytest

from app import controlled_probe_io as io
from app.windows_operator import powershell

WRITER = Path(__file__).resolve().parents[3] / 'scripts/set-probe-secret.ps1'
ACCOUNT = 'offline_fake_only'
REF = 'Pathwise/DeepSeek/' + ACCOUNT
FAKE = 'PUBLIC_FAKE_ONLY'


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    guards = []
    for obj, name in ((psycopg, 'connect'), (socket, 'socket'),
                      (socket, 'getaddrinfo'), (httpx.HTTPTransport, 'handle_request'),
                      (httpx.AsyncHTTPTransport, 'handle_async_request')):
        guard = Mock(side_effect=AssertionError('external IO prohibited'))
        monkeypatch.setattr(obj, name, guard)
        guards.append(guard)
    # Tests that need a reader replace this with fake unmanaged memory only.
    native = Mock(side_effect=AssertionError('native credentials prohibited'))
    monkeypatch.setattr(ctypes, 'WinDLL', native, raising=False)
    yield
    for guard in (*guards, native):
        guard.assert_not_called()


def policy(**changes):
    return SimpleNamespace(**(dict(account_ref=ACCOUNT, secret_ref=REF, secret_revision=123) | changes))


def fake_native(monkeypatch, raw=None, *, change=None, fail=None):
    raw = FAKE.encode('utf-16-le') if raw is None else raw
    held, freed, reads = [], [], []

    class Read:
        def __call__(self, target, kind, flags, out):
            reads.append(target)
            assert (target, kind, flags) == (REF, 1, 0)
            if fail == 'read':
                return False
            if fail == 'null_result':
                return True
            structure = self.argtypes[-1]._type_._type_
            c = structure(Type=1, TargetName=REF, UserName=ACCOUNT)
            c.LastWritten.dwLowDateTime = 123
            blob = (ctypes.c_byte * len(raw)).from_buffer_copy(raw)
            c.CredentialBlobSize = len(raw)
            c.CredentialBlob = blob
            if change:
                change(c)
            held.append((c, blob))
            ctypes.cast(out, self.argtypes[-1])[0] = ctypes.pointer(c)
            return True

    class Free:
        def __call__(self, ptr):
            freed.append(True)
            if fail == 'free':
                raise RuntimeError(FAKE)

    api = SimpleNamespace(CredReadW=Read(), CredFree=Free())
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: api, raising=False)
    return held, freed, reads


@pytest.mark.parametrize('changes', [dict(account_ref='wrong'), dict(account_ref=''),
    dict(account_ref='a/b'), dict(secret_ref='Pathwise/PostgreSQL/forbidden'),
    dict(secret_ref='Pathwise/DeepSeek/other'), dict(secret_revision=0),
    dict(secret_revision=-1), dict(secret_revision=True), dict(secret_revision='123'),
    dict(secret_revision=None)])
def test_binding_rejected_before_native_io(monkeypatch, changes):
    with monkeypatch.context() as m:
        m.setattr(io.os, 'name', 'nt')
        with pytest.raises(io.ProbeError, match='^controlled_secret_binding_changed$'):
            io.WindowsCredentialSecret().resolve(policy(**changes))


@pytest.mark.parametrize('length,accepted', [(4, False), (7, False), (8, True),
                                           (1024, True), (1025, False)])
def test_reader_lengths(monkeypatch, length, accepted):
    raw = ('!' * length).encode('utf-16-le')
    held, freed, _ = fake_native(monkeypatch, raw)
    with monkeypatch.context() as m:
        m.setattr(io.os, 'name', 'nt')
        if accepted:
            assert io.WindowsCredentialSecret().resolve(policy()) == '!' * length
        else:
            with pytest.raises(io.ProbeError):
                io.WindowsCredentialSecret().resolve(policy())
    assert freed == [True] and all(b == 0 for b in held[0][1])


@pytest.mark.parametrize('raw', [('FAKE ONLY').encode('utf-16-le'),
    ('FAKE\tONLY').encode('utf-16-le'), ('FAKE\nONLY').encode('utf-16-le'),
    ('FAKE\x7fONLY').encode('utf-16-le'), ('FAKE\0ONLY').encode('utf-16-le'),
    ('公开假值测试文本').encode('utf-16-le'), b'\x00\xd8' + b'A\x00' * 7,
    FAKE.encode('utf-16-le') + b'x'])
def test_invalid_blob_has_only_safe_error(monkeypatch, raw):
    held, freed, _ = fake_native(monkeypatch, raw)
    with monkeypatch.context() as m:
        m.setattr(io.os, 'name', 'nt')
        with pytest.raises(io.ProbeError) as error:
            io.WindowsCredentialSecret().resolve(policy())
    assert error.value.args[0] in ('controlled_secret_invalid', 'controlled_secret_binding_changed')
    assert FAKE not in str(error.value) and raw not in error.value.args
    assert freed == [True] and all(b == 0 for b in held[0][1])


@pytest.mark.parametrize('field,value', [('Type', 2), ('TargetName', 'other'),
    ('UserName', 'other'), ('CredentialBlob', None)])
def test_returned_binding_and_pointer(monkeypatch, field, value):
    def change(c):
        setattr(c, field, value if value is not None else ctypes.POINTER(ctypes.c_byte)())
    _, freed, _ = fake_native(monkeypatch, change=change)
    with monkeypatch.context() as m:
        m.setattr(io.os, 'name', 'nt')
        with pytest.raises(io.ProbeError, match='^controlled_secret_binding_changed$'):
            io.WindowsCredentialSecret().resolve(policy())
    assert freed == [True]


@pytest.mark.parametrize('failure', ['read', 'null_result', 'free', 'zero'])
def test_reader_native_failures_are_safe_and_free_is_independent(monkeypatch, failure):
    _, freed, _ = fake_native(monkeypatch, fail=failure)
    if failure == 'zero':
        monkeypatch.setattr(ctypes, 'memset', Mock(side_effect=RuntimeError(FAKE)))
    with monkeypatch.context() as m:
        m.setattr(io.os, 'name', 'nt')
        with pytest.raises(io.ProbeError) as error:
            io.WindowsCredentialSecret().resolve(policy())
    assert str(error.value).startswith('controlled_secret_') and FAKE not in str(error.value)
    assert freed == ([] if failure in ('read', 'null_result') else [True])


# This fake C# class implements the same native IO boundary, with only public
# fake memory. It does not import or call ANY Windows Credential Manager API.
FAKE_CS = r'''
using System;
using System.Runtime.InteropServices;
public static class PathwiseCredential {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct Credential {
    public UInt32 Flags,Type; public string TargetName,Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
    public UInt32 CredentialBlobSize; public IntPtr CredentialBlob;
    public UInt32 Persist,AttributeCount; public IntPtr Attributes;
    public string TargetAlias,UserName;
  }
  public static bool Exists,WriteThrows,WriteFalse,FreeThrows,NoRevision,ParseThrows,ZeroThrows;
  public static int Reads,Writes,Frees,Error,FailReadAt,ChangeReadAt;
  public static UInt32 Revision=100,Bytes=16;
  public static void Reset() {
    Exists=WriteThrows=WriteFalse=FreeThrows=NoRevision=ParseThrows=ZeroThrows=false;
    Reads=Writes=Frees=Error=FailReadAt=ChangeReadAt=0; Revision=100;Bytes=16;
  }
  public static bool Read(string target,UInt32 type,UInt32 flags,out IntPtr ptr) {
    Reads++;ptr=IntPtr.Zero;
    if ((Error!=0 && Error!=1168) || Reads==FailReadAt) { Error=5;return false; }
    if (!Exists) { Error=1168;return false; }
    Error=0;
    if(Reads==ChangeReadAt)Revision++;
    Credential c=new Credential();c.Type=1;c.TargetName=target;c.UserName="offline_fake_only";
    c.LastWritten.dwLowDateTime=(int)Revision;c.CredentialBlobSize=Bytes;
    c.CredentialBlob=Marshal.AllocHGlobal((int)Bytes);
    for(int i=0;i<Bytes;i++)Marshal.WriteByte(c.CredentialBlob,i,33);
    ptr=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(Credential)));Marshal.StructureToPtr(c,ptr,false);
    return true;
  }
  public static bool Write(ref Credential c,UInt32 flags) {
    Writes++;Exists=true;Bytes=c.CredentialBlobSize;if(!NoRevision)Revision++;
    if(WriteThrows)throw new Exception("PUBLIC_FAKE_ONLY");return !WriteFalse;
  }
  public static void CredFree(IntPtr ptr) {
    Frees++;Credential c=(Credential)Marshal.PtrToStructure(ptr,typeof(Credential));
    Marshal.FreeHGlobal(c.CredentialBlob);Marshal.DestroyStructure(ptr,typeof(Credential));
    Marshal.FreeHGlobal(ptr);if(FreeThrows)throw new Exception("PUBLIC_FAKE_ONLY");
  }
}
'''


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell 5.1 Fake Native harness requires Windows')
def test_powershell_syntax_and_fake_native_scenarios():
    encoded = base64.b64encode(str(WRITER).encode()).decode()
    code = "Add-Type -TypeDefinition @'\n" + FAKE_CS + "\n'@\n" + r'''
    $ErrorActionPreference='Stop';
    $path=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('ENCODED_PATH'));
    $tokens=$null;$errors=$null;
    $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors);
    if($errors.Count){throw 'writer_syntax_error'}
    $source=[IO.File]::ReadAllText($path);
    $begin=$source.IndexOf('function Assert-PathwiseInteractive');
    $end=$source.LastIndexOf('$result=Invoke-PathwiseSecret');
    $functions=$source.Substring($begin,$end-$begin);
    # Only native return/error/Marshal parsing boundaries are substituted.
    $functions=$functions.Replace('[Runtime.InteropServices.Marshal]::GetLastWin32Error()', '[PathwiseCredential]::Error');
    $functions=$functions.Replace('[Runtime.InteropServices.Marshal]::PtrToStructure(', 'Read-TestStructure ' + '(');
    $functions=$functions.Replace('[Runtime.InteropServices.Marshal]::WriteByte(', 'Write-TestByte ' + '(');
    . ([scriptblock]::Create($functions));
    # Reuse the actual script parameter block; never run the writer entrypoint.
    . ([scriptblock]::Create('function Test-AccountParameter {'+
      $ast.ParamBlock.Extent.Text+'; $script:parameterBodyCalls++ }'));
    $script:parameterBodyCalls=0;
    Test-AccountParameter -AccountRef 'a';
    Test-AccountParameter -AccountRef ('A'*64);
    if($script:parameterBodyCalls -ne 2){throw 'valid_account_parameter_rejected'}
    # Credential TargetName is case-insensitive, but account bindings stay exact.
    $lower=Get-PathwiseLockName 'Pathwise/DeepSeek/offline_fake_only' 'S-1-5-21-1';
    $upper=Get-PathwiseLockName 'PATHWISE/DEEPSEEK/OFFLINE_FAKE_ONLY' 'S-1-5-21-1';
    $other=Get-PathwiseLockName 'Pathwise/DeepSeek/offline_fake_only' 'S-1-5-21-2';
    if($lower -cne $upper -or $lower -ceq $other){throw 'lock_name_binding_failed'}
    function Read-TestStructure($argsPair) {
      if([PathwiseCredential]::ParseThrows){throw 'PUBLIC_FAKE_ONLY'}
      [Runtime.InteropServices.Marshal]::PtrToStructure([IntPtr]$argsPair[0],[type]$argsPair[1])
    }
    function Write-TestByte($argsTriple) {
      if([PathwiseCredential]::ZeroThrows){throw 'PUBLIC_FAKE_ONLY'}
      [Runtime.InteropServices.Marshal]::WriteByte($argsTriple[0],$argsTriple[1],$argsTriple[2])
    }
    function Assert-PathwiseInteractive { }
    function Enter-PathwiseLock($target) {
      if($script:case -eq 'busy'){throw 'controlled_secret_lock_busy'}
      if($script:case -eq 'abandoned'){throw 'controlled_secret_lock_abandoned'}
      return 'FAKE_MUTEX'
    }
    function Exit-PathwiseLock($mutex) {
      $script:released++;
      if($script:case -eq 'release_failure'){throw 'PUBLIC_FAKE_ONLY'}
    }
    function New-PathwisePointer($secure) {
      if($script:case -eq 'allocation_failure'){throw 'PUBLIC_FAKE_ONLY'}
      [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure)
    }
    function Clear-PathwisePointer($pointer) {
      $script:cleared++;
      [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pointer);
      if($script:case -eq 'clear_failure'){throw 'PUBLIC_FAKE_ONLY'}
    }
    function Dispose-PathwiseSecure($secure) {
      $script:disposed++;$secure.Dispose();
      if($script:case -eq 'dispose_failure'){throw 'PUBLIC_FAKE_ONLY'}
    }
    function Read-Host { param($Prompt,[switch]$AsSecureString)
      $script:inputs++;
      if(!$AsSecureString){
        if($script:case -eq 'cancel'){return 'cancel'}
        return 'ROTATE offline_fake_only 100'
      }
      $v='FAKEONLY';
      switch($script:case){
        'length4' {$v='!!!!'} 'length7' {$v='!!!!!!!'}
        'length1024' {$v='!'*1024} 'length1025' {$v='!'*1025}
        'space' {$v='FAKE ONLY'} 'control' {$v="FAKE`nONLY"}
        'unicode' {$v=[string][char]0x4e2d+'FAKEONLY'}
      }
      ConvertTo-SecureString $v -AsPlainText -Force
    }
    $cases=@('first','exists','rotation','stale','missing_rotation','cancel','access_error',
      'busy','abandoned','length4','length7','length1024','length1025','space','control','unicode',
      'allocation_failure','readback_failure','write_failure','write_false','same_revision','binding_race',
      'clear_failure','dispose_failure','release_failure','parse_failure','zero_failure','free_failure',
      'account_lf','account_crlf','account_cr','account_space','account_slash','account_tab',
      'account_null','account_unicode','account_empty','account_overlong');
    $all=@();
    foreach($script:case in $cases){
      [PathwiseCredential]::Reset();$script:inputs=0;$script:disposed=0;$script:released=0;$script:cleared=0;
      $rotate=$false;$revision=[uint64]0;
      if($case -in @('exists','rotation','stale','cancel','same_revision','binding_race','parse_failure','zero_failure','free_failure')){
        [PathwiseCredential]::Exists=$true;
      }
      if($case -in @('rotation','stale','cancel','same_revision','binding_race','missing_rotation')){$rotate=$true;$revision=100}
      if($case -eq 'stale'){$revision=99}
      if($case -eq 'access_error'){[PathwiseCredential]::Error=5}
      if($case -eq 'readback_failure'){[PathwiseCredential]::FailReadAt=3}
      if($case -eq 'write_failure'){[PathwiseCredential]::WriteThrows=$true}
      if($case -eq 'write_false'){[PathwiseCredential]::WriteFalse=$true}
      if($case -eq 'binding_race'){[PathwiseCredential]::ChangeReadAt=2}
      if($case -eq 'same_revision'){[PathwiseCredential]::NoRevision=$true}
      if($case -eq 'parse_failure'){[PathwiseCredential]::ParseThrows=$true}
      if($case -eq 'zero_failure'){[PathwiseCredential]::ZeroThrows=$true}
      if($case -eq 'free_failure'){[PathwiseCredential]::FreeThrows=$true}
      $account='offline_fake_only';$parameterRejected=$false;$script:parameterBodyCalls=0;
      switch($case){
        'account_lf' {$account+="`n"} 'account_crlf' {$account+="`r`n"}
        'account_cr' {$account+="`r"} 'account_space' {$account+=' '}
        'account_slash' {$account+='/'} 'account_tab' {$account+="`t"}
        'account_null' {$account+=[char]0} 'account_unicode' {$account+=[char]0x4e2d}
        'account_empty' {$account=''} 'account_overlong' {$account='A'*65}
      }
      if($case.StartsWith('account_')){
        try { Test-AccountParameter -AccountRef $account }
        catch [Management.Automation.ParameterBindingException] { $parameterRejected=$true }
      }
      $r=Invoke-PathwiseSecret $account $rotate $revision;
      $all+=@{case=$case;result=$r;writes=[PathwiseCredential]::Writes;frees=[PathwiseCredential]::Frees;
        reads=[PathwiseCredential]::Reads;parameter_rejected=$parameterRejected;parameter_body_calls=$script:parameterBodyCalls;
        inputs=$script:inputs;disposed=$script:disposed;released=$script:released;cleared=$script:cleared};
    }
    $all|ConvertTo-Json -Depth 6 -Compress
    '''.replace('ENCODED_PATH', encoded)
    proc = powershell(code)
    assert proc.returncode == 0, proc.stderr.decode(errors='replace')
    import json
    data = json.loads(proc.stdout.decode('utf-8-sig'))
    assert FAKE not in proc.stdout.decode('utf-8-sig')
    assert len(data) == 38
    success = {'first', 'rotation', 'length1024'}
    unknown = {'readback_failure', 'write_failure', 'write_false', 'same_revision',
               'clear_failure', 'dispose_failure', 'release_failure'}
    for row in data:
        name = row['case']
        expected = 'stored' if name in success else 'outcome_unknown' if name in unknown else 'stopped'
        assert row['result']['status'] == expected, row
        assert row['writes'] == (1 if name in success | unknown else 0), row
        if name.startswith('account_'):
            assert row['result']['safe_code'] == 'controlled_secret_binding_changed', row
            assert row['parameter_rejected'] and row['parameter_body_calls'] == 0, row
            assert row['reads'] == row['inputs'] == row['writes'] == row['released'] == 0, row
        if name in {'exists', 'stale', 'missing_rotation', 'access_error', 'busy', 'abandoned'}:
            assert row['inputs'] == 0, row
        if name in {'allocation_failure', 'clear_failure', 'dispose_failure', 'release_failure'}:
            assert row['disposed'] == row['released'] == 1, row
        if name in {'parse_failure', 'zero_failure', 'free_failure'}:
            assert row['frees'] == 1, row
        codes = {'exists': 'controlled_secret_exists', 'access_error': 'controlled_secret_access_failed',
                 'busy': 'controlled_secret_lock_busy', 'abandoned': 'controlled_secret_lock_abandoned',
                 'binding_race': 'controlled_secret_binding_changed', 'stale': 'controlled_secret_binding_changed',
                 'cancel': 'controlled_confirmation_cancelled'}
        if name in codes:
            assert row['result']['safe_code'] == codes[name], row
