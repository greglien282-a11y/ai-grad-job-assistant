"""C-1B offline HTTP orchestration. No public-network execution path exists.

Only fixed synthetic byte payloads, a restricted test LOGIN, and exact in-memory
HTTPX MockTransport are accepted. No owner factory, secret loader or retries.
"""
import asyncio
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import time
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import AwareDatetime, Field
from sqlalchemy.exc import SQLAlchemyError

from app.cost_ledger import canonical, digest
from app.deepseek_contract import (Frozen, SyntheticRequest, synthetic_requests, ProbeError,
    ENDPOINT, MODEL, VERSION, REGION, FAKE_SECRET, decode_official)
from app.deepseek_transport import DeepSeekOfficialTransport, TimeLimits
from app.mining_context import MiningContext
from app.mining_provider import MiningOutputV2
from app.mining_validation import validate_context_v2
from app.models import utcnow
from app.paid_control import PaidControl, PaidPolicy


class SecretRef(Frozen):
    provider: str = 'deepseek_official'
    account_ref: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    name: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')

    def fingerprint(self): return digest(canonical(self.model_dump(mode='json')))


class ProductionSecretResolver(Protocol):
    """Design contract ONLY, no implementation or Bridge injection path.

    A future isolated broker must verify the committed permit, account, ref,
    expiry/revocation and byte/policy binding itself before releasing a secret.
    This interface alone confers no resolution/dispatch authority.
    """
    def resolve(self, reference: SecretRef, *, grant_id: UUID, call_id: UUID,
                request_sha: str, policy_sha: str) -> str: ...


class BoundFakeSecretResolver(Frozen):
    """Metadata-bound PUBLIC fake, never environment/.env/vault access.

    The C-0 FakeSecretResolver binds a fake value hash. This one binds a
    SecretRef/account/provider and expiry. Neither is a production resolver.
    DisabledSecretResolver continues rejecting ALL resolution elsewhere.
    """
    reference: SecretRef = Field(repr=False)
    expires_at: AwareDatetime
    revoked: bool = False

    def check(self, reference, policy, now):
        if (self.revoked or self.expires_at <= now or reference != self.reference
            or reference.provider != policy.provider or reference.account_ref != policy.account_ref
            or not hmac.compare_digest(reference.fingerprint(), policy.secret_ref_digest)):
            raise ProbeError('bridge_secret_binding_invalid')

    def resolve_fake(self, reference, policy):
        self.check(reference, policy, utcnow())
        return FAKE_SECRET


class BridgeProfile(Frozen):
    provider: str = 'deepseek_official'
    endpoint: str = ENDPOINT
    model: str = MODEL
    expected_version: str = VERSION
    region: str = REGION
    mode: str = 'chat_non_thinking_json_object'
    output_cap: int = Field(strict=True, gt=0, le=1200)
    request_sha: str = Field(pattern=r'^[a-f0-9]{64}$')
    policy_sha: str = Field(pattern=r'^[a-f0-9]{64}$')
    secret_ref: SecretRef = Field(repr=False)


class ResponseLimits(Frozen):
    input_upper_bound: int = Field(strict=True, gt=0, le=12000)
    output_cap: int = Field(strict=True, gt=0, le=1200)


def synthetic_request(case_id='S03', turn_key='b', output_cap=256):
    for request in synthetic_requests(output_cap):
        if (request.case_id, request.turn_key) == (case_id, turn_key): return request
    raise ProbeError('bridge_synthetic_case_missing')


