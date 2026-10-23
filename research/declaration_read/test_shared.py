"""Language parity fixtures have explicit expectations, not parser-generated verdicts."""
import json
from pathlib import Path
import unittest
from contract import parse_json


class SharedCorpusTests(unittest.TestCase):
    def test_shared_corpus(self):
        cases = json.loads(Path(__file__).with_name('corpus.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(cases), 45)
        for case in cases:
            with self.subTest(case=case['name']):
                result = parse_json(case['json'])
                self.assertEqual(result.status, case['status'])
                if 'code' in case:
                    self.assertEqual(result.code, case['code'])
                self.assertFalse(result.truth_verified)
                self.assertFalse(result.persistence_authorized)
                if case['status'] == 'rejected':
                    self.assertIsNone(result.view)
