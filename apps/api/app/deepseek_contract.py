"""C-0 official contract: synthetic allowlist and strict document-shaped decoding.

No keys, environment, network or user DB reads. Document compliance is not live
verification; alias/fingerprint never proves immutable weights.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime
from app.cost_ledger import canonical, digest, money
from app.model_adapter import Adapter, Profile, Envelope, parse_output, unique_pairs
from app.mining_context import MiningContext, UserContext, StopContext, redact
from app.mining_provider import MiningOutputV2

ENDPOINT='https://api.deepseek.com/chat/completions'
MODEL='deepseek-flash'
VERSION='DeepSeek-V4.1-Flash'
REGION='provider_managed_unverified'
ROOT=Path(__file__).resolve().parents[3]
FAKE_SECRET='c0-fake-secret-not-a-provider-key'


class ProbeError(ValueError): pass


class Frozen(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)


class PriceSnapshot(Frozen):
    # USD values are evidence in fixtures, NOT authorization to incur charges.
    source_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    expires_at: AwareDatetime
    peak_miss: Decimal = Field(ge=0,le=100)
    offpeak_miss: Decimal = Field(ge=0,le=100)
    peak_hit: Decimal = Field(ge=0,le=100)
    offpeak_hit: Decimal = Field(ge=0,le=100)
    peak_output: Decimal = Field(ge=0,le=100)
    offpeak_output: Decimal = Field(ge=0,le=100)


class FxSnapshot(Frozen):
    source_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    expires_at: AwareDatetime
    cny_per_usd: Decimal = Field(gt=0,le=100)
    tax_margin_factor: Decimal = Field(ge=1,le=2)


class ProbePolicy(Frozen):
    provider: str = 'deepseek_official'
    endpoint: str = ENDPOINT
    model: str = MODEL
    expected_version: str = VERSION
    region: str = REGION
    api_mode: str = 'chat_non_thinking_json_object'
    key_binding: str = Field(pattern=r'^[a-f0-9]{64}$')
    request_hashes: tuple[str,...] = Field(min_length=1,max_length=24)
    input_upper_bound: int = Field(strict=True,gt=0,le=12000)
    output_cap: int = Field(strict=True,gt=0,le=1200)
    token_evidence_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    # Supplier tokenizer/framing proof is NOT verified during C-0.
    token_evidence_kind: str = 'offline_fixture_not_supplier_verified'
    price: PriceSnapshot
    fx: FxSnapshot

    def check(self, now):
        if (self.provider,self.endpoint,self.model,self.expected_version,self.region,self.api_mode)!=(
                'deepseek_official',ENDPOINT,MODEL,VERSION,REGION,'chat_non_thinking_json_object'):
            raise ProbeError('profile_not_allowlisted')
        if self.token_evidence_kind!='offline_fixture_not_supplier_verified':raise ProbeError('token_evidence_unverified')
        if self.price.expires_at<=now or self.fx.expires_at<=now:raise ProbeError('rate_or_fx_expired')
        if self.price.peak_hit>self.price.peak_miss or self.price.offpeak_hit>self.price.offpeak_miss:raise ProbeError('price_invalid')

    def reservation(self):
        # Never assume cache hits or off-peak prices. Decimal, ceil CNY micro-unit.
        usd=(self.input_upper_bound*max(self.price.peak_miss,self.price.offpeak_miss,self.price.peak_hit,self.price.offpeak_hit)
             +self.output_cap*max(self.price.peak_output,self.price.offpeak_output))/Decimal(1000000)
        return money(usd*self.fx.cny_per_usd*self.fx.tax_margin_factor)


@dataclass(frozen=True,repr=False)
class SyntheticRequest:
    case_id: str
    turn_key: str
    body: bytes = field(repr=False)
    @property
    def fingerprint(self):return digest(self.body.decode('utf8'))
    def __repr__(self):return 'SyntheticRequest(<body redacted>)'


def synthetic_requests(output_cap=256):
    if type(output_cap) is not int or output_cap not in (128,256,512,1200):raise ProbeError('output_cap_not_allowlisted')
    data_text=(ROOT/'docs/evaluation/m12c2-synthetic-cases.json').read_text(encoding='utf8')
    wire_text=(ROOT/'docs/evaluation/provider-wire-output.schema.json').read_text(encoding='utf8')
    if digest(data_text)!='a4689b6c8559a9a0d024cf5e07adb9f7cb25a53d143cc633b4761abc30a54c2d' or digest(wire_text)!='6a1b38f86e6250e120d3cf95dc86abc8141bf369b91423abf7f05214995975d5':
        raise ProbeError('synthetic_manifest_changed')
    data=json.loads(data_text);wire=json.loads(wire_text)
    profile=Profile.model_validate(json.loads((ROOT/'docs/evaluation/m12c2-profile-drafts.json').read_text(encoding='utf8'))['profiles'][0])
    adapter=Adapter(profile,wire);result=[]
    for case in data['cases']:
        if case.get('synthetic') is not True:raise ProbeError('dataset_not_synthetic')
        for step in case['steps']:
            if step['kind']!='user':continue
            tid=uuid5(NAMESPACE_URL,'c0:'+case['id']+step['turn_key'])
            ctx=MiningContext(project_id=uuid5(NAMESPACE_URL,'c0:'+case['id']),context_revision=1,input_turn_id=tid,
                user_turns=(UserContext(turn_id=tid,content=redact(step['text'])),),questions=(),facts=(),
                stop=StopContext(round_count=1,consecutive_empty_rounds=0,user_stopped=False,session_ended=False))
            request=adapter.build_request(ctx);request['max_tokens']=output_cap
            result.append(SyntheticRequest(case['id'],step['turn_key'],canonical(request).encode('utf8')))
    return tuple(result)


def check_request(request,policy,now):
    if type(request) is not SyntheticRequest:raise ProbeError('synthetic_request_required')
    policy.check(now)
    # Authorization cannot turn arbitrary user input into approved synthetic data.
    allowed={r.fingerprint for r in synthetic_requests(policy.output_cap)}
    if request.fingerprint not in allowed or request.fingerprint not in policy.request_hashes:raise ProbeError('payload_not_approved')
    body=json.loads(request.body)
    if (body.get('model')!=MODEL or body.get('stream') is not False or body.get('thinking')!={'type':'disabled'}
        or body.get('response_format')!={'type':'json_object'} or type(body.get('max_tokens')) is not int
        or body['max_tokens']>policy.output_cap):raise ProbeError('request_mode_not_allowlisted')
    return body


def decode_official(body,policy):
    # Supplier raw bodies live in memory only and are never forwarded as errors.
    try:
        raw=json.loads(body,object_pairs_hook=unique_pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if raw['object']!='chat.completion' or not isinstance(raw['id'],str) or len(raw['id'])>200:raise ValueError()
        if type(raw['created']) is not int or not isinstance(raw['system_fingerprint'],str):raise ValueError()
        if raw['model'] not in (MODEL,VERSION):raise ProbeError('model_drift')
        if len(raw['choices'])!=1 or type(raw['choices'][0]['index']) is not int or raw['choices'][0]['index']!=0:raise ValueError()
        choice=raw['choices'][0];msg=choice['message'];finish=choice['finish_reason']
        if msg.get('refusal') or finish=='content_filter':raise ProbeError('refused')
        if finish=='length':raise ProbeError('truncated')
        if finish!='stop' or msg['role']!='assistant' or msg.get('tool_calls') or msg.get('reasoning_content'):raise ProbeError('unexpected_mode')
        u=raw['usage']
        counts={k:u[k] for k in ('prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','total_tokens')}
        if any(type(n) is not int or n<0 for n in counts.values()):raise ValueError()
        if u['prompt_tokens']!=u['prompt_cache_hit_tokens']+u['prompt_cache_miss_tokens'] or u['total_tokens']!=u['prompt_tokens']+u['completion_tokens']:raise ValueError()
        if 'prompt_tokens_details' in u and u['prompt_tokens_details'].get('cached_tokens')!=u['prompt_cache_hit_tokens']:raise ValueError()
        reasoning=u.get('completion_tokens_details',{}).get('reasoning_tokens',0)
        if type(reasoning) is not int or reasoning!=0:raise ProbeError('unexpected_mode')
        if u['prompt_tokens']>policy.input_upper_bound or u['completion_tokens']>policy.output_cap:raise ProbeError('usage_exceeded')
        output=parse_output(msg['content'])
        output=MiningOutputV2.model_validate(output.model_dump()|{'tokens_in':u['prompt_tokens'],'tokens_out':u['completion_tokens']})
        # Do not store arbitrary server strings. Hash identifying evidence.
        evidence={'reported_model':raw['model'],'version_confidence':'alias_not_immutable_unverified',
                  'request_id_digest':digest(raw['id']),'fingerprint_digest':digest(raw['system_fingerprint'])}
        return Envelope(output,{'input':u['prompt_tokens'],'cached':u['prompt_cache_hit_tokens'],'uncached':u['prompt_cache_miss_tokens'],
                                'output':u['completion_tokens'],'reasoning':0},evidence)
    except ProbeError:raise
    except Exception:raise ProbeError('response_invalid') from None
