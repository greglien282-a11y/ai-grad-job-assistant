"""Independent DeepSeek HTTP protocol implementation, default permanently blocked.

C-0 only exposes exercise_offline with exact httpx.MockTransport + fake resolver.
The production invoke entry has NO grant/key/environment escape hatch.
"""
import asyncio
from dataclasses import dataclass, field
import hmac
import math
import time

import httpx

from app.cost_ledger import canonical, digest
from app.deepseek_contract import ENDPOINT, FAKE_SECRET, ProbeError, check_request, decode_official
from app.probe_control import ProbeControl
from app.models import utcnow


@dataclass(frozen=True)
class TimeLimits:
    connect: float = 5
    read: float = 15
    total: float = 45
    def __post_init__(self):
        for n,cap in ((self.connect,5),(self.read,15),(self.total,45)):
            if type(n) not in (int,float) or not math.isfinite(n) or not 0<n<=cap:raise ProbeError('timeout_invalid')


class DisabledSecretResolver:
    def resolve(self,binding):raise ProbeError('secret_resolution_disabled_c0')


@dataclass(repr=False)
class FakeSecretResolver:
    value: str = field(default=FAKE_SECRET,repr=False)
    def resolve(self,binding):
        # Deliberately NOT a real secret loader. No environment or filesystem.
        if self.value!=FAKE_SECRET or not hmac.compare_digest(digest(self.value),binding):raise ProbeError('fake_key_binding_invalid')
        return self.value
    def __repr__(self):return 'FakeSecretResolver(<redacted>)'


class DeniedNetworkTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self,request):raise ProbeError('network_disabled_c0')


class DeepSeekOfficialTransport:
    """Never registered with the user API or legacy Scripted Provider boundary."""
    def __init__(self,*,endpoint=ENDPOINT,limits=None):
        if endpoint!=ENDPOINT:raise ProbeError('endpoint_not_allowlisted')
        self.endpoint=ENDPOINT;self.limits=limits or TimeLimits()

    async def invoke(self,*args,**kwargs):
        # Happens before resolver/client/DB/DNS, regardless of ambient API keys.
        raise ProbeError('live_dispatch_disabled_c0')

    def client_options(self):
        return {'timeout':httpx.Timeout(connect=self.limits.connect,read=self.limits.read,write=5,pool=5),
                'follow_redirects':False,'trust_env':False,'event_hooks':{},
                'limits':httpx.Limits(max_connections=2,max_keepalive_connections=0)}

    async def _post_once(self,body,secret,wire_transport):
        # Defense in depth: even a direct internal call cannot use a socket.
        if type(wire_transport) is not httpx.MockTransport or secret!=FAKE_SECRET:raise ProbeError('offline_wire_required')
        options=self.client_options()
        try:
            # The deadline includes connection, keep-alive bytes, body and close.
            async with asyncio.timeout(self.limits.total):
                async with httpx.AsyncClient(transport=wire_transport,**options) as client:
                    async with client.stream('POST',ENDPOINT,content=body,headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'}) as response:
                        status=response.status_code
                        if 300<=status<400:raise ProbeError('redirect_refused')
                        if status==429:raise ProbeError('http_429')
                        if status>=500:raise ProbeError('http_5xx')
                        if status!=200:raise ProbeError('http_4xx')
                        chunks=[];size=0
                        async for chunk in response.aiter_bytes():
                            size+=len(chunk)
                            if size>262144:raise ProbeError('body_too_large')
                            chunks.append(chunk)
                        return b''.join(chunks)
        except (TimeoutError,httpx.TimeoutException):raise ProbeError('timeout') from None
        except httpx.HTTPError:raise ProbeError('transport_error') from None
        except ProbeError:raise
        except asyncio.CancelledError:raise
        except Exception:raise ProbeError('transport_error') from None

    async def exercise_offline(self,control,grant_id,request,operation,batch_tag,*,resolver,wire_transport):
        # No real-mode parameter, no externally provided httpx.Client/SDK, no proxy.
        if type(control) is not ProbeControl or type(resolver) is not FakeSecretResolver or type(wire_transport) is not httpx.MockTransport:
            raise ProbeError('offline_components_required')
        policy=control.fixture_policy(grant_id)
        check_request(request,policy,utcnow())
        secret=resolver.resolve(policy.key_binding)
        aid,_=control.prepare(grant_id,request,operation,batch_tag,expected_policy_hash=digest(canonical(policy.model_dump(mode='json'))))
        if not control.permit_fixture_send(aid,request):return aid,None
        try:
            # A second local expiry check; still never grants a live network path.
            policy=control.fixture_policy(grant_id)
            deadline=time.monotonic()+self.limits.total
            raw=await self._post_once(request.body,secret,wire_transport)
            envelope=decode_official(raw,policy)
            if time.monotonic()>=deadline:raise ProbeError('timeout')
            control.received(aid,envelope.usage)
            if control.get(aid)['state']!='response_received':return aid,None
            return aid,envelope
        except asyncio.CancelledError:
            control.unknown(aid,'cancelled');raise
        except ProbeError as error:
            control.unknown(aid,str(error));return aid,None
        # Abrupt process death leaves durable sent. Recovery never invokes HTTP.
