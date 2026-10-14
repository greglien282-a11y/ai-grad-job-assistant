"""Design-only offline checks: no transport, keys, env reads or DB connections.

Run: apps/api/.venv/Scripts/python.exe scripts/check_m12c2_contracts.py
The budget below is an in-memory test double, NOT the production approval/ledger.
"""
import copy
import json
import sys
import unittest
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))
from app.mining_provider import MiningOutputV2
from app.mining_validation import atomic, sentence_spans

DATA = ROOT / 'docs/evaluation'


def load_cases():
    data = json.loads((DATA / 'm12c2-synthetic-cases.json').read_text(encoding='utf-8'))
    if len(data['cases']) != 12 or any(c['synthetic'] is not True for c in data['cases']):
        raise ValueError('Only the reviewed twelve synthetic cases are permitted')
    return data['cases']


def wire_schema():
    schema = copy.deepcopy(MiningOutputV2.model_json_schema())
    # Usage comes from the transport envelope/invoice, never model JSON claims.
    for field in ('tokens_in', 'tokens_out'): schema['properties'].pop(field)
    def clean(node):
        if isinstance(node, dict):
            node.pop('default', None);node.pop('title', None)
            if node.get('type') == 'object':
                node['additionalProperties'] = False
                node['required'] = list(node.get('properties', {}))
            for value in node.values(): clean(value)
        elif isinstance(node, list):
            for value in node: clean(value)
    clean(schema)
    return schema


def no_duplicate_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data: raise ValueError('Duplicate JSON key')
        data[key] = value
    return data


def decode_mock(body):
    parsed = json.loads(body, object_pairs_hook=no_duplicate_keys)
    if not isinstance(parsed, dict) or set(parsed) != {'schema_version', 'candidates', 'questions', 'stop', 'stop_reason'}:
        raise ValueError('Unexpected wire fields/missing fields')
    return MiningOutputV2.model_validate({**parsed, 'tokens_in': 0, 'tokens_out': 0})


def estimate(input_bound, output_cap, input_rate, output_rate, *, currency='CNY', fx=None):
    if input_bound < 0 or output_cap < 0: raise ValueError('Negative usage')
    if currency not in ('CNY', 'USD'): raise ValueError('Unknown currency')
    if currency == 'USD' and (fx is None or not Decimal(fx).is_finite() or Decimal(fx) <= 0): raise ValueError('Reviewed FX required')
    rates = [Decimal(input_rate), Decimal(output_rate)]
    if any(not r.is_finite() or r < 0 for r in rates): raise ValueError('Invalid rate')
    cost = (Decimal(input_bound)*rates[0] + Decimal(output_cap)*rates[1]) / Decimal(1000000)
    if currency == 'USD': cost *= Decimal(fx)
    return cost.quantize(Decimal('0.000001'), rounding=ROUND_CEILING)


class BudgetDouble:
    """Atomicity is simulated sequentially; DB locks/multi-process still unimplemented."""
    def __init__(self, approved=False, global_limit='30', session_limit='2', call_limit='0.5', provider_limit='18', model_limit='18'):
        self.approved = approved
        self.limits = dict(global_=Decimal(global_limit), session=Decimal(session_limit), call=Decimal(call_limit), provider=Decimal(provider_limit), model=Decimal(model_limit))
        self.rows = {}

    def exposure(self, scope=None, value=None):
        rows = self.rows.values() if scope is None else (r for r in self.rows.values() if r[scope] == value)
        return sum((r['cost'] if r['state'] == 'reconciled' else r['held'] for r in rows), Decimal(0))

    def reserve(self, call_id, amount, provider='deepseek_official', model='DeepSeek-V4.1-Flash', session='synthetic-session'):
        amount = Decimal(amount)
        if not self.approved: raise ValueError('Approval absent: no spending permitted')
        if not amount.is_finite() or amount < 0: raise ValueError('Invalid reservation')
        if call_id in self.rows:
            old = self.rows[call_id]
            if (old['held'], old['provider'], old['model'], old['session']) != (amount, provider, model, session): raise ValueError('Operation mismatch')
            return False  # Never re-dispatch even if an earlier result is unknown.
        if amount > self.limits['call'] or self.exposure() + amount > self.limits['global_']: raise ValueError('Budget exceeded')
        for scope, value in [('session', session), ('provider', provider), ('model', model)]:
            if self.exposure(scope, value) + amount > self.limits[scope]: raise ValueError('Scoped budget exceeded')
        self.rows[call_id] = dict(held=amount, cost=None, state='reserved', provider=provider, model=model, session=session)
        return True

    def unknown(self, call_id):
        row = self.rows[call_id]
        if row['state'] not in ('reserved', 'unknown'): raise ValueError('Cannot erase a reconciled bill')
        row['state'] = 'unknown'

    def reconcile(self, call_id, invoice_cost):
        cost = Decimal(invoice_cost)
        if not cost.is_finite() or cost < 0: raise ValueError('Invalid invoice')
        row = self.rows[call_id]
        if row['state'] == 'reconciled':
            if cost != row['cost']: raise ValueError('Conflicting invoice requires audit')
            return
        row['cost'], row['state'] = cost, 'reconciled'
        if cost > row['held'] or self.exposure() > self.limits['global_']:
            self.approved = False  # Freeze, record overrun; never pretend it fit.


