"""Shared Python/TS corpus plus actual SELECT-only A graph projection."""

from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import UUID
import pytest
from research.declaration_read.contract import PAIRS
from research.g3_choice_protocol.read_candidate import parse, parse_batch, parse_json
from research.g3_choice_protocol.projection import project
from research.g3_choice_protocol.runtime import Refused
from research.g3_choice_protocol.test_postgres import saved, TEXTS

CORPUS = json.loads(
    Path(__file__).with_name("read_cases.json").read_text(encoding="utf8")
)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["name"])
def test_shared_strict_event_read_corpus(case):
    value = deepcopy(CORPUS["base"])
    for path, item in case["patches"]:
        target = value
        for key in path[:-1]:
            target = target[int(key)] if type(target) is list else target[key]
        target[int(path[-1]) if type(target) is list else path[-1]] = deepcopy(item)
    before = deepcopy(value)
    result = parse(value)
    assert result.code == case["code"]
    assert result.status == (
        "parsed_candidate"
        if case["code"] == "candidate_internally_consistent"
        else "rejected"
    )
    assert (
        value == before
        and result.truth_verified is False
        and result.persistence_authorized is False
    )
    assert (
        not result.authentication_verified
        and not result.database_history_verified
        and not result.language_validation_replayed
    )
    if result.status == "rejected":
        assert result.view is None


@pytest.mark.parametrize("labels", sorted(PAIRS))
@pytest.mark.parametrize(
    "status", ["pending", "user_confirmed", "evidence_supported", "rejected"]
)
def test_all_existing_matrix_and_statuses_remain_independent_not_semantic_verification(
    labels, status
):
    value = deepcopy(CORPUS["base"])
    selection = dict(
        zip(("fact_kind", "progress_stage", "classification_contract"), labels)
    )
    value["subject"].update(selection, status=status)
    if labels[2] == "explicit-typed-v1":
        value["basis"]["event"]["classification"] = deepcopy(selection)
        value["basis"]["event"]["selection"]["classification"] = deepcopy(selection)
    else:
        value["basis"] = dict(
            status=(
                "legacy_unclassified" if labels[2] == "legacy-v0" else "not_recorded"
            ),
            event=None,
        )
    result = parse(value)
    assert (
        result.status == "parsed_candidate"
        and result.view["subject"]["status"] == status
    )
    assert not result.truth_verified and not result.language_validation_replayed
    # Text can disagree with declared labels: this parser does NOT replay c3a.
    assert result.view["subject"]["statement"] == CORPUS["base"]["subject"]["statement"]


@pytest.mark.parametrize(
    "text,code",
    [
        ('{"read_contract":1,"read_\\u0063ontract":2}', "candidate_duplicate_key"),
        ('{"x":NaN}', "candidate_shape_invalid"),
        ('{"x":9007199254740992}', "candidate_shape_invalid"),
        ('{"x":1.0}', "candidate_shape_invalid"),
        ('{"x":1e0}', "candidate_shape_invalid"),
        ('{"x":', "candidate_json_invalid"),
    ],
)
def test_strict_json_never_last_key_wins_or_numeric_coercion(text, code):
    result = parse_json(text)
    assert result.code == code and result.view is None


def batch(n=3):
    """Synthetic ONLY; no claim of stored authentication or recorded events."""
    values = []
    raw = "\r\n".join(TEXTS[:n])
    cursor = 0
    for i, quote in enumerate(TEXTS[:n]):
        value = deepcopy(CORPUS["base"])
        start = raw.index(quote, cursor)
        cursor = start + len(quote)
        cite = dict(
            turn_id=value["turns"][0]["id"], start=start, end=cursor, quote=quote
        )
        value["turns"][0]["content"] = raw
        value["subject"]["statement"] = quote
        value["text_provenance"] = dict(original=[cite], current=[cite])
        event = value["basis"]["event"]
        value["subject"]["fact_id"] = str(UUID(int=100 + i))
        event.update(
            id=str(UUID(int=200 + i)),
            fact_id=value["subject"]["fact_id"],
            change_id=str(UUID(int=300 + i)),
            effect_slot=i + 1,
            statement_citations=[cite],
        )
        event["selection"]["id"] = str(UUID(int=400 + i))
        values.append(value)
    return values


