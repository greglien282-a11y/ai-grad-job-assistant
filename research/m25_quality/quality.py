"""Offline synthetic diagnostics. No Provider, network, database, or quality certification.

Python indexes are Unicode code points. All candidate graph checks precede diagnostics.
Even a clean hard-rule result leaves subjective language quality uncertain.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT = "local-suggestion-candidates-v1"
DIMENSIONS = ("jd_requirements", "association", "source_fidelity", "fabrication_risk",
              "state_preservation", "usefulness_explanation", "clarification")
TERMS = ("python", "pytorch", "opencv", "图像处理", "视觉", "标注", "部署", "测试",
         "项目", "团队", "本科", "实习", "量化")
RISK_MARKERS = ("计划", "准备", "正在", "未", "没有", "不知道", "不确定", "可能", "团队", "我们", "拒绝")
MAX_BYTES = 2 * 1024 * 1024
MAX_PACKET_BYTES = 512 * 1024


class ContractError(ValueError):
    pass


def strict_json(text: str) -> Any:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ContractError("document_too_large")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("duplicate_json_key:" + key)
            result[key] = value
        return result
    try:
        result = json.loads(text, object_pairs_hook=pairs,
                            parse_constant=lambda value: (_ for _ in ()).throw(ContractError("non_finite_number")))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ContractError("invalid_json") from exc
    def depth(value, n=0):
        if n > 24:
            raise ContractError("document_too_deep")
        if isinstance(value, dict):
            for key, item in value.items():
                _string(key)
                depth(item, n + 1)
        elif isinstance(value, list):
            for item in value:
                depth(item, n + 1)
        elif isinstance(value, str):
            _string(value, empty=True)
    depth(result)
    return result


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ContractError("unknown_or_missing_fields")


def _string(value, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > 40000:
        raise ContractError("invalid_string")
    if any(0xD800 <= ord(c) <= 0xDFFF or ord(c) == 0 for c in value):
        raise ContractError("invalid_unicode")


def _text(value):
    _string(value)
    if len(value.encode("utf-16-le")) // 2 > 20000 or len(value.encode("utf-8")) > 128 * 1024:
        raise ContractError("text_budget_exceeded")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]", value):
        raise ContractError("unsafe_text")
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~-]{12,}|\bsk-[A-Za-z0-9_-]{16,}", value, re.I):
        raise ContractError("suspected_credential")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value):
        raise ContractError("invalid_identifier")


def _list(value, limit=200):
    if not isinstance(value, list) or len(value) > limit:
        raise ContractError("invalid_array")


def _integer(value):
    # JSON has one number type; 1, 1.0 and 1e0 denote the same mathematical
    # integer. bool remains invalid, and float values must be finite/exact.
    return type(value) is int or (type(value) is float and math.isfinite(value) and value.is_integer())


def _range(value, text):
    start, end = value.get("start"), value.get("end")
    if not _integer(start) or not _integer(end) or not 0 <= start < end <= len(text):
        raise ContractError("invalid_code_point_range")
    _text(value.get("quote"))
    if text[int(start):int(end)] != value["quote"]:
        raise ContractError("quote_mismatch")


def validate(value: Any) -> dict:
    """Strict complete paragraph/JD bindings. No implicit source repair or fallback."""
    _keys(value, "contract role_id source_snapshot jd_snapshot suggestions")
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_PACKET_BYTES:
        raise ContractError("packet_budget_exceeded")
    if value["contract"] != CONTRACT:
        raise ContractError("unsupported_contract")
    _id(value["role_id"])
    source, jd = value["source_snapshot"], value["jd_snapshot"]
    _keys(source, "id text paragraphs")
    _keys(jd, "text requirements")
    _id(source["id"])
    _text(source["text"])
    _text(jd["text"])
    _list(source["paragraphs"], 150)
    _list(jd["requirements"])
    if not jd["requirements"]:
        raise ContractError("empty_source_graph")
    paragraphs, requirements = {}, {}
    for paragraph in source["paragraphs"]:
        _keys(paragraph, "id kind start end quote")
        _id(paragraph["id"])
        if paragraph["kind"] not in ("resume_excerpt", "user_manual_statement"):
            raise ContractError("unknown_source_kind")
        _range(paragraph, source["text"])
        if paragraph["id"] in paragraphs:
            raise ContractError("duplicate_paragraph")
        paragraphs[paragraph["id"]] = paragraph
    for requirement in jd["requirements"]:
        _keys(requirement, "id start end quote")
        _id(requirement["id"])
        _range(requirement, jd["text"])
        if requirement["id"] in requirements:
            raise ContractError("duplicate_requirement")
        requirements[requirement["id"]] = requirement
    _list(value["suggestions"], 100)
    ids, pairs = set(), set()
    for item in value["suggestions"]:
        _keys(item, "id source jd priority rewrite_text reason new_claims evidence_gap provenance")
        _id(item["id"])
        if item["id"] in ids:
            raise ContractError("duplicate_suggestion")
        ids.add(item["id"])
        if not _integer(item["priority"]) or not 1 <= item["priority"] <= 100:
            raise ContractError("invalid_priority")
        _text(item["reason"])
        for key in ("rewrite_text", "evidence_gap"):
            if item[key] is not None:
                _text(item[key])
        _list(item["new_claims"], 20)
        for claim in item["new_claims"]:
            _text(claim)
        ref, requirement = item["source"], item["jd"]
        _keys(ref, "source_id paragraph_id kind quote start end")
        _keys(requirement, "requirement_id quote start end")
        for key in ("source_id", "paragraph_id"):
            _id(ref[key])
        _id(requirement["requirement_id"])
        _range(ref, source["text"])
        _range(requirement, jd["text"])
        paragraph = paragraphs.get(ref["paragraph_id"])
        saved_jd = requirements.get(requirement["requirement_id"])
        if ref["source_id"] != source["id"] or paragraph is None or saved_jd is None:
            raise ContractError("unknown_source_or_jd")
        if any(ref[k] != paragraph[k] for k in ("kind", "quote", "start", "end")):
            raise ContractError("incomplete_or_cross_source_quote")
        if any(requirement[k] != saved_jd[k] for k in ("quote", "start", "end")):
            raise ContractError("jd_quote_mismatch")
        pair = (ref["paragraph_id"], requirement["requirement_id"])
        if pair in pairs:
            raise ContractError("duplicate_source_jd_pair")
        pairs.add(pair)
        provenance = item["provenance"]
        _keys(provenance, "kind id version")
        if provenance["kind"] not in ("deterministic_rule", "offline_mock", "supplied_offline"):
            raise ContractError("unknown_generator_kind")
        _id(provenance["id"])
        _id(provenance["version"])
    return deepcopy(value)


def literal_terms(source: str, requirement: str) -> list[str]:
    def present(term, text):
        return bool(re.search(r"\b" + re.escape(term) + r"\b", text, re.I | re.ASCII)) if term.isascii() else term in text
    return [term for term in TERMS if present(term, source) and present(term, requirement)]


def baseline(case: dict) -> dict:
    """Current M2 finite lexical core only, NOT the UI's complete admission policy."""
    value = {key: deepcopy(case[key]) for key in ("role_id", "source_snapshot", "jd_snapshot")}
    value.update(contract=CONTRACT, suggestions=[])
    for paragraph in value["source_snapshot"]["paragraphs"]:
        for requirement in value["jd_snapshot"]["requirements"]:
            matched = literal_terms(paragraph["quote"], requirement["quote"])
            if not matched:
                continue
            item = {"id": f"baseline-{len(value['suggestions']) + 1}",
                    "source": {"source_id": value["source_snapshot"]["id"], "paragraph_id": paragraph["id"],
                               **{key: paragraph[key] for key in ("kind", "quote", "start", "end")}},
                    "jd": {"requirement_id": requirement["id"], **{key: requirement[key] for key in ("quote", "start", "end")}},
                    "priority": min(len(value["suggestions"]) + 1, 100), "rewrite_text": None,
                    "reason": "字面交集：" + "、".join(matched) + "；仅排序原句，不证明掌握或真实性。",
                    "new_claims": [], "evidence_gap": "字面关联不能证明符合岗位；请人工核对责任、状态及证据。",
                    "provenance": {"kind": "deterministic_rule", "id": "m2-keyword-vocabulary", "version": "1"}}
            value["suggestions"].append(item)
    return validate(value)


