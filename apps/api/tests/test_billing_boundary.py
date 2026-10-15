"""C-1C: missing evidence never becomes a certificate or paid permission."""
import asyncio
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from app.billing_boundary import assess_boundary, conditional_context_scenario, PROBE_SHA
from app.deepseek_bridge import DeepSeekBridge, synthetic_request
from app.deepseek_contract import ProbeError
from app.deepseek_transport import DeepSeekOfficialTransport


@pytest.mark.parametrize('strategy', ['tokenizer_framing', 'context_window', 'owner_approved'])
@pytest.mark.parametrize('bound,kind', [(None, None), (5000, 'owner_attested'),
                                      (1_000_000, 'official_context'), (1_048_576, 'vendor_guaranteed')])
def test_no_claim_can_enable_unproven_strategy(strategy, bound, kind):
    result = assess_boundary(strategy=strategy, body=synthetic_request().body,
                             claimed_input_bound=bound, evidence_kind=kind)
    assert result.dispatch_allowed is False
    assert result.verified_input_upper_bound is None
    assert result.verified_maximum_cost is None
    assert 'no_accepted_bound_certificate' in result.blockers
    assert 'real_authorization_zero' in result.blockers


@pytest.mark.parametrize('body', [b'', b'private synthetic error must not echo', bytearray(b'{}')])
def test_actual_bytes_not_supplied_hash_are_checked_without_echo(body):
    result = assess_boundary(strategy='context_window', body=body)
    assert 'request_bytes_not_pinned' in result.blockers
    assert 'private' not in repr(result)


def test_pinned_request_and_no_output_cap_subtraction():
    body = synthetic_request().body
    assert hashlib.sha256(body).hexdigest() == PROBE_SHA
    parsed = json.loads(body)
    assert parsed['max_tokens'] == 256 and parsed['stream'] is False
    assert parsed['thinking'] == {'type': 'disabled'}
    assert parsed['response_format'] == {'type': 'json_object'}
    # Output cap is not a promise of 256 generated tokens: I <= C, not C-256.
    assert conditional_context_scenario('CNY', 1_000_000).hypothetical_native_cost == Decimal('2.002048')


@pytest.mark.parametrize('currency,context,amount', [
    ('CNY', 1_000_000, '2.002048'), ('CNY', 1_048_576, '2.099200'),
    ('USD', 1_000_000, '0.3003072'), ('USD', 1_048_576, '0.3148800')])
def test_native_currency_conditional_arithmetic_is_not_certified(currency, context, amount):
    scenario = conditional_context_scenario(currency, context)
    assert scenario.currency == currency and scenario.certified is False
    assert scenario.hypothetical_native_cost == Decimal(amount)
    if currency == 'CNY':
        assert scenario.hypothetical_native_cost > Decimal('0.05')


@pytest.mark.parametrize('currency,context', [('zh-cn', 1_000_000), ('en', 1_000_000),
    ('CNY', 5000), ('USD', True), ('CNY', 1_000_000.0), ('EUR', 1_000_000)])
def test_language_fx_or_small_estimate_cannot_select_billing(currency, context):
    with pytest.raises(ValueError, match='unsupported_conditional_scenario'):
        conditional_context_scenario(currency, context)


def test_ambient_fake_key_does_not_open_either_real_entrypoint(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'public-fake-not-a-real-key')
    monkeypatch.setenv('AI_ENABLED', 'true')
    async def check():
        # Create the event loop first (Windows uses an internal socketpair).
        # All subsequent socket/secret access is a trap, not a fake success.
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')), \
             patch('app.deepseek_bridge.BoundFakeSecretResolver.resolve_fake', side_effect=AssertionError('secret forbidden')):
            for target in (DeepSeekBridge(), DeepSeekOfficialTransport()):
                with pytest.raises(ProbeError, match='live_dispatch_disabled'):
                    await target.invoke()
    asyncio.run(check())


def test_cli_is_read_only_blocked_and_contains_no_approved_bound():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, str(root/'scripts/check_deepseek_billing_boundary.py')],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report['real_requests'] == 0 and report['approved_cny'] == '0'
    assert report['dispatch_allowed'] is False and report['verified_maximum_cost'] is None
    assert all(s['certified'] is False for s in report['conditional_scenarios'])


def test_evidence_manifest_cannot_claim_an_approved_strategy_or_currency():
    root = Path(__file__).resolve().parents[3]
    evidence = json.loads((root/'docs/evaluation/deepseek-c1c-billing-evidence.json').read_text(encoding='utf8'))
    assert evidence['approved_bound_strategies'] == []
    assert evidence['approved_real_calls'] == 0 and evidence['approved_real_cny'] == '0'
    assert evidence['verified_input_upper_bound'] is None
    assert evidence['verified_maximum_cost'] is None
    assert evidence['probe_sha256'] == PROBE_SHA
    prices = evidence['observed_prices_not_approved']
    assert prices['account_settlement_currency'] is None and prices['approved_fx'] is None
    assert prices['valid_until'] is None and prices['approved_tax_margin'] is None
    for currency in ('CNY', 'USD'):
        price = prices[currency]
        expected = (Decimal(price['cache_miss_peak']) * 1_000_000 + Decimal(price['output_peak']) * 256) / Decimal(1_000_000)
        assert conditional_context_scenario(currency, 1_000_000).hypothetical_native_cost == expected
