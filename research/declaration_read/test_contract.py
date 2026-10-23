"""Contract evidence only; synthetic records are not actual stored declarations."""
import ast
import importlib.util
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import unittest
import sys

from contract import DECLARATION_CONTRACT, PAIRS, READ_CONTRACT, declaration_text, parse, parse_json


SID = "00000000-0000-4000-8000-000000000001"
PID = "00000000-0000-4000-8000-000000000002"
FID = "00000000-0000-4000-8000-000000000003"
TID = "00000000-0000-4000-8000-000000000004"
DID = "00000000-0000-4000-8000-000000000005"
DECLARATION_TURN = "00000000-0000-4000-8000-000000000006"
OTHER = "00000000-0000-4000-8000-000000000009"


def fixture(*, recorded=True):
    quote = "我整理了27条缺失记录。"
    citation = {"turn_id": TID, "start": 0, "end": len(quote), "quote": quote}
    classification = {"fact_kind": "personal_action", "progress_stage": "completed",
                      "classification_contract": "explicit-typed-v1"}
    subject = {"fact_id": FID, "session_id": SID, "project_id": PID, "fact_version": 1,
               "statement": quote, "status": "pending", **classification}
    group = {"availability": "exact_quotes", "turn_ids": [TID], "citations": [citation]}
    declaration = {"declaration_contract": DECLARATION_CONTRACT, "declaration_id": DID,
        "record_type": "explicit_user_choice", "actor": "user", "fact_id": FID,
        "session_id": SID, "project_id": PID, "fact_version": 1,
        "classification": deepcopy(classification), "statement_citations": [deepcopy(citation)],
        "declaration_source": {"turn_id": DECLARATION_TURN, "start": 0,
            "end": len(declaration_text(subject)), "quote": declaration_text(subject)},
        "recorded_at": "2026-10-23T00:00:00Z",
        "recorded_validation": {"contract": "typed-semantic-spike-v1", "status": "eligible_candidate", "code": "finite_rule_match"}}
    return {"read_contract": READ_CONTRACT, "synthetic": True, "subject": subject,
        "turns": [{"id": TID, "session_id": SID, "role": "user", "content": quote}] + ([
            {"id": DECLARATION_TURN, "session_id": SID, "role": "user", "content": declaration_text(subject)}
        ] if recorded else []),
        "text_provenance": {"original": deepcopy(group), "current": deepcopy(group)},
        "basis": {"status": "user_declaration_recorded" if recorded else "not_recorded",
                  "declaration": declaration if recorded else None}}


