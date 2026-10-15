"""Operator-only, validated synthetic output. No raw response or secret store."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from uuid import UUID

from app.cost_ledger import canonical
from app.deepseek_bridge import synthetic_request
from app.deepseek_contract import ProbeError
from app.mining_context import MiningContext
from app.mining_provider import MiningOutputV2
from app.mining_validation import validate_context_v2
from app.windows_operator import powershell


def safe_output(output, *, secret=None):
    checked=validate_context_v2(
        MiningContext.model_validate_json(json.loads(synthetic_request().body)['messages'][1]['content']),output)
    value=checked.model_dump(mode='json',exclude={'tokens_in','tokens_out'})
    encoded=canonical(value)
    if ((secret and secret in encoded) or re.search(r'(?i)\b(?:sk-[a-z0-9_-]{6,}|bearer\s+\S+|authorization\s*:)',encoded)
        or any(c in encoded for c in ('\u202e','\u202d','\u2066','\u2067','\u2068','\u2069'))):
        raise ProbeError('controlled_preview_rejected')
    return value


def _acl(path, *, create=False):
    if os.name!='nt':
        if create:os.chmod(path,0o700 if path.is_dir() else 0o600)
        s=path.stat()
        if s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=(0o700 if path.is_dir() else 0o600):
            raise ProbeError('controlled_preview_access_denied')
        return
    # Only opaque path data is interpolated, never executable/user text.
    target=base64.b64encode(str(path).encode('utf8')).decode('ascii')
    code=f"$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{target}'));"
    code+="$ErrorActionPreference='Stop';$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;"
    if create:
        code+="""$dir=(Get-Item -LiteralPath $p).PSIsContainer;
        if($dir){$a=New-Object Security.AccessControl.DirectorySecurity;
          $rule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')}
        else{$a=New-Object Security.AccessControl.FileSecurity;
          $rule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','Allow')};
        $a.SetOwner($sid);$a.SetAccessRuleProtection($true,$false);$a.AddAccessRule($rule);
        if($dir){[IO.Directory]::SetAccessControl($p,$a)}else{[IO.File]::SetAccessControl($p,$a)};"""
    code+="""$a=Get-Acl -LiteralPath $p;$rules=$a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]);
    if(!$a.AreAccessRulesProtected -or $a.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value -or $rules.Count -ne 1 -or $rules[0].IdentityReference.Value -ne $sid.Value -or $rules[0].AccessControlType -ne 'Allow' -or $rules[0].FileSystemRights -ne 'FullControl'){exit 2}"""
    result=powershell(code)
    if result.returncode:raise ProbeError('controlled_preview_access_denied')


class LocalPreviewStore:
    def __init__(self,root):
        self.root=Path(root)
        if not self.root.is_absolute() or str(self.root).startswith('\\\\'):
            raise ProbeError('controlled_preview_local_path_required')

    def _check_links(self,path):
        for item in (path,*path.parents):
            if not item.exists() and not item.is_symlink():continue
            s=item.lstat()
            if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
                raise ProbeError('controlled_preview_link_refused')

    def prepare(self,grant_id):
        self._check_links(self.root)
        new=not self.root.exists()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        _acl(self.root,create=new)
        path=self.root/(str(UUID(str(grant_id)))+'.json')
        self._check_links(path)
        if path.exists():raise ProbeError('controlled_preview_already_exists')

    def save(self,row,output):
        value={'format':1,'grant_id':str(row['grant_id']),'ledger_id':str(row['ledger_id']),
            'policy_sha':row['policy_hash'],'request_sha':row['policy']['request_sha'],
            'execution':row['policy']['execution'],'validated_output':safe_output(output)}
        body=canonical(value).encode('utf8')
        self._check_links(self.root);_acl(self.root)
        path=self.root/(str(UUID(str(row['grant_id'])))+'.json')
        self._check_links(path)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            # Directory was already protected; lock down file before its first byte.
            _acl(path,create=True)
            with os.fdopen(fd,'wb') as file:
                fd=None;file.write(body);file.flush();os.fsync(file.fileno())
        finally:
            if fd is not None:os.close(fd)
        return hashlib.sha256(body).hexdigest()

    def load(self,row):
        expected=(row['diagnostic'] or {}).get('preview_sha')
        if not expected:return None
        self._check_links(self.root);_acl(self.root)
        path=self.root/(str(UUID(str(row['grant_id'])))+'.json')
        self._check_links(path);_acl(path)
        with open(path,'rb') as file:body=file.read(65537)
        if len(body)>65536 or hashlib.sha256(body).hexdigest()!=expected:
            raise ProbeError('controlled_preview_digest_mismatch')
        data=json.loads(body)
        if (set(data)!={'format','grant_id','ledger_id','policy_sha','request_sha','execution','validated_output'}
            or data['format']!=1 or data['grant_id']!=str(row['grant_id']) or data['ledger_id']!=str(row['ledger_id'])
            or data['policy_sha']!=row['policy_hash'] or data['request_sha']!=row['policy']['request_sha']
            or data['execution']!=row['policy']['execution']):raise ProbeError('controlled_preview_binding_invalid')
        return safe_output(MiningOutputV2.model_validate(data['validated_output']))


def operator_preview_store():
    if os.name!='nt':raise ProbeError('controlled_windows_required')
    return LocalPreviewStore(Path(os.environ['LOCALAPPDATA'])/'PathwiseProbe'/'results')
