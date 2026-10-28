"""Synthetic protocol/diagnostic tests, not an independently reviewed quality benchmark."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("m25_quality", HERE / "quality.py")
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)
CORPUS = q.load_corpus()
SHARED = q.strict_json((HERE / "contract-fixtures.json").read_text(encoding="utf8"))


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["id"] + "-" + c["title"])
def test_frozen_public_synthetic_cases_stay_unreviewed_and_baseline_is_not_accuracy(case):
    before = deepcopy(case)
    packet = q.baseline(case)
    result = q.evaluate(case, packet)
    assert case == before
    assert case["label_status"] == result["label_status"] == "draft_unreviewed"
    assert case["human_review"] is None
    assert result["hard_checks"] == "pass"
    assert result["status"] == "uncertain"
    assert set(result["dimensions"]) == set(q.DIMENSIONS)
    assert result["truth_verified"] is result["persistence_authorized"] is False
    assert all(s["rewrite_text"] is None and not s["new_claims"] for s in packet["suggestions"])


@pytest.mark.parametrize("packet", SHARED["valid"], ids=("normal", "unicode", "manual", "crlf", "mathematical-integer-json"))
def test_shared_python_ts_valid_contracts(packet):
    before = deepcopy(packet)
    assert q.validate(packet) == before
    assert packet == before


@pytest.mark.parametrize("item", SHARED["invalid"], ids=lambda i: i["name"])
def test_shared_python_ts_invalid_contracts(item):
    with pytest.raises(q.ContractError):
        q.validate(item["packet"])


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":"\\ud800"}', '[' * 26 + '0' + ']' * 26])
def test_duplicate_keys_nonfinite_unicode_and_depth_fail_closed(text):
    with pytest.raises(q.ContractError):
        q.strict_json(text)


def test_code_point_offsets_not_utf16_or_graphemes():
    packet = deepcopy(SHARED["valid"][1])
    paragraph = packet["source_snapshot"]["paragraphs"][0]
    assert "👩🏽‍💻" in paragraph["quote"] and "é" in paragraph["quote"]
    assert paragraph["end"] == len(paragraph["quote"])
    assert paragraph["end"] != len(paragraph["quote"].encode("utf-16-le")) // 2
    packet["suggestions"][0]["source"]["end"] += 1
    with pytest.raises(q.ContractError):
        q.validate(packet)


def test_crlf_is_not_normalized_or_silently_repaired():
    packet = deepcopy(SHARED["valid"][3])
    assert "\r\n" in packet["source_snapshot"]["text"]
    packet["source_snapshot"]["text"] = packet["source_snapshot"]["text"].replace("\r\n", "\n")
    with pytest.raises(q.ContractError):
        q.validate(packet)


def test_json_mathematical_integer_variants_do_not_rewrite_original_packet():
    packet = deepcopy(SHARED["valid"][4])
    before = json.dumps(packet, ensure_ascii=False)
    checked = q.validate(packet)
    assert type(checked["suggestions"][0]["priority"]) is float
    assert type(checked["suggestions"][0]["source"]["start"]) is float
    assert json.dumps(checked, ensure_ascii=False) == before
    assert json.dumps(packet, ensure_ascii=False) == before
    exponent = before.replace('"priority": 1.0', '"priority": 1e0')
    parsed = q.strict_json(exponent)
    assert q.validate(parsed) == checked


@pytest.mark.parametrize("number", [True, False, 1.25, float("inf"), float("-inf"), float("nan")], ids=("true", "false", "fraction", "infinity", "negative-infinity", "nan"))
@pytest.mark.parametrize("field", ["priority", "source-start", "source-end", "paragraph-end", "jd-start"])
def test_boolean_nonfinite_fractional_numbers_remain_rejected(number, field):
    packet = deepcopy(SHARED["valid"][0])
    if field == "priority":
        packet["suggestions"][0]["priority"] = number
    elif field == "paragraph-end":
        packet["source_snapshot"]["paragraphs"][0]["end"] = number
    else:
        ref, key = field.split("-")
        packet["suggestions"][0][ref][key] = number
    with pytest.raises(q.ContractError):
        q.validate(packet)


def test_stale_role_or_source_snapshot_rejected_even_when_internally_valid():
    case = CORPUS["cases"][0]
    packet = q.baseline(case)
    packet["role_id"] = "other-role"
    q.validate(packet)
    with pytest.raises(q.ContractError, match="case_snapshot_or_role_mismatch"):
        q.evaluate(case, packet)


def test_changed_source_snapshot_cannot_be_used_to_mark_fake_quote_valid():
    case = CORPUS["cases"][50]
    packet = q.baseline(case)
    packet["source_snapshot"]["text"] = packet["source_snapshot"]["text"].replace("27", "28")
    for paragraph in packet["source_snapshot"]["paragraphs"]:
        paragraph["quote"] = paragraph["quote"].replace("27", "28")
    for item in packet["suggestions"]:
        item["source"]["quote"] = item["source"]["quote"].replace("27", "28")
    q.validate(packet)
    with pytest.raises(q.ContractError, match="case_snapshot_or_role_mismatch"):
        q.evaluate(case, packet)


def test_known_negative_fixtures_preserved_and_detected_without_changing_labels():
    batch = q.strict_json((HERE / "fixtures/deliberate-negative-candidates.json").read_text(encoding="utf8"))
    result = q.report(CORPUS, batch["cases"])
    assert result["counts"]["supplied"] == {"fail": 5, "uncertain": 2}
    assert result["accuracy"] is result["fact_error_rate"] is None
    failures = {f["rule"] for r in result["cases"] if r["supplied"] for f in r["supplied"]["findings"] if f["status"] == "fail"}
    assert {"new_numeric_token", "source_qualifier_removed"} <= failures


def test_english_semantic_blind_spots_are_uncertain_and_not_claimed_safe():
    batch = q.strict_json((HERE / "fixtures/deliberate-negative-candidates.json").read_text(encoding="utf8"))
    result = q.report(CORPUS, batch["cases"])
    for number in ("M25-057", "M25-058"):
        row = next(r for r in result["cases"] if r["case_id"] == number)
        assert row["supplied"]["status"] == "uncertain"
        assert row["supplied"]["hard_checks"] == "pass"  # finite checks missed this; never a semantic pass
        assert any(f["rule"] == "changed_text_entailment_unproven" for f in row["supplied"]["findings"])


def test_keyword_baseline_misses_synonym_and_matches_jd_negation_honestly():
    synonym = next(c for c in CORPUS["cases"] if c["title"] == "synonym")
    jd_negation = next(c for c in CORPUS["cases"] if c["title"] == "jd-negation")
    assert q.baseline(synonym)["suggestions"] == []
    assert q.baseline(jd_negation)["suggestions"]  # current literal vocabulary is not semantic understanding
    assert q.evaluate(jd_negation, q.baseline(jd_negation))["status"] == "uncertain"


def test_corrupt_candidate_returns_case_failure_not_partial_projection():
    bad = deepcopy(SHARED["valid"][0])
    bad["suggestions"][0].pop("reason")
    result = q.report(CORPUS, {"M25-001": bad})
    row = result["cases"][0]["supplied"]
    assert row["status"] == "fail"
    assert row["findings"][0]["rule"] == "contract_rejected"
    assert row["findings"][0]["source"] is None


@pytest.mark.parametrize("raw", [{}, {"contract": q.CONTRACT}, None, [], 1, {"suggestions": 1}])
def test_completely_malformed_case_cannot_crash_report_comparison(raw):
    result = q.report(CORPUS, {"M25-001": raw})
    row = result["cases"][0]
    assert row["supplied"]["status"] == "fail"
    assert row["comparison"]["supplied_suggestion_count"] is None


def test_ascii_keyword_boundaries_match_existing_m2_lexical_core():
    assert q.literal_terms("Pythonic code", "Python experience") == []
    assert q.literal_terms("用Python写脚本", "Python experience") == ["python"]
    assert q.literal_terms("PYTHON 脚本", "Python experience") == ["python"]


def test_unknown_case_does_not_silently_fallback_to_baseline():
    with pytest.raises(q.ContractError, match="unknown_candidate_case"):
        q.report(CORPUS, {"invented-case": SHARED["valid"][0]})


def test_frozen_manifest_detects_corpus_edits_without_relabeling(tmp_path, monkeypatch):
    corpus = deepcopy(CORPUS)
    corpus["cases"][0]["draft_observation"] = "silently adjusted answer"
    (tmp_path / "cases-v1.json").write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf8")
    (tmp_path / "cases-v1.manifest.json").write_bytes((HERE / "cases-v1.manifest.json").read_bytes())
    monkeypatch.setattr(q, "HERE", tmp_path)
    with pytest.raises(q.ContractError, match="frozen_corpus_hash_mismatch"):
        q.load_corpus()


def test_review_dispute_is_external_claim_not_gold_or_verified_identity():
    sidecar = {"contract": "m25-human-review-claim-v1", "corpus_sha256": q.canonical_sha(CORPUS),
               "reviewer_id": "example-only", "provenance": "synthetic file; no real reviewer",
               "entries": [{"case_id": "M25-001", "decision": "dispute", "rationale": "Synthetic dispute example.", "evidence_ref": "example-ref"}]}
    result = q.review_sidecar(sidecar, CORPUS)
    assert result["disputed_case_ids"] == ["M25-001"]
    assert result["identity_verified"] is result["gold_authorized"] is False
    assert all(c["human_review"] is None and c["label_status"] == "draft_unreviewed" for c in CORPUS["cases"])
    sidecar["corpus_sha256"] = "0" * 64
    with pytest.raises(q.ContractError):
        q.review_sidecar(sidecar, CORPUS)


def test_reordered_complete_paragraphs_are_legal_without_inventing_new_source_rule():
    case = next(c for c in CORPUS["cases"] if len(c["source_snapshot"]["paragraphs"]) > 1)
    packet = q.baseline(case)
    packet["source_snapshot"]["paragraphs"].reverse()
    assert q.validate(packet) == packet


def test_baseline_and_evaluation_cli_are_repeatable_and_preserve_old_output(tmp_path):
    packet = tmp_path / "baseline.json"
    result = tmp_path / "report.json"
    commands = (["verify"], ["baseline", "--output", str(packet)], ["evaluate", "--input", str(packet), "--output", str(result)])
    for args in commands:
        run = subprocess.run([sys.executable, str(HERE / "quality.py"), *args], capture_output=True)
        assert run.returncode == 0, run.stderr
    first = result.read_bytes()
    run = subprocess.run([sys.executable, str(HERE / "quality.py"), "evaluate", "--input", str(packet), "--output", str(result)], capture_output=True)
    assert run.returncode == 2
    assert result.read_bytes() == first
    document = q.strict_json(first.decode())
    assert document["case_count"] == document["supplied_case_count"] == 60
    assert document["counts"]["supplied"] == {"uncertain": 60}
    assert document["accuracy"] is None


def test_negative_cli_saves_failures_then_returns_one_without_relabeling(tmp_path):
    output = tmp_path / "negative-diagnostics.json"
    run = subprocess.run([sys.executable, str(HERE / "quality.py"), "evaluate", "--input",
                          str(HERE / "fixtures/deliberate-negative-candidates.json"), "--output", str(output)], capture_output=True)
    assert run.returncode == 1
    result = q.strict_json(output.read_text(encoding="utf8"))
    assert result["counts"]["supplied"] == {"fail": 5, "uncertain": 2}
    assert result["label_status"] == "draft_unreviewed"


def test_committed_generated_reports_are_reproducible_diagnostics_not_external_gold():
    baseline_batch = q.strict_json((HERE / "reports/baseline-candidates.generated.json").read_text(encoding="utf8"))
    assert baseline_batch == {"contract": "m25-candidate-batch-v1", "cases": {c["id"]: q.baseline(c) for c in CORPUS["cases"]}}
    baseline_report = q.strict_json((HERE / "reports/baseline-diagnostics.generated.json").read_text(encoding="utf8"))
    negatives = q.strict_json((HERE / "fixtures/deliberate-negative-candidates.json").read_text(encoding="utf8"))
    negative_report = q.strict_json((HERE / "reports/negative-diagnostics.generated.json").read_text(encoding="utf8"))
    assert q.report(CORPUS, baseline_batch["cases"]) == baseline_report
    assert q.report(CORPUS, negatives["cases"]) == negative_report
    assert baseline_report["uncalibrated_generated_diagnostics"] is True
    assert baseline_report["accuracy"] is baseline_report["fact_error_rate"] is None


def test_offline_module_has_no_network_database_provider_or_secret_imports():
    import ast
    tree = ast.parse((HERE / "quality.py").read_text(encoding="utf8"))
    imports = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imports |= {alias.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names}
    assert imports <= {"__future__", "argparse", "collections", "copy", "hashlib", "json", "math", "pathlib", "re", "sys", "typing"}
