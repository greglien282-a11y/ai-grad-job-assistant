"""Synthetic read-contract candidate; NOT a database reader or writer admission.

No app imports, HTTP, DB, clock, environment, network, secrets or model calls.
The parser proves only internal consistency of caller-supplied synthetic data.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from uuid import UUID

READ_CONTRACT = "classification-declaration-read-candidate-v1"
DECLARATION_CONTRACT = "explicit-user-classification-declaration-candidate-v1"
CLASSIFICATION_KEYS = {"fact_kind", "progress_stage", "classification_contract"}
SUBJECT_KEYS = CLASSIFICATION_KEYS | {
    "fact_id", "session_id", "project_id", "fact_version", "statement", "status"}
STATUSES = {"pending", "user_confirmed", "evidence_supported", "rejected"}
PAIRS = {("legacy_unspecified", "legacy_unknown", "legacy-v0"),
         ("legacy_unspecified", "legacy_unknown", "unclassified-v1"),
         ("personal_action", "in_progress", "explicit-typed-v1"),
         ("personal_action", "completed", "explicit-typed-v1"),
         ("plan", "planned", "explicit-typed-v1"),
         ("plan", "in_progress", "explicit-typed-v1"),
         ("background", "not_applicable", "explicit-typed-v1"),
         ("boundary", "not_applicable", "explicit-typed-v1")}


class Invalid(Exception):
    pass


def require(condition, code="candidate_shape_invalid"):
    if not condition:
        raise Invalid(code)


def shape(value, keys):
    require(type(value) is dict and set(value) == keys)


def string(value, maximum=10000):
    require(type(value) is str and 0 < len(value) <= maximum and "\0" not in value)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise Invalid("candidate_text_invalid") from None


def uuid(value):
    require(type(value) is str)
    try:
        require(str(UUID(value)) == value)
    except ValueError:
        raise Invalid("candidate_identifier_invalid") from None


def integer(value, minimum=1):
    require(type(value) is int and minimum <= value <= 2**53 - 1)


def classification(value):
    values = tuple(value[k] for k in ("fact_kind", "progress_stage", "classification_contract"))
    require(all(type(v) is str for v in values) and values in PAIRS, "candidate_classification_invalid")


def declaration_text(value):
    """Synthetic explicit UI choice encoding, not a natural-language classifier."""
    return f"我选择事实类型为 {value['fact_kind']}，进度为 {value['progress_stage']}。"


def citations(items, turns):
    require(type(items) is list and len(items) <= 5)
    seen = set()
    previous_end = {}
    for item in items:
        shape(item, {"turn_id", "start", "end", "quote"})
        uuid(item["turn_id"]); integer(item["start"], 0); integer(item["end"])
        string(item["quote"], 500)
        turn = turns.get(item["turn_id"])
        require(turn is not None and turn["role"] == "user", "candidate_source_invalid")
        require(0 <= item["start"] < item["end"] <= len(turn["content"])
                and turn["content"][item["start"]:item["end"]] == item["quote"],
                "candidate_quote_mismatch")
        key = (item["turn_id"], item["start"], item["end"])
        require(key not in seen, "candidate_duplicate_source")
        require(item["start"] >= previous_end.get(item["turn_id"], 0), "candidate_source_order_invalid")
        previous_end[item["turn_id"]] = item["end"]
        seen.add(key)
    return seen


def text_group(group, turns, *, current_statement=None):
    shape(group, {"availability", "turn_ids", "citations"})
    ids = group["turn_ids"]
    require(type(ids) is list and 1 <= len(ids) <= 5)
    for tid in ids:
        uuid(tid)
        require(tid in turns and turns[tid]["role"] == "user", "candidate_source_invalid")
    require(len(ids) == len(set(ids)), "candidate_duplicate_source")
    keys = citations(group["citations"], turns)
    if group["availability"] == "unquoted_source":
        require(not keys, "candidate_source_status_mismatch")
    elif group["availability"] == "exact_quotes":
        require(bool(keys) and {k[0] for k in keys} == set(ids), "candidate_source_status_mismatch")
        if current_statement is not None:
            # Candidate carries a complete current statement from each cited
            # turn. Partial/assembled historical text needs a reviewed extension.
            require(all(c["quote"] == current_statement for c in group["citations"]),
                    "candidate_statement_mismatch")
    else:
        raise Invalid("candidate_source_status_unsupported")
    return set(ids), keys


@dataclass(frozen=True)
class Result:
    status: str
    code: str
    view: dict | None = None
    evidence_class: str = "synthetic_contract_only"
    authentication_verified: bool = False
    database_history_verified: bool = False
    language_validation_replayed: bool = False
    truth_verified: bool = False
    persistence_authorized: bool = False


def parse(payload: object) -> Result:
    """All-or-error, no partial view, no enrichment of missing declaration data."""
    try:
        shape(payload, {"read_contract", "synthetic", "subject", "turns", "text_provenance", "basis"})
        require(payload["read_contract"] == READ_CONTRACT, "candidate_version_unsupported")
        require(payload["synthetic"] is True, "candidate_scope_required")
        s = payload["subject"]
        shape(s, SUBJECT_KEYS); classification(s)
        for key in ("fact_id", "session_id", "project_id"):
            uuid(s[key])
        integer(s["fact_version"]); string(s["statement"], 500)
        require(type(s["status"]) is str and s["status"] in STATUSES)
        require(type(payload["turns"]) is list and 1 <= len(payload["turns"]) <= 10)
        turns = {}
        for t in payload["turns"]:
            shape(t, {"id", "session_id", "role", "content"})
            uuid(t["id"]); uuid(t["session_id"]); string(t["content"])
            require(t["session_id"] == s["session_id"], "candidate_session_mismatch")
            require(type(t["role"]) is str and t["role"] in {"user", "assistant"})
            require(t["id"] not in turns, "candidate_duplicate_source")
            turns[t["id"]] = t
        shape(payload["text_provenance"], {"original", "current"})
        original_ids, _ = text_group(payload["text_provenance"]["original"], turns)
        current_ids, current_keys = text_group(payload["text_provenance"]["current"], turns,
                                             current_statement=s["statement"])
        basis = payload["basis"]
        shape(basis, {"status", "declaration"})
        declaration_ids = set()
        if basis["status"] in ("legacy_unclassified", "not_recorded"):
            expected = "legacy_unclassified" if s["classification_contract"] == "legacy-v0" else "not_recorded"
            require(basis["status"] == expected and basis["declaration"] is None,
                    "candidate_basis_status_mismatch")
        elif basis["status"] == "user_declaration_recorded":
            require(s["classification_contract"] == "explicit-typed-v1", "candidate_basis_status_mismatch")
            d = basis["declaration"]
            shape(d, {"declaration_contract", "declaration_id", "record_type", "actor",
                      "fact_id", "fact_version", "session_id", "project_id", "classification",
                      "statement_citations", "declaration_source", "recorded_validation", "recorded_at"})
            require(d["declaration_contract"] == DECLARATION_CONTRACT, "candidate_declaration_version_unsupported")
            uuid(d["declaration_id"])
            require(d["record_type"] == "explicit_user_choice" and d["actor"] == "user",
                    "candidate_declaration_origin_invalid")
            for key in ("fact_id", "session_id", "project_id"):
                uuid(d[key]); require(d[key] == s[key], "candidate_declaration_subject_mismatch")
            integer(d["fact_version"])
            require(d["fact_version"] == s["fact_version"], "candidate_declaration_version_mismatch")
            shape(d["classification"], CLASSIFICATION_KEYS); classification(d["classification"])
            require(all(d["classification"][k] == s[k] for k in CLASSIFICATION_KEYS),
                    "candidate_declaration_classification_mismatch")
            declaration_keys = citations([d["declaration_source"]], turns)
            declaration_ids = {k[0] for k in declaration_keys}
            require(not declaration_ids & (original_ids | current_ids), "candidate_declaration_origin_invalid")
            declaration_source = d["declaration_source"]
            declaration_turn = turns[declaration_source["turn_id"]]
            require(declaration_source["start"] == 0
                    and declaration_source["end"] == len(declaration_turn["content"])
                    and declaration_source["quote"] == declaration_text(s),
                    "candidate_declaration_choice_mismatch")
            require(type(d["recorded_at"]) is str and bool(re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", d["recorded_at"])), "candidate_timestamp_invalid")
            from datetime import datetime  # Parsing only; never reads the clock.
            try:
                datetime.strptime(d["recorded_at"], "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                raise Invalid("candidate_timestamp_invalid") from None
            keys = citations(d["statement_citations"], turns)
            require(bool(keys) and keys == current_keys, "candidate_declaration_source_mismatch")
            require(all(c["quote"] == s["statement"] for c in d["statement_citations"]),
                    "candidate_statement_mismatch")
            shape(d["recorded_validation"], {"contract", "status", "code"})
            require(d["recorded_validation"] == {"contract": "typed-semantic-spike-v1",
                    "status": "eligible_candidate", "code": "finite_rule_match"}, "candidate_validation_record_unsupported")
        else:
            raise Invalid("candidate_basis_status_unsupported")
        require(set(turns) == original_ids | current_ids | declaration_ids, "candidate_unreferenced_source")
        return Result("parsed_candidate", "candidate_internally_consistent", deepcopy(payload))
    except Invalid as exc:
        return Result("rejected", str(exc))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        return Result("rejected", "candidate_shape_invalid")


def parse_json(text: str) -> Result:
    """Reject duplicate JSON keys/non-finite numbers instead of accepting last-wins."""
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise Invalid("candidate_duplicate_key")
            obj[key] = value
        return obj
    def constant(_):
        raise Invalid("candidate_shape_invalid")
    try:
        require(type(text) is str and len(text) <= 150000)
        return parse(json.loads(text, object_pairs_hook=unique, parse_constant=constant))
    except Invalid as exc:
        return Result("rejected", str(exc))
    except (ValueError, TypeError, RecursionError):
        return Result("rejected", "candidate_json_invalid")