def evaluate(case: dict, candidate: dict) -> dict:
    """Known counterexample diagnostics, not full semantic entailment/accuracy."""
    candidate = validate(candidate)
    for key in ("role_id", "source_snapshot", "jd_snapshot"):
        if candidate[key] != case[key]:
            raise ContractError("case_snapshot_or_role_mismatch")
    findings = []
    def finding(rule, dimension, status, item=None, detail=""):
        findings.append({"rule": rule, "dimension": dimension, "status": status,
                         "suggestion_id": item["id"] if item else None,
                         "source": item["source"] if item else None, "detail": detail})
    finding("exact_jd_quote_binding", "jd_requirements", "pass", detail="只验证给定条目原文，不评估要求提取完整性。")
    finding("jd_extraction_completeness_requires_review", "jd_requirements", "uncertain")
    finding("exact_source_graph", "source_fidelity", "pass")
    if not candidate["suggestions"]:
        finding("empty_recommendation_not_necessarily_wrong", "association", "uncertain")
    for item in candidate["suggestions"]:
        source, rewritten = item["source"]["quote"], item["rewrite_text"]
        terms = literal_terms(source, item["jd"]["quote"])
        finding("literal_overlap_observation", "association", "uncertain", item,
                "字面交集=" + "、".join(terms) + "；无交集也不证明无语义关联。")
        finding("reason_requires_human_judgment", "usefulness_explanation", "uncertain", item)
        if rewritten is None or rewritten == source:
            finding("original_text_not_rewritten", "fabrication_risk", "pass", item)
            finding("source_qualifiers_retained", "state_preservation", "pass", item)
        else:
            old_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", source))
            added_numbers = sorted(set(re.findall(r"\d+(?:\.\d+)?%?", rewritten)) - old_numbers)
            added_terms = [term for term in TERMS if term in rewritten.lower() and term not in source.lower()]
            if added_numbers:
                finding("new_numeric_token", "fabrication_risk", "fail", item, repr(added_numbers))
            if added_terms:
                finding("new_protected_term", "fabrication_risk", "fail", item, repr(added_terms))
            lost = [marker for marker in RISK_MARKERS if marker in source and marker not in rewritten]
            if lost:
                finding("source_qualifier_removed", "state_preservation", "fail", item, repr(lost))
            finding("changed_text_entailment_unproven", "fabrication_risk", "uncertain", item,
                    "未触发有限规则不代表没有编造；改写仍需人工逐项审查。")
            finding("rewrite_needs_human_review", "clarification", "uncertain", item)
        if item["new_claims"]:
            finding("declared_new_claims_unverified", "clarification", "uncertain", item,
                    "新增主张不是证据，不能据确认按钮认证：" + repr(item["new_claims"]))
        if any(marker in source for marker in RISK_MARKERS):
            finding("restricted_context_needs_review", "clarification", "uncertain", item,
                    "保留来源限制，不能推导个人完成或解决 R03。")
    for dimension in DIMENSIONS:
        if not any(f["dimension"] == dimension for f in findings):
            finding("not_automatically_judged", dimension, "uncertain")
    counts = {dimension: dict(Counter(f["status"] for f in findings if f["dimension"] == dimension)) for dimension in DIMENSIONS}
    status = "fail" if any(f["status"] == "fail" for f in findings) else "uncertain"
    return {"case_id": case["id"], "status": status, "label_status": "draft_unreviewed",
            "hard_checks": "fail" if status == "fail" else "pass", "dimensions": counts,
            "findings": findings, "truth_verified": False, "persistence_authorized": False}


def canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_corpus() -> dict:
    corpus = strict_json((HERE / "cases-v1.json").read_text(encoding="utf8"))
    manifest = strict_json((HERE / "cases-v1.manifest.json").read_text(encoding="utf8"))
    if corpus["contract"] != "m25-public-synthetic-corpus-v1" or corpus["label_status"] != "draft_unreviewed":
        raise ContractError("unsupported_corpus")
    if canonical_sha(corpus) != manifest["canonical_sha256"]:
        raise ContractError("frozen_corpus_hash_mismatch")
    if len(corpus["cases"]) != manifest["case_count"] or len({c["id"] for c in corpus["cases"]}) != len(corpus["cases"]):
        raise ContractError("corpus_count_or_identity_mismatch")
    for case in corpus["cases"]:
        if case["label_status"] != "draft_unreviewed" or canonical_sha(case) != manifest["case_sha256"][case["id"]]:
            raise ContractError("frozen_case_or_label_mismatch")
        baseline(case)
    return corpus


def report(corpus: dict, supplied: dict | None = None) -> dict:
    supplied = supplied or {}
    unknown = set(supplied) - {case["id"] for case in corpus["cases"]}
    if unknown:
        raise ContractError("unknown_candidate_case")
    records = []
    for case in corpus["cases"]:
        reference = baseline(case)
        current = None
        if case["id"] in supplied:
            try:
                current = evaluate(case, supplied[case["id"]])
            except ContractError as exc:
                current = {"case_id": case["id"], "status": "fail", "label_status": "draft_unreviewed",
                           "hard_checks": "fail", "dimensions": {
                               dimension: {"fail" if dimension == "source_fidelity" else "uncertain": 1}
                               for dimension in DIMENSIONS},
                           "findings": [{"rule": "contract_rejected", "dimension": "source_fidelity", "status": "fail",
                                         "suggestion_id": None, "source": None, "detail": str(exc)}],
                           "truth_verified": False, "persistence_authorized": False}
        base_result = evaluate(case, reference)
        raw_suggestions = supplied[case["id"]].get("suggestions") if isinstance(supplied.get(case["id"]), dict) else None
        records.append({"case_id": case["id"], "tags": case["tags"], "baseline": base_result,
                        "supplied": current,
                        "comparison": None if current is None else {
                            "baseline_suggestion_count": len(reference["suggestions"]),
                            "supplied_suggestion_count": len(raw_suggestions) if isinstance(raw_suggestions, list) else None,
                            "baseline_hard_checks": base_result["hard_checks"], "supplied_hard_checks": current["hard_checks"],
                            "interpretation": "诊断差异；不是模型质量优劣排名。"}})
    return {"contract": "m25-quality-diagnostics-v1", "corpus_sha256": canonical_sha(corpus),
            "label_status": "draft_unreviewed", "case_count": len(records),
            "supplied_case_count": len(supplied), "uncalibrated_generated_diagnostics": True,
            "accuracy": None, "fact_error_rate": None,
            "baseline_scope": "M2 finite keyword lexical core with ASCII word boundaries; not whole UI admission, gap, conflict or print policy.",
            "warning": "Codex 草拟案例/标注未经独立人工审核。硬规则通过不证明真实性；没有真实模型调用。",
            "counts": {"baseline": dict(Counter(r["baseline"]["status"] for r in records)),
                       "supplied": dict(Counter(r["supplied"]["status"] for r in records if r["supplied"]))},
            "dimension_finding_counts": {
                lane: {dimension: dict(Counter(f["status"] for r in records if r[lane]
                                               for f in r[lane]["findings"] if f["dimension"] == dimension))
                       for dimension in DIMENSIONS} for lane in ("baseline", "supplied")},
            "count_unit": "Case counts and per-dimension finding counts are separate; no averaged quality score.",
            "cases": records}


