"""Verify UI sample claims with unchanged c3a; no runtime HTTP adapter."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('journey_c3a', ROOT/'apps/api/app/typed_semantic_spike.py')
c3a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c3a
spec.loader.exec_module(c3a)


class FixtureTests(unittest.TestCase):
    def test_every_precomputed_ui_sample_matches_existing_c3a_without_truth_or_write_authority(self):
        samples = json.loads(Path(__file__).with_name('src').joinpath('scenarios.json').read_text(encoding='utf8'))
        self.assertEqual(len(samples), 10)
        for sample in samples:
            with self.subTest(sample=sample['id']):
                text = sample['text']
                result = c3a.validate_candidate(dict(validation_contract=c3a.CONTRACT, synthetic=True,
                    raw_text=text, items=[dict(fact_kind=sample['kind'], progress_stage=sample['stage'],
                        classification_contract='explicit-typed-v1', quote=text, start=0, end=len(text))]))
                self.assertEqual(result.status, 'eligible_candidate')
                self.assertFalse(result.truth_verified)
                self.assertFalse(result.persistence_authorized)

    def test_r03_ui_variants_are_reviewed_adversarial_material_not_new_equivalence_rules(self):
        cases = json.loads((ROOT/'apps/api/tests/overnight_research/r03_cases.json').read_text(encoding='utf8'))['cases']
        for case_id in ('numeric_spelling', 'synonym', 'team_to_person', 'unrelated_current'):
            row = next(c for c in cases if c['id'] == case_id)
            self.assertEqual(row['status'], 'rejected')
            self.assertIn('HISTORY_RISK', row['expected'])
        self.assertTrue(next(c for c in cases if c['id'] == 'unrelated_current')['unrelated'])
