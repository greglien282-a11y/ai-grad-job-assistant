"""Explicit local operator IO. Not imported by application startup/routes."""
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
import ctypes
from ctypes import wintypes
import json
import logging
import os
import ssl
import sys

import certifi
import httpx

from app.deepseek_contract import ENDPOINT, MODEL, VERSION, FAKE_SECRET, ProbeError
from app.model_adapter import parse_output, unique_pairs
from app.mining_context import MiningContext
from app.mining_validation import validate_context_v2
from app.controlled_probe import verify_bytes
from app.controlled_probe import ExperimentControl
from app.probe_preview import safe_output, LocalPreviewStore, operator_preview_store


@contextmanager
def private_io():
    # Dedicated one-shot CLI only, no web server or concurrent application work.
    previous=logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:yield
    finally:logging.disable(previous)


class WindowsCredentialSecret:
    """Current Windows user's Credential Manager; never environment or .env."""
    def resolve(self, policy):
        if os.name!='nt':raise ProbeError('controlled_windows_required')
        class Credential(ctypes.Structure):
            _fields_=[('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),
                ('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),('CredentialBlobSize',wintypes.DWORD),
                ('CredentialBlob',ctypes.POINTER(ctypes.c_byte)),('Persist',wintypes.DWORD),
                ('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),
                ('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]
        api=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
        api.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))]
        api.CredReadW.restype=wintypes.BOOL
        api.CredFree.argtypes=[ctypes.c_void_p]
        ptr=ctypes.POINTER(Credential)()
        if not api.CredReadW(policy.secret_ref,1,0,ctypes.byref(ptr)):
            raise ProbeError('controlled_secret_unavailable')
        try:
            c=ptr.contents
            revision=(c.LastWritten.dwHighDateTime<<32)|c.LastWritten.dwLowDateTime
            if (c.TargetName!=policy.secret_ref or c.UserName!=policy.account_ref or revision!=policy.secret_revision
                    or not 8<=c.CredentialBlobSize<=2048):raise ProbeError('controlled_secret_binding_changed')
            key=ctypes.string_at(c.CredentialBlob,c.CredentialBlobSize).decode('utf-16-le')
            if not key.isascii() or any(ord(ch)<=32 or ord(ch)>=127 for ch in key):
                raise ProbeError('controlled_secret_invalid')
            return key
        finally:
            if ptr:
                if ptr.contents.CredentialBlob:ctypes.memset(ptr.contents.CredentialBlob,0,ptr.contents.CredentialBlobSize)
                api.CredFree(ptr)


class FakeExperimentSecret:
    def resolve(self, policy):return FAKE_SECRET


class HTTPFailure(ProbeError):
    def __init__(self, code, status=None):
        super().__init__(code);self.code,self.status=code,status


def quiet_io(function):
    @wraps(function)
    async def wrapped(*args,**kwargs):
        with private_io():return await function(*args,**kwargs)
    return wrapped


def _https_options():
    # Pure configuration: cannot construct a connection or send a request.
    return dict(retries=0,verify=ssl.create_default_context(cafile=certifi.where()),trust_env=False,
                limits=httpx.Limits(max_connections=1,max_keepalive_connections=0))


@dataclass(frozen=True,repr=False)
class DispatchPermit:
    control: ExperimentControl
    policy: object
    token: str = field(repr=False)


@quiet_io
async def _post_once(body, key, *, mock=None, permit=None):
    """Bare calls are MOCK ONLY. Real IO must consume a DB-issued send token.

    A valid sent row alone cannot reconstruct the secret permit or replay it.
    The token is returned once by permit(), its SHA only is stored in SQL.
    """
    verify_bytes(body)
    if permit is None:
        if mock is None:raise ProbeError('controlled_dispatch_permit_required')
        if type(mock) is not httpx.MockTransport or key!=FAKE_SECRET:raise ProbeError('controlled_mock_boundary')
    else:
        if type(permit) is not DispatchPermit or type(permit.control) is not ExperimentControl:
            raise ProbeError('controlled_dispatch_permit_required')
        control,p=permit.control,permit.policy
        live=p.execution=='controlled_live_probe'
        if (live and (mock is not None or key is not None)) or (not live and (type(mock) is not httpx.MockTransport or key!=FAKE_SECRET)):
            raise ProbeError('controlled_mode_mismatch')
        control.check_role(live=live)
        if control.policy(p.execution).sha()!=p.sha():raise ProbeError('controlled_policy_changed')
        control.action(p,'dispatch',{'request_sha':p.request_sha,'operation':p.operation_hash,'dispatch_token':permit.token})
        if live:
            # Key resolution AND real client construction are inside this gate.
            key=WindowsCredentialSecret().resolve(p)
            if control.policy(p.execution).sha()!=p.sha():raise ProbeError('controlled_policy_changed')
    transport=mock if mock is not None else httpx.AsyncHTTPTransport(**_https_options())
    try:
        async with asyncio.timeout(45):
            async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,
                timeout=httpx.Timeout(connect=5,read=15,write=5,pool=5)) as client:
                async with client.stream('POST',ENDPOINT,content=body,
                    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'}) as response:
                    status=response.status_code
                    if status!=200:raise HTTPFailure('controlled_http_error',status)
                    chunks=[];size=0
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>262144:raise HTTPFailure('controlled_body_too_large',status)
                        chunks.append(chunk)
                    result=b''.join(chunks)
                    if permit is not None and permit.policy.execution=='controlled_live_probe':
                        # Check against the actual secret BEFORE it leaves this
                        # scope, including JSON-escaped echoes of that secret.
                        validate_response(result,body,secret=key)
                    return status,result
    except (TimeoutError,httpx.TimeoutException):raise HTTPFailure('controlled_timeout') from None
    except httpx.HTTPError:raise HTTPFailure('controlled_network_unknown') from None


def validate_response(body, request_body, *, secret=None):
    """Uses actual usage, NOT an invented hard input bound or TokenCertificate."""
    try:
        raw=json.loads(body,object_pairs_hook=unique_pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if raw['object']!='chat.completion' or raw['model'] not in (MODEL,VERSION):raise ValueError()
        if (not isinstance(raw['id'],str) or not 1<=len(raw['id'])<=200 or type(raw['created']) is not int
            or raw['created']<0 or not isinstance(raw['system_fingerprint'],str)):
            raise ValueError()
        if len(raw['choices'])!=1:raise ValueError()
        c=raw['choices'][0];m=c['message']
        if type(c['index']) is not int or c['index']!=0 or c['finish_reason']!='stop' or m['role']!='assistant' or m.get('refusal') or m.get('tool_calls') or m.get('reasoning_content'):
            raise ValueError()
        u=raw['usage'];keys=('prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','total_tokens')
        if any(type(u[k]) is not int or not 0<=u[k]<=10**12 for k in keys):raise ValueError()
        if (u['completion_tokens']>256 or u['prompt_tokens']!=u['prompt_cache_hit_tokens']+u['prompt_cache_miss_tokens']
            or u['total_tokens']!=u['prompt_tokens']+u['completion_tokens']):raise ValueError()
        reasoning=u.get('completion_tokens_details',{}).get('reasoning_tokens',0)
        if type(reasoning) is not int or reasoning!=0:raise ValueError()
        if 'prompt_tokens_details' in u and u['prompt_tokens_details'].get('cached_tokens')!=u['prompt_cache_hit_tokens']:raise ValueError()
        output=parse_output(m['content'])
        context=MiningContext.model_validate_json(json.loads(request_body)['messages'][1]['content'])
        checked=validate_context_v2(context,output)
        preview=safe_output(checked,secret=secret)
        return ({'http_status':200,'validated':True,'safe_code':'controlled_validated',
            'reported_model':raw['model'],'usage':{k:u[k] for k in keys}},preview)
    except Exception:raise ProbeError('controlled_response_invalid') from None


async def orchestrate(control, *, execution, mock=None, preview_store=None):
    # Only the separate CLI's interactive live entry calls with mock=None.
    # Test callers cannot use fixture policy to turn this into live IO.
    if type(control) is not ExperimentControl:raise ProbeError('controlled_control_required')
    if execution=='offline_mock':
        if type(mock) is not httpx.MockTransport:raise ProbeError('controlled_mock_required')
        resolver=FakeExperimentSecret()
    elif execution=='controlled_live_probe' and mock is None:
        resolver=WindowsCredentialSecret()
    else:raise ProbeError('controlled_mode_mismatch')
    live=execution=='controlled_live_probe'
    control.check_role(live=live)
    p=control.policy(execution)
    if control.read()['state']!='approved':raise ProbeError('controlled_already_attempted')
    if live:
        if os.name!='nt' or not sys.stdin.isatty():raise ProbeError('controlled_interactive_windows_required')
        row=control.read()
        print('风险：无法严格保证最高账单。内部计划 CNY '+str(p.planned_cny)+' 并非供应商损失上限。')
        print('固定合成 SHA '+p.request_sha+'；账户引用 '+p.account_ref+'；仅一次 POST，不重试。')
        expected='EXECUTE '+str(row['grant_id'])+' '+p.sha()[:12]
        if input('确认后输入 '+expected+': ').strip()!=expected:
            raise ProbeError('controlled_confirmation_cancelled')
        if preview_store is not None:raise ProbeError('controlled_operator_preview_path_fixed')
        preview_store=operator_preview_store()
    if preview_store is not None:
        if type(preview_store) is not LocalPreviewStore:raise ProbeError('controlled_preview_store_required')
        preview_store.prepare(control.read()['grant_id'])
    from app.deepseek_bridge import synthetic_request
    body=synthetic_request().body;verify_bytes(body)
    result=control.action(p,'reserve')
    if not result['created']:raise ProbeError('controlled_already_attempted')
    p2=control.policy(execution)
    if p2.sha()!=p.sha():raise ProbeError('controlled_policy_changed')
    permission=control.action(p,'permit')
    if not permission['permitted']:raise ProbeError('controlled_already_attempted')
    permit=DispatchPermit(control,p,permission['dispatch_token'])
    status=None
    preview=None
    retention_error=False
    try:
        # After sent, even a local failure or no actual socket is uncertain.
        p2=control.policy(execution);verify_bytes(body)
        if p2.sha()!=p.sha():raise ProbeError('controlled_policy_changed')
        with private_io():
            key=resolver.resolve(p) if not live else None
            try:
                if control.policy(execution).sha()!=p.sha():raise ProbeError('controlled_policy_changed')
                verify_bytes(body)
                status,raw=await _post_once(body,key,mock=mock,permit=permit)
                # Live secret stays inside the gated IO; credential-like output
                # is independently rejected by the preview's strict filter.
                diagnostic,preview=validate_response(raw,body,secret=key)
                del raw
            finally:del key  # Python/OS memory zeroization cannot be guaranteed.
        if preview_store is not None:
            try:diagnostic['preview_sha']=preview_store.save(control.read(),preview)
            except Exception:
                retention_error=True
                raise ProbeError('controlled_preview_retention_failed') from None
        control.action(p,'received',diagnostic)
    except BaseException as error:
        code='controlled_cancelled' if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt)) else 'controlled_result_unknown'
        if isinstance(error,HTTPFailure):code=error.code;status=error.status
        if isinstance(error,ProbeError) and str(error) in ('controlled_response_invalid','controlled_secret_unavailable','controlled_secret_binding_changed','controlled_secret_invalid'):
            code=str(error)
        try:control.action(p,'unknown',{'http_status':status,'validated':False,'safe_code':code})
        except Exception:raise ProbeError('controlled_unknown_not_persisted') from None
        if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt)):raise asyncio.CancelledError() from None
    result=control.report()
    if preview is not None:result['validated_preview']=preview
    if retention_error:result['preview_error']='controlled_preview_retention_failed_no_retry'
    return result