def bind_bytes(request, policy, profile):
    """No reserialization or JSON repair: freeze and compare original bytes."""
    if type(request) is not SyntheticRequest or type(request.body) is not bytes:
        raise ProbeError('bridge_payload_invalid')
    body = request.body  # immutable bytes; later changes to caller object cannot replace this buffer
    try:
        body.decode('utf8', errors='strict')
        approved = synthetic_request(request.case_id, request.turn_key, profile.output_cap)
        sha = hashlib.sha256(body).hexdigest()
        if body != approved.body or sha != profile.request_sha:
            raise ProbeError('bridge_payload_not_approved')
        if tuple(getattr(profile, k) for k in ('provider','endpoint','model','expected_version','region','mode','output_cap')) != tuple(
                getattr(policy, k) for k in ('provider','endpoint','model','expected_version','region','mode','output_cap')):
            raise ProbeError('bridge_profile_changed')
        if digest(canonical(policy.model_dump(mode='json'))) != profile.policy_sha:
            raise ProbeError('bridge_policy_changed')
        if profile.secret_ref.provider != policy.provider or profile.secret_ref.account_ref != policy.account_ref or profile.secret_ref.fingerprint() != policy.secret_ref_digest:
            raise ProbeError('bridge_secret_binding_invalid')
        certificate = next((c for c in policy.certificates if c.request_sha == sha), None)
        if certificate is None: raise ProbeError('bridge_payload_not_approved')
        parsed = json.loads(body)
        if (parsed['model'] != MODEL or parsed['stream'] is not False or parsed['thinking'] != {'type':'disabled'}
            or parsed['response_format'] != {'type':'json_object'} or type(parsed['max_tokens']) is not int
            or parsed['max_tokens'] != profile.output_cap):
            raise ProbeError('bridge_profile_changed')
        context = MiningContext.model_validate_json(parsed['messages'][1]['content'])
        return SyntheticRequest(request.case_id, request.turn_key, body), context, ResponseLimits(
            input_upper_bound=certificate.input_bound, output_cap=policy.output_cap)
    except ProbeError: raise
    except Exception: raise ProbeError('bridge_payload_invalid') from None


SAFE_CODES = frozenset({
    'bridge_components_invalid','bridge_payload_invalid','bridge_payload_not_approved','bridge_profile_changed',
    'bridge_policy_changed','bridge_secret_binding_invalid','bridge_policy_invalid','bridge_policy_digest_invalid',
    'bridge_isolated_database_required','bridge_restricted_login_required','paid_ledger_identity_mismatch',
    'paid_grant_inactive','paid_rate_expired','paid_token_bound_unproven','paid_synthetic_manifest_required',
    'paid_profile_not_allowlisted','paid_price_binding_invalid','bridge_source_invalid','bridge_ledger_error',
    'paid_idempotency_conflict','paid_budget_exceeded','paid_scope_exceeded','paid_pool_blocked',
    'paid_call_limit','paid_concurrency_exceeded','paid_configuration_changed','paid_lease_expired',
    'timeout','transport_error','http_4xx','http_429','http_5xx','redirect_refused','body_too_large',
    'model_drift','refused','truncated','unexpected_mode','usage_exceeded','response_invalid',
    'bridge_validation_failed','bridge_state_unknown','bridge_unknown_not_persisted',
})


def safe_error(error):
    if isinstance(error, ProbeError):
        value = str(error)
        return value if value in SAFE_CODES else 'bridge_validation_failed'
    if isinstance(error, SQLAlchemyError):
        value = getattr(getattr(getattr(error, 'orig', None), 'diag', None), 'message_primary', None)
        return value if value in SAFE_CODES else 'bridge_ledger_error'
    return 'bridge_validation_failed'


@dataclass(frozen=True)
class BridgeResult:
    code: str
    call_id: str | None = None
    state: str | None = None
    output: MiningOutputV2 | None = field(default=None, repr=False)

    def diagnostic(self):
        # Never export response text, requests, credentials, raw errors or bills.
        return dict(mode='offline_http_fixture', code=self.code, call_id=self.call_id, state=self.state,
                    candidates=len(self.output.candidates) if self.output else 0,
                    questions=len(self.output.questions) if self.output else 0,
                    real_requests=0, real_cost_cny='0', real_quality=None, real_latency_ms=None)