class ContractTests(unittest.TestCase):
    def assert_denied_authority(self, result):
        self.assertEqual(result.evidence_class, "synthetic_contract_only")
        self.assertFalse(result.authentication_verified)
        self.assertFalse(result.database_history_verified)
        self.assertFalse(result.language_validation_replayed)
        self.assertFalse(result.truth_verified)
        self.assertFalse(result.persistence_authorized)

    def assert_rejected(self, payload, code=None):
        result = parse(payload)
        self.assertEqual(result.status, "rejected")
        self.assertIsNone(result.view)
        self.assert_denied_authority(result)
        if code: self.assertEqual(result.code, code)

    def test_recorded_explicit_choice_is_not_verification(self):
        data = fixture(); result = parse(data)
        self.assertEqual(result.status, "parsed_candidate")
        self.assertEqual(result.view, data)
        self.assert_denied_authority(result)

    def test_missing_record_stays_missing_with_exact_original_and_current_sources(self):
        result = parse(fixture(recorded=False))
        self.assertEqual(result.status, "parsed_candidate")
        self.assertEqual(result.view["basis"], {"status": "not_recorded", "declaration": None})
        self.assert_denied_authority(result)

    def test_original_source_cannot_fill_missing_declaration(self):
        data = fixture(recorded=False); data["basis"]["status"] = "user_declaration_recorded"
        self.assert_rejected(data)

    def test_declaration_has_a_separate_complete_choice_source(self):
        data = fixture(); d = data['basis']['declaration']
        self.assertNotEqual(d['declaration_source']['turn_id'], TID)
        self.assertEqual(parse(data).status, 'parsed_candidate')
        d['declaration_source'] = deepcopy(data['text_provenance']['original']['citations'][0])
        self.assert_rejected(data, 'candidate_declaration_origin_invalid')

    def test_declaration_source_cannot_be_omitted_or_falsely_labelled(self):
        data = fixture(); del data['basis']['declaration']['declaration_source']
        self.assert_rejected(data)
        data = fixture(); data['turns'][1]['content'] = '我选择事实类型为 plan，进度为 planned。'
        data['basis']['declaration']['declaration_source'].update(
            quote=data['turns'][1]['content'], end=len(data['turns'][1]['content']))
        self.assert_rejected(data, 'candidate_declaration_choice_mismatch')

    def test_declaration_source_preserves_full_user_choice_not_a_partial_quote(self):
        data = fixture(); source = data['basis']['declaration']['declaration_source']
        data['turns'][1]['content'] = source['quote'] + '这不是平台认证。'
        self.assert_rejected(data, 'candidate_declaration_choice_mismatch')

    def test_original_citation_shape_is_not_a_declaration(self):
        data = fixture(); data["basis"]["declaration"] = deepcopy(data["text_provenance"]["original"]["citations"][0])
        self.assert_rejected(data)

    def test_no_silent_record_removal(self):
        data = fixture(); data["basis"]["status"] = "not_recorded"
        self.assert_rejected(data, "candidate_basis_status_mismatch")

    def test_unknown_read_version_no_fallback(self):
        for version in (4, True, "classification-declaration-read-candidate-v2", "FactV3"):
            with self.subTest(version=version):
                data = fixture(); data["read_contract"] = version
                self.assert_rejected(data, "candidate_version_unsupported")

    def test_unknown_declaration_version(self):
        data = fixture(); data["basis"]["declaration"]["declaration_contract"] += "-new"
        self.assert_rejected(data, "candidate_declaration_version_unsupported")

    def test_unknown_status_or_platform_verified_status(self):
        for status in ("verified", "platform_verified", "recorded", True):
            data = fixture(); data["basis"]["status"] = status
            self.assert_rejected(data, "candidate_basis_status_unsupported")

    def test_extra_fields_never_ignored(self):
        for location in ((), ("subject",), ("basis",), ("basis", "declaration"), ("text_provenance", "current")):
            data = fixture(); target = data
            for key in location: target = target[key]
            target["truth_verified"] = True
            self.assert_rejected(data)

    def test_no_force_history_safe_or_classify_options(self):
        for key in ("force", "history_safe", "related_plan", "classify", "operation_key", "raw_text"):
            data = fixture(); data[key] = True
            self.assert_rejected(data)

    def test_all_existing_classification_pairs_structurally_supported(self):
        for kind, stage, contract in PAIRS:
            data = fixture(recorded=False)
            data["subject"].update(fact_kind=kind, progress_stage=stage, classification_contract=contract)
            data["basis"]["status"] = "legacy_unclassified" if contract == "legacy-v0" else "not_recorded"
            result = parse(data)
            self.assertEqual(result.status, "parsed_candidate")
            self.assertEqual(result.view["subject"]["statement"], data["subject"]["statement"])
            self.assert_denied_authority(result)

    def test_illegal_type_stage_contract_pairs_rejected(self):
        for kind, stage, contract in (("plan", "completed", "explicit-typed-v1"),
                ("background", "in_progress", "explicit-typed-v1"),
                ("boundary", "planned", "explicit-typed-v1"),
                ("personal_action", "completed", "legacy-v0")):
            data = fixture(); data["subject"].update(fact_kind=kind, progress_stage=stage, classification_contract=contract)
            self.assert_rejected(data, "candidate_classification_invalid")

    def test_legacy_and_unclassified_do_not_gain_recorded_basis(self):
        for contract in ("legacy-v0", "unclassified-v1"):
            data = fixture()
            data["subject"].update(fact_kind="legacy_unspecified", progress_stage="legacy_unknown", classification_contract=contract)
            self.assert_rejected(data, "candidate_basis_status_mismatch")

    def test_unclassified_does_not_get_legacy_exemption(self):
        data = fixture(recorded=False)
        data["subject"].update(fact_kind="legacy_unspecified", progress_stage="legacy_unknown", classification_contract="unclassified-v1")
        data["basis"]["status"] = "legacy_unclassified"
        self.assert_rejected(data, "candidate_basis_status_mismatch")

    def test_declared_pair_must_equal_current_pair(self):
        data = fixture(); data["basis"]["declaration"]["classification"]["progress_stage"] = "in_progress"
        self.assert_rejected(data, "candidate_declaration_classification_mismatch")

    def test_fact_session_project_and_version_bound(self):
        for key in ("fact_id", "session_id", "project_id", "fact_version"):
            data = fixture(); data["basis"]["declaration"][key] = 2 if key == "fact_version" else OTHER
            self.assert_rejected(data)

    def test_strict_integers_not_bool_float_or_numeric_strings(self):
        for value in (True, 1.0, "1", 0, -1, 2**53):
            data = fixture(); data["subject"]["fact_version"] = value
            self.assert_rejected(data)
        for value in (False, 0.0, "0", -1):
            data = fixture(); data["basis"]["declaration"]["statement_citations"][0]["start"] = value
            self.assert_rejected(data)

    def test_assistant_and_foreign_session_sources_rejected(self):
        for key, value in (("role", "assistant"), ("session_id", OTHER)):
            data = fixture(); data["turns"][0][key] = value
            self.assert_rejected(data)

    def test_missing_turn_and_duplicate_turn_rejected(self):
        data = fixture(); data["turns"] = []; self.assert_rejected(data)
        data = fixture(); data["turns"].append(deepcopy(data["turns"][0])); self.assert_rejected(data)

    def test_unreferenced_turn_not_leaked_in_candidate(self):
        data = fixture(); data["turns"].append({"id": OTHER, "session_id": SID, "role": "user", "content": "其他资料。"})
        self.assert_rejected(data, "candidate_unreferenced_source")

    def test_number_change_does_not_match_saved_fixture_quote(self):
        data = fixture(); data["subject"]["statement"] = "我整理了28条缺失记录。"
        self.assert_rejected(data, "candidate_statement_mismatch")
        data = fixture(); data["basis"]["declaration"]["statement_citations"][0]["quote"] = "我整理了28条缺失记录。"
        self.assert_rejected(data, "candidate_quote_mismatch")

    def unicode_fixture(self):
        data = fixture()
        content = "🧪e\u0301👩\u200d💻\r\n" + data["subject"]["statement"]
        # 1 emoji + e + combining acute + woman + ZWJ + laptop + CR + LF = 8 CP.
        data["turns"][0]["content"] = content
        for citations in (data["text_provenance"]["original"]["citations"],
                          data["text_provenance"]["current"]["citations"],
                          data["basis"]["declaration"]["statement_citations"]):
            citations[0].update(start=8, end=len(content))
        return data

    def test_emoji_combining_zwj_crlf_exact_codepoints_preserved(self):
        data = self.unicode_fixture(); result = parse(data)
        self.assertEqual(result.status, "parsed_candidate")
        self.assertEqual(result.view, data)

    def test_utf16_units_rejected(self):
        data = self.unicode_fixture()
        data["basis"]["declaration"]["statement_citations"][0]["start"] = 11
        self.assert_rejected(data, "candidate_quote_mismatch")

    def test_unicode_normalization_not_silently_applied(self):
        data = self.unicode_fixture(); data["turns"][0]["content"] = data["turns"][0]["content"].replace("e\u0301", "é")
        self.assert_rejected(data, "candidate_quote_mismatch")

    def test_original_and_current_sources_are_not_interchangeable(self):
        data = fixture()
        new_turn = deepcopy(data["turns"][0]); new_turn["id"] = OTHER; data["turns"].append(new_turn)
        original = data["text_provenance"]["original"]
        original["turn_ids"] = [OTHER]; original["citations"][0]["turn_id"] = OTHER
        self.assertEqual(parse(data).status, "parsed_candidate")
        # Identical words in the original turn cannot stand in for a later choice source.
        data["basis"]["declaration"]["statement_citations"][0]["turn_id"] = OTHER
        self.assert_rejected(data, "candidate_declaration_source_mismatch")

    def test_duplicate_or_omitted_declaration_citations_rejected(self):
        data = fixture(); data["basis"]["declaration"]["statement_citations"] = []; self.assert_rejected(data)
        data = fixture(); cites = data["basis"]["declaration"]["statement_citations"]; cites.append(deepcopy(cites[0]))
        self.assert_rejected(data, "candidate_duplicate_source")

    def test_unquoted_current_source_cannot_claim_recorded_declaration(self):
        data = fixture(); group = data["text_provenance"]["current"]
        group.update(availability="unquoted_source", citations=[])
        self.assert_rejected(data, "candidate_declaration_source_mismatch")

    def test_legacy_unquoted_source_is_explicit_not_fabricated(self):
        data = fixture(recorded=False)
        data["subject"].update(fact_kind="legacy_unspecified", progress_stage="legacy_unknown", classification_contract="legacy-v0")
        data["basis"]["status"] = "legacy_unclassified"
        for group in data["text_provenance"].values(): group.update(availability="unquoted_source", citations=[])
        result = parse(data)
        self.assertEqual(result.status, "parsed_candidate")
        self.assertEqual(result.view["basis"]["declaration"], None)

    def test_record_not_inferred_from_ai_or_source_role(self):
        for key, value in (("actor", "system"), ("record_type", "original_source"), ("actor", "model")):
            data = fixture(); data["basis"]["declaration"][key] = value
            self.assert_rejected(data, "candidate_declaration_origin_invalid")

    def test_unrecognized_recorded_rule_is_not_upgraded(self):
        for key, value in (("contract", "new-validator"), ("status", "verified"), ("code", "true")):
            data = fixture(); data["basis"]["declaration"]["recorded_validation"][key] = value
            self.assert_rejected(data, "candidate_validation_record_unsupported")

    def test_invalid_timestamp(self):
        for value in ("2026-02-30T00:00:00Z", "yesterday", "2026-10-23T00:00:00+08:00", True):
            data = fixture(); data["basis"]["declaration"]["recorded_at"] = value
            self.assert_rejected(data, "candidate_timestamp_invalid")

    def test_all_review_statuses_preserved_without_inferred_truth(self):
        for status in ("pending", "user_confirmed", "evidence_supported", "rejected"):
            data = fixture(); data["subject"]["status"] = status
            result = parse(data); self.assertEqual(result.view["subject"]["status"], status)
            self.assert_denied_authority(result)

    def test_consistent_forged_semantics_is_not_detected_by_structural_parser(self):
        # Deliberate limitation evidence: caller-supplied sources/records can agree
        # while falsely claiming a plan was completed. No admission/semantic claim.
        data = fixture(); text = "我计划部署服务。"; data["subject"]["statement"] = text
        data["turns"][0]["content"] = text
        for cites in (data["text_provenance"]["original"]["citations"], data["text_provenance"]["current"]["citations"], data["basis"]["declaration"]["statement_citations"]):
            cites[0].update(quote=text, end=len(text))
        result = parse(data)
        self.assertEqual(result.status, "parsed_candidate")
        self.assert_denied_authority(result)
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("frozen_c3a_contract_probe", root / "apps/api/app/typed_semantic_spike.py")
        language = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = language
        spec.loader.exec_module(language)
        language_result = language.validate_candidate({"validation_contract": "typed-semantic-spike-v1",
            "synthetic": True, "raw_text": text, "items": [{"quote": text, "start": 0, "end": len(text),
                "fact_kind": "personal_action", "progress_stage": "completed", "classification_contract": "explicit-typed-v1"}]})
        self.assertNotEqual(language_result.status, "eligible_candidate")

    def test_overlapping_citations_are_not_multiple_source_proofs(self):
        data = fixture(recorded=False)
        data["turns"][0]["content"] = "aaaa"
        data["subject"]["statement"] = "aa"
        cites = [{"turn_id": TID, "start": 0, "end": 2, "quote": "aa"},
                 {"turn_id": TID, "start": 1, "end": 3, "quote": "aa"}]
        for group in data["text_provenance"].values(): group["citations"] = deepcopy(cites)
        self.assert_rejected(data, "candidate_source_order_invalid")

    def test_no_input_mutation_or_view_alias(self):
        data = fixture(); before = deepcopy(data); result = parse(data)
        self.assertEqual(data, before)
        result.view["turns"][0]["content"] = "changed"
        self.assertEqual(data, before)

    def test_rejection_contains_no_raw_text_or_partial_payload(self):
        data = fixture(); data["turns"][0]["content"] = "SYNTHETIC-PRIVATE-CONTENT"
        result = parse(data)
        self.assertIsNone(result.view)
        self.assertNotIn("SYNTHETIC-PRIVATE", json.dumps(asdict(result)))

    def test_json_duplicate_keys_non_finite_and_malformed(self):
        text = json.dumps(fixture())
        for bad in (text.replace('"synthetic": true', '"synthetic": true, "synthetic": false'),
                    text.replace('"fact_version": 1', '"fact_version": NaN'), "{", "[]"):
            result = parse_json(bad)
            self.assertEqual(result.status, "rejected"); self.assertIsNone(result.view)
        self.assertEqual(parse_json(text).status, "parsed_candidate")

    def test_no_surrogates_nulls_or_non_json_types(self):
        for value in ("\ud800", "\0", "", None, object()):
            data = fixture(); data["subject"]["statement"] = value
            self.assert_rejected(data)

    def test_module_and_product_isolation(self):
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse((Path(__file__).parent / "contract.py").read_text(encoding="utf8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(a.name for a in node.names)
            if isinstance(node, ast.ImportFrom): imports.add(node.module)
        self.assertEqual(imports, {"copy", "dataclasses", "json", "re", "uuid", "datetime"})
        for file in (root / "apps/api/app").rglob("*.py"):
            source = file.read_text(encoding="utf8")
            self.assertNotIn("declaration_read", source)
            self.assertNotIn(READ_CONTRACT, source)


if __name__ == "__main__":
    unittest.main()
