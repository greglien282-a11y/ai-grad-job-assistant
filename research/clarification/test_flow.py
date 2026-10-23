import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from overnight_research.r03 import Claim, Record, Source
from flow import HistoricalFact, begin, explain, request_save

CORPUS = json.loads((ROOT / 'apps/api/tests/overnight_research/r03_cases.json').read_text(encoding='utf8'))['cases']


def arranged(case):
    source = Source('old', 0, 12)
    current = Source('new', 0, len(case['new']))
    if case['source'] == 'overlap': current = Source('old', 0, 7)
    elif case['source'] == 'disjoint': current = Source('old', 20, 27)
    elif case['source'] == 'unknown': source = Source('old')
    snapshots = ((case.get('prior', case['old']), 'rejected'),) if case['past'] else ()
    return Claim(case['new'], current), (HistoricalFact('synthetic-fact-1', 2 if snapshots else 1,
        Record(case['old'], case['status'], snapshots, (source,))),)


class ClarificationTests(unittest.TestCase):
    def test_all_reviewed_adversarial_cases_preserve_history_and_never_authorize(self):
        for case in CORPUS:
            with self.subTest(case=case['id']):
                claim, history = arranged(case)
                before = deepcopy((claim, history))
                flow = begin(claim, history)
                updated = explain(flow, expected_revision=1, text='我提供额外解释，但不确定是否独立。',
                    evidence_description='合成测试日志的文字描述；尚未核实。')
                self.assertEqual(flow.history, updated.history)
                self.assertEqual((claim, history), before)
                self.assertEqual(updated.state, 'awaiting_independent_review')
                self.assertFalse(updated.persistence_authorized)
                self.assertFalse(updated.truth_verified)
                self.assertEqual(updated.semantic_independence, 'NOT_PROVEN')
                self.assertEqual(request_save(updated)['status'], 'not_saved')
                if case['past'] or case['status'] == 'rejected':
                    conflict = updated.conflicts[0]
                    self.assertEqual(conflict.fact_id, 'synthetic-fact-1')
                    self.assertIn(case.get('prior', case['old']), conflict.rejected_statements)

    def test_numeric_synonym_responsibility_and_unrelated_explanations(self):
        for name in ('numeric_spelling', 'synonym', 'team_to_person'):
            case = next(c for c in CORPUS if c['id'] == name)
            flow = begin(*arranged(case))
            self.assertEqual(flow.conflicts[0].reason, 'possible_reassertion_not_proven')
            self.assertIn('SEMANTICALLY_SUSPECTED', flow.conflicts[0].labels)
        unrelated = next(c for c in CORPUS if c['id'] == 'unrelated_current')
        flow = begin(*arranged(unrelated))
        self.assertEqual(flow.conflicts[0].reason, 'unrelated_blocked_by_rejected_history')

    def test_original_and_all_rejected_snapshots_are_retained(self):
        history = (HistoricalFact('old', 4, Record('当前原话', 'pending',
            (('最早否认', 'rejected'), ('第二次否认', 'rejected'), ('后来确认', 'user_confirmed')), (Source('old'),))),)
        flow = begin(Claim('我部署了服务。', Source('new')), history)
        self.assertEqual(flow.history, history)
        self.assertEqual(flow.conflicts[0].rejected_statements, ('最早否认', '第二次否认'))

    def test_new_turn_cannot_unlock_exact_claim(self):
        case = next(c for c in CORPUS if c['id'] == 'exact_new_turn')
        claim, history = arranged(case)
        for turn in ('new-a', 'new-b', 'another-key-like-symbol'):
            flow = begin(replace(claim, source=Source(turn)), history)
            self.assertIn('EXACT_REUSE', flow.conflicts[0].labels)
            self.assertFalse(request_save(flow)['persistence_authorized'])

    def test_explanation_rounds_append_without_erasing_anything(self):
        flow = begin(*arranged(CORPUS[0]))
        for i in range(3):
            flow = explain(flow, expected_revision=i+1, text=f'解释 {i}', evidence_description='未核实资料')
        self.assertEqual(len(flow.explanations), 3)
        self.assertEqual(flow.revision, 4)
        self.assertFalse(flow.history_completeness_verified)

    def test_stale_explanation_and_invalid_fields_fail_closed(self):
        flow = begin(*arranged(CORPUS[0]))
        for revision in (True, 0, 2):
            with self.assertRaisesRegex(ValueError, 'revision_conflict'):
                explain(flow, expected_revision=revision, text='解释', evidence_description='证据')
        for value in ('', '\0', 'x'*2001, '\ud800', None):
            with self.assertRaises(ValueError):
                explain(flow, expected_revision=1, text=value, evidence_description='证据')

    def test_no_approval_override_and_no_tampered_conflicts(self):
        flow = begin(*arranged(CORPUS[0]))
        with self.assertRaises(ValueError): replace(flow, persistence_authorized=True)
        with self.assertRaises(FrozenInstanceError): flow.state = 'approved'
        with self.assertRaises(ValueError):
            explain(replace(flow, conflicts=()), expected_revision=1, text='解释', evidence_description='证据')
        with self.assertRaises(TypeError): begin(flow.candidate, flow.history, force=True)
        with self.assertRaisesRegex(ValueError, 'version_unsupported'): begin(flow.candidate, flow.history, contract='v9')

    def test_empty_history_is_not_proof_of_independence(self):
        flow = begin(Claim('我部署了服务。', Source('new')), ())
        self.assertEqual(flow.conflicts, ())
        self.assertEqual(flow.semantic_independence, 'NOT_PROVEN')
        self.assertFalse(request_save(flow)['persistence_authorized'])

    def test_isolated_no_io_or_production_import(self):
        source = Path(__file__).with_name('flow.py').read_text(encoding='utf8')
        tree = ast.parse(source)
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(modules, {'dataclasses', 'overnight_research.r03'})
        self.assertFalse(any(isinstance(n, ast.Import) for n in ast.walk(tree)))
        for path in (ROOT/'apps/api/app').rglob('*.py'):
            self.assertNotIn('research.clarification', path.read_text(encoding='utf8'))
