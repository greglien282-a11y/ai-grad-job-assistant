"""Independent A event read candidate; no formal DTO/HTTP/factory integration.

Pure parsing cannot authenticate a record, replay its validator, inspect history,
or authorize persistence. Reuses G2.1 scalar/source rules, NOT its Turn-based
declaration projection. Input provenance remains untrusted until separately read
and checked by a server. The disposable projector is in projection.py.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
import re

from research.declaration_read.contract import (
    Invalid,
    require,
    shape,
    string,
    uuid,
    integer,
    classification,
    citations,
    CLASSIFICATION_KEYS,
    SUBJECT_KEYS,
    STATUSES,
)

READ_CONTRACT = "g3-choice-basis-read-candidate-v1"
EVENT_CONTRACT = "g3-choice-event-ref-v1"
SCOPE = "synthetic_or_disposable_reference_only"


@dataclass(frozen=True)
class Result:
    status: str
    code: str
    view: object = None
    evidence_class: str = "structural_read_candidate_only"
    authentication_verified: bool = False
    database_history_verified: bool = False
    language_validation_replayed: bool = False
    truth_verified: bool = False
    persistence_authorized: bool = False


def stamp(value):
    require(
        type(value) is str
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z",
            value,
        ),
        "candidate_timestamp_invalid",
    )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Invalid("candidate_timestamp_invalid") from None


def _checked(payload):
    shape(
        payload,
        {"read_contract", "scope", "subject", "turns", "text_provenance", "basis"},
    )
    require(payload["read_contract"] == READ_CONTRACT, "candidate_version_unsupported")
    require(payload["scope"] == SCOPE, "candidate_scope_required")
    subject = payload["subject"]
    shape(subject, SUBJECT_KEYS)
    classification(subject)
    for key in ("fact_id", "session_id", "project_id"):
        uuid(subject[key])
    integer(subject["fact_version"])
    string(subject["statement"], 500)
    require(type(subject["status"]) is str and subject["status"] in STATUSES)
    require(type(payload["turns"]) is list and 1 <= len(payload["turns"]) <= 10)
    turns = {}
    for turn in payload["turns"]:
        shape(
            turn, {"source_kind", "id", "session_id", "project_id", "role", "content"}
        )
        for key in ("id", "session_id", "project_id"):
            uuid(turn[key])
        string(turn["content"])
        require(
            turn["source_kind"] == "conversation_turn" and turn["role"] == "user",
            "candidate_source_invalid",
        )
        require(
            all(turn[k] == subject[k] for k in ("session_id", "project_id")),
            "candidate_session_mismatch",
        )
        require(turn["id"] not in turns, "candidate_duplicate_source")
        turns[turn["id"]] = turn
    provenance = payload["text_provenance"]
    shape(provenance, {"original", "current"})
    original = citations(provenance["original"], turns)
    current = citations(provenance["current"], turns)
    require(bool(original) and bool(current), "candidate_source_invalid")
    require(
        all(c["quote"] == subject["statement"] for c in provenance["current"]),
        "candidate_statement_mismatch",
    )
    require(
        set(turns) == {c[0] for c in original | current},
        "candidate_unreferenced_source",
    )
    basis = payload["basis"]
    shape(basis, {"status", "event"})
    if basis["status"] in ("legacy_unclassified", "not_recorded"):
        expected = (
            "legacy_unclassified"
            if subject["classification_contract"] == "legacy-v0"
            else "not_recorded"
        )
        require(
            basis["status"] == expected and basis["event"] is None,
            "candidate_basis_status_mismatch",
        )
        return payload
    require(
        basis["status"] == "event_recorded"
        and subject["classification_contract"] == "explicit-typed-v1",
        "candidate_basis_status_mismatch",
    )
    event = basis["event"]
    shape(
        event,
        {
            "event_contract",
            "source_kind",
            "id",
            "session_id",
            "project_id",
            "fact_id",
            "fact_version",
            "operation_id",
            "effect_slot",
            "change_id",
            "classification",
            "statement_citations",
            "selection",
            "authentication_context",
            "recorded_validation",
            "recorded_at",
        },
    )
    require(
        event["event_contract"] == EVENT_CONTRACT, "candidate_event_version_unsupported"
    )
    require(
        event["source_kind"] == "immutable_user_choice_event",
        "candidate_event_source_invalid",
    )
    for key in (
        "id",
        "session_id",
        "project_id",
        "fact_id",
        "operation_id",
        "change_id",
    ):
        uuid(event[key])
    integer(event["fact_version"])
    require(
        all(
            event[k] == subject[k]
            for k in ("session_id", "project_id", "fact_id", "fact_version")
        ),
        "candidate_event_subject_mismatch",
    )
    integer(event["effect_slot"])
    require(event["effect_slot"] <= 5)
    labels = event["classification"]
    shape(labels, CLASSIFICATION_KEYS)
    classification(labels)
    require(
        all(labels[k] == subject[k] for k in CLASSIFICATION_KEYS),
        "candidate_event_classification_mismatch",
    )
    require(
        citations(event["statement_citations"], turns) == current,
        "candidate_event_source_mismatch",
    )
    selection = event["selection"]
    shape(selection, {"id", "source_kind", "classification"})
    uuid(selection["id"])
    require(
        selection["source_kind"] == "explicit_ui_selection",
        "candidate_choice_source_invalid",
    )
    shape(selection["classification"], CLASSIFICATION_KEYS)
    require(selection["classification"] == labels, "candidate_choice_mismatch")
    auth = event["authentication_context"]
    shape(
        auth,
        {
            "id",
            "source_kind",
            "session_id",
            "project_id",
            "operation_id",
            "authenticated_subject",
            "issuer",
            "db_login",
            "recorded_at",
        },
    )
    for key in (
        "id",
        "session_id",
        "project_id",
        "operation_id",
        "authenticated_subject",
    ):
        uuid(auth[key])
    require(
        auth["source_kind"] == "server_authenticated_session"
        and auth["issuer"] == "synthetic-server-auth-v1",
        "candidate_auth_context_invalid",
    )
    require(
        all(auth[k] == event[k] for k in ("session_id", "project_id", "operation_id")),
        "candidate_auth_context_mismatch",
    )
    string(auth["db_login"], 63)
    require(
        stamp(auth["recorded_at"]) <= stamp(event["recorded_at"]),
        "candidate_timestamp_invalid",
    )
    shape(event["recorded_validation"], {"contract", "status", "code"})
    require(
        event["recorded_validation"]
        == {
            "contract": "typed-semantic-spike-v1",
            "status": "eligible_candidate",
            "code": "finite_rule_match",
        },
        "candidate_validation_record_unsupported",
    )
    return payload


def parse(payload):
    try:
        return Result(
            "parsed_candidate",
            "candidate_internally_consistent",
            deepcopy(_checked(payload)),
        )
    except Invalid as exc:
        return Result("rejected", str(exc))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        return Result("rejected", "candidate_shape_invalid")


def parse_batch(payloads):
    """N one-to-one declarations for ONE operation; all-or-error, no partial view."""
    try:
        require(type(payloads) is list and 1 <= len(payloads) <= 5)
        views = [_checked(p) for p in payloads]
        require(
            all(v["basis"]["status"] == "event_recorded" for v in views),
            "candidate_batch_basis_required",
        )
        events = [v["basis"]["event"] for v in views]
        first = events[0]
        require(
            [e["effect_slot"] for e in events] == list(range(1, len(events) + 1)),
            "candidate_batch_slots_invalid",
        )
        for key in ("id", "fact_id", "change_id"):
            require(
                len({e[key] for e in events}) == len(events),
                "candidate_batch_reused_event",
            )
        require(
            len({e["selection"]["id"] for e in events}) == len(events),
            "candidate_batch_reused_event",
        )
        require(
            all(
                all(
                    e[k] == first[k]
                    for k in (
                        "session_id",
                        "project_id",
                        "operation_id",
                        "authentication_context",
                    )
                )
                for e in events
            ),
            "candidate_batch_operation_mismatch",
        )
        # All effects came from one saved body Turn, with ordered disjoint spans.
        spans = [e["statement_citations"] for e in events]
        require(all(len(c) == 1 for c in spans), "candidate_batch_sources_invalid")
        source = spans[0][0]["turn_id"]
        previous = 0
        known_turns = {}
        for view in views:
            for turn in view["turns"]:
                require(
                    turn["id"] not in known_turns or known_turns[turn["id"]] == turn,
                    "candidate_batch_sources_invalid",
                )
                known_turns[turn["id"]] = turn
        for group in spans:
            c = group[0]
            require(
                c["turn_id"] == source and c["start"] >= previous,
                "candidate_batch_sources_invalid",
            )
            previous = c["end"]
        strip = lambda text: re.sub("[ \\t\\r\\n]", "", text)
        require(
            strip(known_turns[source]["content"])
            == strip("".join(c[0]["quote"] for c in spans)),
            "candidate_batch_sources_invalid",
        )
        return Result(
            "parsed_candidate", "candidate_batch_internally_consistent", deepcopy(views)
        )
    except Invalid as exc:
        return Result("rejected", str(exc))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        return Result("rejected", "candidate_shape_invalid")


def parse_json(text):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, "candidate_duplicate_key")
            obj[key] = value
        return obj

    def number(value):
        require(not any(c in value for c in ".eE") and abs(int(value)) <= 2**53 - 1)
        return int(value)

    def invalid(_):
        raise Invalid("candidate_shape_invalid")

    try:
        require(type(text) is str and len(text) <= 150000)
        return parse(
            json.loads(
                text,
                object_pairs_hook=unique,
                parse_int=number,
                parse_float=number,
                parse_constant=invalid,
            )
        )
    except Invalid as exc:
        return Result("rejected", str(exc))
    except (ValueError, TypeError, RecursionError):
        return Result("rejected", "candidate_json_invalid")