class ContractTests(unittest.TestCase):
    def test_twelve_cases_have_exact_codepoint_golds(self):
        cases = load_cases()
        self.assertEqual(len({c['id'] for c in cases}), 12)
        for case in cases:
            keys = set()
            for step in case['steps']:
                if step['kind'] != 'user': continue
                self.assertNotIn(step['turn_key'], keys);keys.add(step['turn_key'])
                self.assertLessEqual(len(step['question_goals']), 2)
                for c in step['gold_candidates']:
                    self.assertEqual(step['text'][c['start']:c['end']], c['quote'])
                    self.assertIn((c['start'], c['end'], c['quote']), set(sentence_spans(step['text'])))

    def test_wire_snapshot_matches_design(self):
        actual = json.loads((DATA/'provider-wire-output.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(actual, wire_schema())
        self.assertNotIn('tokens_in', actual['properties'])
        self.assertFalse(actual['additionalProperties'])

    def test_mock_packets_pass_existing_model_schema(self):
        for case in load_cases():
            for step in case['steps']:
                if step['kind'] != 'user': continue
                tid = str(uuid5(NAMESPACE_URL, 'synthetic/'+case['id']+'/'+step['turn_key']))
                packet = dict(schema_version=2, candidates=[{'citation': {'turn_id': tid, **q}} for q in step['gold_candidates']],
                    questions=[] if step['allow_stop'] else [{'text':'请补充你本人做过的部分？', 'purpose':'contribution', 'source_turn_ids':[tid]}],
                    stop=step['allow_stop'], stop_reason='user_uncertain' if step['allow_stop'] else None)
                result = decode_mock(json.dumps(packet, ensure_ascii=False))
                self.assertEqual(result.tokens_in, 0)
                # This checks shape/literals only; existing DB validate_v2 remains
                # mandatory for real run/session/source/revision validation.

    def test_invalid_and_duplicate_json_no_repair_or_retry(self):
        for body in ('```json {} ```', '{"schema_version":2,"schema_version":1}', '{', '{"status":"user_confirmed"}'):
            with self.assertRaises(ValueError): decode_mock(body)

    def test_profiles_are_disabled_and_versions_are_honest(self):
        config = json.loads((DATA/'m12c2-profile-drafts.json').read_text(encoding='utf-8'))
        self.assertFalse(config['real_model_enabled']);self.assertIsNone(config['approval'])
        self.assertEqual(Decimal(config['approved_budget_cny']), 0)
        self.assertTrue(all(not p['enabled'] and not p['actually_verified'] for p in config['profiles']))
        self.assertFalse(config['automatic_retry']);self.assertFalse(config['automatic_provider_fallback'])
        self.assertEqual(config['profiles'][0]['api_model'], 'deepseek-flash')
        self.assertIn('not_immutable', config['profiles'][0]['version_policy'])

    def test_thirty_yuan_draft_is_not_permission(self):
        with self.assertRaises(ValueError): BudgetDouble().reserve('a','0.01')

    def test_fee_math_and_unknown_fx_fail_closed(self):
        self.assertEqual(estimate(6000,1200,'2','8'), Decimal('0.021600'))
        with self.assertRaises(ValueError): estimate(6000,1200,'0.3','1.2',currency='USD')
        with self.assertRaises(ValueError): estimate(6000,1200,'NaN','8')

    def test_unknown_bill_keeps_exposure_and_same_call_never_redispatches(self):
        ledger = BudgetDouble(approved=True,global_limit='0.04')
        self.assertTrue(ledger.reserve('a','0.03'));ledger.unknown('a')
        self.assertFalse(ledger.reserve('a','0.03'))
        self.assertEqual(ledger.exposure(), Decimal('0.03'))
        with self.assertRaises(ValueError): ledger.reserve('b','0.02',provider='bailian',model='Qwen3.7-Plus')
        ledger.reconcile('a','0.01');ledger.reconcile('a','0.01')
        self.assertEqual(ledger.exposure(),Decimal('0.01'))

    def test_scope_caps_apply_across_providers(self):
        ledger = BudgetDouble(approved=True,session_limit='0.04')
        ledger.reserve('a','0.03')
        with self.assertRaises(ValueError): ledger.reserve('b','0.02',provider='bailian',model='Qwen3.7-Plus')
        ledger = BudgetDouble(approved=True,provider_limit='0.03',model_limit='0.03')
        ledger.reserve('a','0.03')
        with self.assertRaises(ValueError): ledger.reserve('b','0.01',session='different')

    def test_overrun_is_recorded_and_frozen(self):
        ledger = BudgetDouble(approved=True)
        ledger.reserve('a','0.01');ledger.reconcile('a','0.02')
        self.assertFalse(ledger.approved);self.assertEqual(ledger.exposure(),Decimal('0.02'))
        with self.assertRaises(ValueError): ledger.reserve('b','0.01')

    def test_mock_timeout_sends_once_without_cross_provider_fallback(self):
        ledger = BudgetDouble(approved=True)
        calls = []
        def purely_local_timeout():
            calls.append('deepseek_official');raise TimeoutError('Synthetic outcome unknown')
        for _ in range(2):
            if ledger.reserve('same-operation','0.03'):
                try: purely_local_timeout()
                except TimeoutError: ledger.unknown('same-operation')
        self.assertEqual(calls,['deepseek_official'])
        self.assertEqual(ledger.exposure(),Decimal('0.03'))

    def test_reconciled_cost_cannot_be_erased_by_late_unknown(self):
        ledger = BudgetDouble(approved=True)
        ledger.reserve('a','0.03');ledger.reconcile('a','0.02')
        with self.assertRaises(ValueError): ledger.unknown('a')
        self.assertEqual(ledger.exposure(),Decimal('0.02'))


def main():
    # Network prohibition is a local check, not a promise of installed production
    # egress control. This design checker has no real-provider execution path.
    with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')), patch('socket.getaddrinfo', side_effect=AssertionError('Network forbidden')):
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests))
        if not result.wasSuccessful(): return 1
        cases = load_cases()
        diagnostics = []
        for case in cases:
            for step in case['steps']:
                if step['kind'] != 'user': continue
                gold = {q['quote'] for q in step['gold_candidates']}
                for _, _, sentence in sentence_spans(step['text']):
                    if atomic(sentence) and sentence not in gold: diagnostics.append({'case':case['id'], 'turn':step['turn_key'], 'finding':'lexical acceptance exceeds human gold; review before real enablement'})
                    if sentence in gold and not atomic(sentence): diagnostics.append({'case':case['id'], 'turn':step['turn_key'], 'finding':'human gold rejected by lexical guard; review before real enablement'})
        print(json.dumps({'mode':'offline_mock_contracts', 'cases':12, 'tests_passed':result.testsRun, 'vendor_requests':0, 'actual_cost_cny':'0.000000',
            'real_model_quality':None, 'provider_latency_ms':None, 'actual_tokens':None, 'known_semantic_diagnostics':diagnostics}, ensure_ascii=False))
    return 0


if __name__ == '__main__': raise SystemExit(main())