def review_sidecar(value: dict, corpus: dict) -> dict:
    """Validate external review claims, never promote them to gold automatically."""
    _keys(value, "contract corpus_sha256 reviewer_id provenance entries")
    if value["contract"] != "m25-human-review-claim-v1" or value["corpus_sha256"] != canonical_sha(corpus):
        raise ContractError("review_version_mismatch")
    _string(value["reviewer_id"])
    _string(value["provenance"])
    _list(value["entries"])
    ids = set()
    for entry in value["entries"]:
        _keys(entry, "case_id decision rationale evidence_ref")
        if entry["case_id"] not in {c["id"] for c in corpus["cases"]} or entry["case_id"] in ids:
            raise ContractError("unknown_or_duplicate_review_case")
        ids.add(entry["case_id"])
        if entry["decision"] not in ("agree", "dispute", "uncertain"):
            raise ContractError("unknown_review_decision")
        _string(entry["rationale"])
        _string(entry["evidence_ref"])
    return {"review_claim_valid": True, "identity_verified": False, "gold_authorized": False,
            "disputed_case_ids": [e["case_id"] for e in value["entries"] if e["decision"] == "dispute"],
            "claim_sha256": canonical_sha(value), "warning": "本工具只校验审核文件结构；不能验证审核者身份、独立性或批准金标准。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "baseline", "evaluate", "review"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    corpus = load_corpus()
    if args.command == "verify":
        result = {"frozen_manifest_verified": True, "case_count": len(corpus["cases"]),
                  "canonical_sha256": canonical_sha(corpus), "label_status": "draft_unreviewed", "gold_authorized": False}
    elif args.command == "baseline":
        result = {"contract": "m25-candidate-batch-v1", "cases": {c["id"]: baseline(c) for c in corpus["cases"]}}
    else:
        if args.input is None:
            parser.error("--input is required")
        raw = strict_json(args.input.read_text(encoding="utf8"))
        if args.command == "review":
            result = review_sidecar(raw, corpus)
        else:
            _keys(raw, "contract cases")
            if raw["contract"] != "m25-candidate-batch-v1" or not isinstance(raw["cases"], dict):
                raise ContractError("unsupported_candidate_batch")
            result = report(corpus, raw["cases"])
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        if args.output.exists():
            raise ContractError("output_exists_preserve_evidence")
        args.output.write_text(text, encoding="utf8")
    else:
        print(text)
    return 1 if args.command == "evaluate" and result["counts"]["supplied"].get("fail", 0) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ContractError as exc:
        print(json.dumps({"contract": "m25-quality-error-v1", "status": "fail", "code": str(exc),
                          "truth_verified": False, "persistence_authorized": False}, ensure_ascii=False))
        sys.exit(2)
