"""Read-only C-1C evidence assessment, NOT a certificate issuer or dispatcher.

No database, environment, secret, HTTP or PaidControl operations. Hypothetical
native-currency arithmetic below must never be used as a reservation amount.
The reviewed registry currently contains NO accepted hard-bound strategy.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
from typing import Literal

from app.deepseek_bridge import synthetic_request


PROBE_SHA = '5cc2def4f875e43760e799678a43c1f2d2072dd4245eaf54457dfe78ee0b373e'
STRATEGIES = ('tokenizer_framing', 'context_window')


@dataclass(frozen=True)
class BoundaryAssessment:
    strategy: str
    blockers: tuple[str, ...]

    @property
    def dispatch_allowed(self) -> Literal[False]:
        return False

    @property
    def verified_input_upper_bound(self) -> None:
        return None

    @property
    def verified_maximum_cost(self) -> None:
        return None


def assess_boundary(*, strategy: str, body: bytes,
                    claimed_input_bound: int | None = None,
                    evidence_kind: str | None = None) -> BoundaryAssessment:
    """Assess an untrusted proposal; claims/attestations cannot register proof.

    Checks the bytes themselves against the pinned synthetic fixture. Extra
    claims are deliberately NOT reflected in diagnostics (may be sensitive).
    Accepting any strategy later requires a separately reviewed code change,
    authoritative evidence and paid-control integration; there is no flag.
    """
    blockers = []
    if (type(body) is not bytes or hashlib.sha256(body).hexdigest() != PROBE_SHA
            or body != synthetic_request().body):
        blockers.append('request_bytes_not_pinned')
    if strategy not in STRATEGIES:
        blockers.append('unsupported_strategy')
    elif strategy == 'tokenizer_framing':
        blockers.extend(('online_tokenizer_version_unproven', 'billable_framing_unproven'))
    else:
        blockers.extend(('context_unit_unproven', 'context_to_billed_tokens_unproven',
                         'chat_overflow_billing_unproven'))
    if claimed_input_bound is not None or evidence_kind is not None:
        blockers.append('caller_claim_is_not_a_certificate')
    blockers.extend(('no_accepted_bound_certificate', 'account_currency_unverified',
                     'approved_price_window_missing', 'real_authorization_zero',
                     'production_dispatch_unimplemented'))
    return BoundaryAssessment(strategy if strategy in STRATEGIES else 'unsupported', tuple(blockers))


@dataclass(frozen=True)
class ConditionalScenario:
    """Observation + assumptions, NOT an approved price or verified upper bound."""
    currency: Literal['CNY', 'USD']
    assumed_context_tokens: int
    output_cap: int
    hypothetical_native_cost: Decimal

    @property
    def certified(self) -> Literal[False]:
        return False


def conditional_context_scenario(currency: str, context_tokens: int) -> ConditionalScenario:
    # Fixed 2026-10-15 observations, cache-miss PEAK only. No FX or tax defaults.
    # Restrict to the two explicitly documented interpretations under discussion;
    # callers cannot reduce a speculative bound to fit a preferred budget.
    if currency not in ('CNY', 'USD') or type(context_tokens) is not int or context_tokens not in (1_000_000, 1_048_576):
        raise ValueError('unsupported_conditional_scenario')
    input_price, output_price = (Decimal('2'), Decimal('8')) if currency == 'CNY' else (Decimal('0.30'), Decimal('1.20'))
    amount = (Decimal(context_tokens) * input_price + Decimal(256) * output_price) / Decimal(1_000_000)
    return ConditionalScenario(currency, context_tokens, 256, amount)