@pytest.mark.parametrize("n", [1, 3, 5])
def test_synthetic_batch_bijection_is_not_database_proof(n):
    values = batch(n)
    result = parse_batch(values)
    assert result.status == "parsed_candidate" and not result.database_history_verified
    assert (
        parse_json(json.dumps(values[0], ensure_ascii=False)).status
        == "parsed_candidate"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "event",
        "fact",
        "change",
        "selection",
        "slot",
        "auth",
        "turn_content",
        "source_reuse",
        "missing_body",
    ],
)
def test_synthetic_batch_all_or_error(fault):
    values = batch()
    a = values[0]["basis"]["event"]
    b = values[1]["basis"]["event"]
    if fault in ("event", "change"):
        b["id" if fault == "event" else "change_id"] = a[
            "id" if fault == "event" else "change_id"
        ]
    elif fault == "fact":
        b["fact_id"] = a["fact_id"]
        values[1]["subject"]["fact_id"] = a["fact_id"]
    elif fault == "selection":
        b["selection"]["id"] = a["selection"]["id"]
    elif fault == "slot":
        b["effect_slot"] = a["effect_slot"]
    elif fault == "auth":
        b["authentication_context"]["authenticated_subject"] = str(UUID(int=999))
    elif fault == "turn_content":
        values[1]["turns"][0]["content"] += "额外文字"
    elif fault == "missing_body":
        for v in values:
            v["turns"][0]["content"] += "遗漏限定语"
    else:
        values[1]["subject"]["statement"] = values[0]["subject"]["statement"]
        values[1]["text_provenance"] = deepcopy(values[0]["text_provenance"])
        b["statement_citations"] = deepcopy(a["statement_citations"])
    result = parse_batch(values)
    assert (
        result.status == "rejected"
        and result.view is None
        and not result.persistence_authorized
    )


@pytest.mark.parametrize("n", [1, 3, 5])
def test_real_pg_A_graph_to_new_candidate_is_zero_effect(model, n):
    m = model
    b = m.seed()
    _, receipt = saved(m, b, n=n)
    before = m.snapshot()
    with m.connect("reader", True) as db:
        result = project(db, b.sid, b.token, "synthetic-key")
    assert result.status == "parsed_candidate" and len(result.view) == n
    assert m.snapshot() == before
    for view, effect in zip(result.view, receipt["effects"]):
        event = view["basis"]["event"]
        assert (
            view["subject"]["fact_id"] == effect["fact_id"]
            and event["id"] == effect["id"]
        )
        assert event["source_kind"] == "immutable_user_choice_event"
        assert event["authentication_context"]["authenticated_subject"] == str(
            b.subject
        )
        assert event["selection"]["classification"] == event["classification"]
        assert event["id"] not in {t["id"] for t in view["turns"]}
        assert view["subject"]["status"] == "pending" and not result.truth_verified
        assert (
            parse_json(json.dumps(view, ensure_ascii=False)).status
            == "parsed_candidate"
        )


def test_real_B_not_silently_projected_as_A_and_unauthorized_reads_have_no_partial_view(
    model,
):
    m = model
    b = m.seed()
    other = m.seed()
    saved(m, b, scheme="B")
    before = m.snapshot()
    with pytest.raises(Refused, match="contract_mismatch"), m.connect(
        "reader", True
    ) as db:
        project(db, b.sid, b.token, "synthetic-key")
    with pytest.raises(Refused, match="resource_unavailable"), m.connect(
        "reader", True
    ) as db:
        project(db, b.sid, other.token, "synthetic-key")
    assert m.snapshot() == before


def test_real_projection_can_supply_synthetic_only_cross_language_evidence(model):
    m = model
    b = m.seed()
    saved(m, b, n=5)
    before = m.snapshot()
    with m.connect("reader", True) as db:
        result = project(db, b.sid, b.token, "synthetic-key")
    assert result.status == "parsed_candidate" and m.snapshot() == before
    # Test-harness export AFTER the read; no token, key, hashes or credentials.
    # Set the path explicitly to run the separate TS/real-PG bridge test.
    target = os.getenv("G3_PG_CANDIDATE_FILE")
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.view, ensure_ascii=False), encoding="utf8")