class DeepSeekBridge:
    async def invoke(self, *args, **kwargs):
        # There is deliberately no enabled flag / live resolver / live client.
        raise ProbeError('live_dispatch_disabled_c1b')

    def recover_offline(self, control, call_id):
        """Explicit read-only recovery even after grant revocation/expiry."""
        if type(control) is not PaidControl: return BridgeResult('bridge_components_invalid')
        try:
            control.assert_offline_runtime()
            return BridgeResult('recovered_read_only', str(call_id), control.get(call_id)['state'])
        except Exception as error: return BridgeResult(safe_error(error))

    async def exercise_offline(self, control, grant_id, request, operation, batch_tag, *, profile, resolver, wire_transport, transport=None):
        if (type(control) is not PaidControl or type(profile) is not BridgeProfile
            or type(resolver) is not BoundFakeSecretResolver or type(wire_transport) is not httpx.MockTransport
            or (transport is not None and type(transport) is not DeepSeekOfficialTransport)):
            return BridgeResult('bridge_components_invalid')
        transport = transport or DeepSeekOfficialTransport()
        if type(transport.limits) is not TimeLimits: return BridgeResult('bridge_components_invalid')
        call_id = None; sent = False
        try:
            control.assert_offline_runtime()
            policy = control.checked_policy(grant_id)
            frozen, context, limits = bind_bytes(request, policy, profile)
            if transport.endpoint != profile.endpoint: raise ProbeError('bridge_profile_changed')
            resolver.check(profile.secret_ref, policy, utcnow())  # metadata only, NOT secret resolution
            row = control.reserve(grant_id, frozen, operation, batch_tag, profile.policy_sha)
            call_id = row['id']
            if not row['created']:
                return BridgeResult('recovered_read_only', call_id, control.get(call_id)['state'])
            policy = control.checked_policy(grant_id)
            frozen, context, limits = bind_bytes(frozen, policy, profile)
            resolver.check(profile.secret_ref, policy, utcnow())
            if not control.transition(call_id, 'permit', profile.request_sha, profile.policy_sha)['permitted']:
                return BridgeResult('recovered_read_only', call_id, control.get(call_id)['state'])
            sent = True  # transaction has committed, NOT proof supplier ran once
            # Re-check immediately after the irreversible intent, before loading
            # even the public fake secret. Expiry/revocation here means unknown.
            policy = control.checked_policy(grant_id)
            frozen, context, limits = bind_bytes(frozen, policy, profile)
            secret = resolver.resolve_fake(profile.secret_ref, policy)
            deadline = time.monotonic() + transport.limits.total
            raw = await transport._post_once(frozen.body, secret, wire_transport)
            envelope = decode_official(raw, limits)
            try: output = validate_context_v2(context, envelope.output)
            except Exception: raise ProbeError('bridge_source_invalid') from None
            if time.monotonic() >= deadline: raise ProbeError('timeout')
            control.transition(call_id, 'received', usage=dict(input_tokens=envelope.usage['input'], output_tokens=envelope.usage['output']))
            state = control.get(call_id)['state']
            if state != 'response_received': return BridgeResult('bridge_state_unknown', call_id, state)
            # No business publication, no invoice/reconcile, full reserve held.
            return BridgeResult('validated_offline', call_id, state, output)
        except asyncio.CancelledError:
            if sent: self._unknown(control, call_id)
            raise asyncio.CancelledError() from None
        except Exception as error:
            code = safe_error(error)
            if sent:
                persisted = self._unknown(control, call_id)
                return BridgeResult(code if persisted else 'bridge_unknown_not_persisted', call_id, 'unknown')
            # A DB commit error can be ambiguous: do not resend, repair or retry.
            return BridgeResult(code, call_id, 'reserved_or_unresolved' if call_id else None)
        # Hard process termination / BaseException leaves durable sent. Only
        # GET projection and explicit ledger recovery can classify it afterward.

    @staticmethod
    def _unknown(control, call_id):
        try:
            control.transition(call_id, 'unknown')
            return True
        except Exception:
            return False  # retain prior durable sent/received; no retry or refund
