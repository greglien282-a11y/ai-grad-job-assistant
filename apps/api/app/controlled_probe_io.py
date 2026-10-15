"""Explicit local operator IO. Not imported by application startup/routes."""
import asyncio
from contextlib import contextmanager
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


async def _post_once(body, key, *, mock=None):
    """Private IO primitive; caller must already commit unique sent intent.

    Exact MockTransport accepted for offline fixtures. Production transport has
    zero retries, fixed CA bundle, no redirects/proxy or customizable target.
    """
    verify_bytes(body)
    if mock is not None and (type(mock) is not httpx.MockTransport or key!=FAKE_SECRET):
        raise ProbeError('controlled_mock_boundary')
    transport=mock if mock is not None else httpx.AsyncHTTPTransport(retries=0,
        verify=ssl.create_default_context(cafile=certifi.where()),trust_env=False,
        limits=httpx.Limits(max_connections=1,max_keepalive_connections=0))
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
                    return status,b''.join(chunks)
    except (TimeoutError,httpx.TimeoutException):raise HTTPFailure('controlled_timeout') from None
    except httpx.HTTPError:raise HTTPFailure('controlled_network_unknown') from None


def validate_response(body, request_body):
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
        validate_context_v2(context,output)
        return {'http_status':200,'validated':True,'safe_code':'controlled_validated',
            'reported_model':raw['model'],'usage':{k:u[k] for k in keys}}
    except Exception:raise ProbeError('controlled_response_invalid') from None


async def orchestrate(control, *, execution, mock=None):
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
    from app.deepseek_bridge import synthetic_request
    body=synthetic_request().body;verify_bytes(body)
    result=control.action(p,'reserve')
    if not result['created']:raise ProbeError('controlled_already_attempted')
    p2=control.policy(execution)
    if p2.sha()!=p.sha():raise ProbeError('controlled_policy_changed')
    if not control.action(p,'permit')['permitted']:raise ProbeError('controlled_already_attempted')
    status=None
    try:
        # After sent, even a local failure or no actual socket is uncertain.
        p2=control.policy(execution);verify_bytes(body)
        if p2.sha()!=p.sha():raise ProbeError('controlled_policy_changed')
        with private_io():
            key=resolver.resolve(p)
            try:
                if control.policy(execution).sha()!=p.sha():raise ProbeError('controlled_policy_changed')
                verify_bytes(body)
                status,raw=await _post_once(body,key,mock=mock)
            finally:del key  # Python/OS memory zeroization cannot be guaranteed.
            diagnostic=validate_response(raw,body)
            del raw
        control.action(p,'received',diagnostic)
    except BaseException as error:
        code='controlled_cancelled' if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt)) else 'controlled_result_unknown'
        if isinstance(error,HTTPFailure):code=error.code;status=error.status
        if isinstance(error,ProbeError) and str(error) in ('controlled_response_invalid','controlled_secret_unavailable','controlled_secret_binding_changed','controlled_secret_invalid'):
            code=str(error)
        try:control.action(p,'unknown',{'http_status':status,'validated':False,'safe_code':code})
        except Exception:raise ProbeError('controlled_unknown_not_persisted') from None
        if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt)):raise asyncio.CancelledError() from None
    return control.report()
