"""Actual PostgreSQL proofs, never claims about the formal 0015 schema."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
import psycopg
from psycopg import sql
from research.g3_choice_protocol.runtime import (
    apply,
    recover,
    command,
    digest,
    Refused,
    TABLES,
)

TEXTS = [
    "我部署了服务。",
    "我编写了脚本。",
    "我制作了👩‍💻原型图。",
    "我测试了导出按钮。",
    "我整理了27条缺失记录。",
]


@pytest.mark.parametrize("scheme", ["A", "B"])
@pytest.mark.parametrize(
    "text,kind,stage",
    [
        ("我部署了服务。", "personal_action", "completed"),
        ("我正在部署服务。", "personal_action", "in_progress"),
        ("我计划部署服务。", "plan", "planned"),
        ("我正在准备部署服务。", "plan", "in_progress"),
        ("团队部署了服务。", "background", "not_applicable"),
        ("我没有部署服务。", "boundary", "not_applicable"),
    ],
)
def test_real_six_typed_pairs_keep_pending_and_do_not_infer_trust(
    model, scheme, text, kind, stage
):
    m = model
    b = m.seed()
    with m.connect() as db:
        apply(
            db,
            b.sid,
            b.token,
            "typed-pair",
            command(b.sid, b.pid, [text], scheme=scheme, kind=kind, stage=stage),
        )
    row = m.admin.execute(
        "SELECT status,memory_state,evidence_id,fact_kind,progress_stage FROM ref_facts"
    ).fetchone()
    assert row == dict(
        status="pending",
        memory_state="unspecified",
        evidence_id=None,
        fact_kind=kind,
        progress_stage=stage,
    )
    before = m.snapshot()
    with m.connect("reader", True) as db:
        result = recover(db, b.sid, b.token, "typed-pair", scheme=scheme)
    assert not result["truth_verified"] and m.snapshot() == before


@pytest.mark.parametrize("scheme", ["A", "B"])
def test_real_later_unrelated_operation_can_repeat_labels_but_not_event_identity(
    model, scheme
):
    m = model
    b = m.seed()
    body, prior = saved(m, b, scheme=scheme)
    with m.connect() as db:
        apply(
            db,
            b.sid,
            b.token,
            "later",
            command(b.sid, b.pid, TEXTS[1:2], revision=2, scheme=scheme),
        )
    assert (
        m.admin.execute("SELECT revision FROM ref_sessions").fetchone()["revision"] == 3
    )
    choices = m.admin.execute("SELECT id,selection_id FROM ref_choices").fetchall()
    assert (
        len({c["id"] for c in choices})
        == len({c["selection_id"] for c in choices})
        == 2
    )
    before = m.snapshot()
    with m.connect("reader", True) as db:
        assert recover(db, b.sid, b.token, "synthetic-key", scheme=scheme) == prior
    with m.connect() as db:
        assert apply(db, b.sid, b.token, "synthetic-key", body)[1] == "replayed"
    assert m.snapshot() == before


def saved(m, b, *, scheme="A", n=1, key="synthetic-key"):
    value = command(b.sid, b.pid, TEXTS[:n], scheme=scheme)
    with m.connect() as db:
        result, tag = apply(db, b.sid, b.token, key, value)
    assert tag == "staged" and result["status"] == "uncommitted_reference_graph"
    with m.connect("reader", True) as db:
        result = recover(db, b.sid, b.token, key, scheme=scheme)
    assert (
        result["truth_verified"] is False and result["persistence_authorized"] is False
    )
    return value, result


@pytest.mark.parametrize("scheme", ["A", "B"])
@pytest.mark.parametrize("n", [1, 3, 5])
def test_real_n_graph_and_authenticated_distinct_choices(model, scheme, n):
    m = model
    b = m.seed()
    value, result = saved(m, b, scheme=scheme, n=n)
    assert len(result["effects"]) == n
    with m.connect("reader", True) as db:
        assert db.execute("SELECT count(*) AS n FROM ref_turns").fetchone()["n"] == (
            1 if scheme == "A" else 2
        )
        rows = db.execute("SELECT * FROM ref_choices ORDER BY effect_slot").fetchall()
        assert (
            len({r["id"] for r in rows})
            == len({r["selection_id"] for r in rows})
            == len({r["fact_id"] for r in rows})
            == n
        )
        ctx = db.execute("SELECT * FROM ref_auth_contexts").fetchone()
        assert (
            ctx["authenticated_subject"] == b.subject
            and ctx["db_login"] == m.roles["writer"]
        )
        assert ctx["issuer"] == "synthetic-server-auth-v1"
        assert all(
            r["auth_context_id"] == ctx["id"] and r["fact_version"] == 1 for r in rows
        )
        assert all(
            r["source_kind"]
            == ("immutable_user_choice_event" if scheme == "A" else "conversation_turn")
            for r in rows
        )
        assert all(r["created_xid"] == ctx["created_xid"] for r in rows)
        assert (
            db.execute("SELECT revision FROM ref_sessions").fetchone()["revision"] == 2
        )
    before = m.snapshot()
    with m.connect() as db:
        replay, tag = apply(db, b.sid, b.token, "synthetic-key", value)
    assert tag == "replayed" and replay == result and m.snapshot() == before
    with m.connect("reader", True) as db:
        assert recover(db, b.sid, b.token, "synthetic-key", scheme=scheme) == result
    assert m.snapshot() == before


@pytest.mark.parametrize("scheme", ["A", "B"])
@pytest.mark.parametrize(
    "fault",
    [
        "missing_choice",
        "version",
        "quote_offset",
        "project",
        "auth_context",
        "selection",
        "snapshot",
    ],
)
def test_real_commit_refuses_bad_graph_and_rolls_back_every_table(model, scheme, fault):
    m = model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.Error) as exc:
        with m.connect() as db:
            staged, tag = apply(
                db,
                b.sid,
                b.token,
                "bad-graph",
                command(b.sid, b.pid, TEXTS[:3], scheme=scheme),
                fault=fault,
            )
            assert (
                tag == "staged"
            )  # errors in deferred graph validation happen at COMMIT
    assert exc.value.sqlstate in ("23514", "23503")
    assert m.snapshot() == before


def test_real_B_wrong_choice_turn_is_not_original_source(model):
    m = model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.Error), m.connect() as db:
        apply(
            db,
            b.sid,
            b.token,
            "bad-turn",
            command(b.sid, b.pid, TEXTS[:3], scheme="B"),
            fault="choice_turn",
        )
    assert m.snapshot() == before


@pytest.mark.parametrize("scheme", ["A", "B"])
def test_real_duplicate_selection_and_actor_forgery_not_accepted(model, scheme):
    m = model
    b = m.seed()
    body = command(b.sid, b.pid, TEXTS[:3], scheme=scheme)
    before = m.snapshot()
    body["items"][1]["selection_id"] = body["items"][0]["selection_id"]
    with pytest.raises(psycopg.errors.UniqueViolation), m.connect() as db:
        apply(db, b.sid, b.token, "duplicate", body)
    assert m.snapshot() == before
    body = command(b.sid, b.pid, TEXTS[:1], scheme=scheme)
    body["actor"] = "user"
    with pytest.raises(Refused, match="contract_unsupported"), m.connect() as db:
        apply(db, b.sid, b.token, "forged", body)
    assert m.snapshot() == before
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect() as db:
        db.execute(
            "INSERT INTO ref_auth_contexts(id,operation_id,session_id,project_id,authenticated_subject,issuer,db_login) VALUES(%s,%s,%s,%s,%s,'synthetic-server-auth-v1',current_user)",
            (uuid4(), uuid4(), b.sid, b.pid, b.subject),
        )
    assert m.snapshot() == before


@pytest.mark.parametrize("scheme", ["A", "B"])
def test_real_authentication_precedes_contract_and_history_information(model, scheme):
    m = model
    b = m.seed()
    other = m.seed()
    value, result = saved(m, b, scheme=scheme)
    before = m.snapshot()
    with pytest.raises(Refused, match="resource_unavailable"), m.connect() as db:
        apply(
            db, b.sid, other.token, "synthetic-key", {**value, "contract_version": 99}
        )
    with pytest.raises(Refused, match="resource_unavailable"), m.connect(
        "reader", True
    ) as db:
        recover(db, b.sid, other.token, "synthetic-key", version=99, scheme=scheme)
    with pytest.raises(Refused, match="resource_unavailable"), m.connect(
        "reader", True
    ) as db:
        recover(db, other.sid, other.token, "synthetic-key", scheme=scheme)
    assert m.snapshot() == before


@pytest.mark.parametrize("scheme", ["A", "B"])
@pytest.mark.parametrize("case", ["same", "payload", "other_key"])
def test_real_two_connection_serialization(model, scheme, case):
    m = model
    b = m.seed()
    barrier = Barrier(2)
    a = command(b.sid, b.pid, TEXTS[:1], scheme=scheme)
    z = (
        deepcopy(a)
        if case == "same"
        else command(b.sid, b.pid, TEXTS[1:2], scheme=scheme)
    )

    def worker(key, body):
        try:
            with m.connect() as db:
                barrier.wait(timeout=10)
                return apply(db, b.sid, b.token, key, body)[1]
        except Refused as e:
            return str(e)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f = pool.submit(worker, "K", a)
        g = pool.submit(worker, "Z" if case == "other_key" else "K", z)
        results = [f.result(timeout=20), g.result(timeout=20)]
    assert sorted(results) == sorted(
        [
            "staged",
            {
                "same": "replayed",
                "payload": "payload_mismatch",
                "other_key": "context_conflict",
            }[case],
        ]
    )
    assert len(m.snapshot()["ref_operations"]) == len(m.snapshot()["ref_facts"]) == 1


@pytest.mark.parametrize("scheme", ["A", "B"])
def test_real_review_marker_new_key_cannot_waive_and_old_replay_remains(model, scheme):
    m = model
    b = m.seed()
    body, result = saved(m, b, scheme=scheme)
    m.admin.execute(
        "UPDATE ref_sessions SET new_command_review_required=true WHERE id=%s", (b.sid,)
    )
    before = m.snapshot()
    with pytest.raises(Refused, match="requires_review"), m.connect() as db:
        apply(
            db,
            b.sid,
            b.token,
            "new-key",
            command(b.sid, b.pid, TEXTS[1:2], scheme=scheme, revision=2),
        )
    with m.connect() as db:
        assert apply(db, b.sid, b.token, "synthetic-key", body)[1] == "replayed"
    with m.connect("reader", True) as db:
        assert recover(db, b.sid, b.token, "synthetic-key", scheme=scheme) == result
    assert m.snapshot() == before


@pytest.mark.parametrize("scheme", ["A", "B"])
def test_real_delete_tombstone_no_sensitive_graph_or_revival(model, scheme):
    m = model
    b = m.seed()
    body, result = saved(m, b, scheme=scheme)
    other = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect("eraser") as db:
        db.execute("SELECT ref_erase(%s,%s)", (b.sid, other.token))
    assert m.snapshot() == before
    with m.connect("eraser") as db:
        db.execute("SELECT ref_erase(%s,%s)", (b.sid, b.token))
    state = m.snapshot()
    for table in TABLES[2:]:
        assert state[table] == []
    row = m.admin.execute("SELECT * FROM ref_operations").fetchone()
    assert row["state"] == "deleted" and all(
        row[k] is None
        for k in (
            "session_id",
            "project_id",
            "input_turn_id",
            "choice_turn_id",
            "item_count",
            "base_revision",
            "result_revision",
            "request_digest",
        )
    )
    before = m.snapshot()
    with pytest.raises(Refused, match="deleted"), m.connect("reader", True) as db:
        recover(db, b.sid, b.token, "synthetic-key", scheme=scheme)
    with pytest.raises(Refused, match="resource_unavailable"), m.connect(
        "reader", True
    ) as db:
        recover(db, b.sid, other.token, "synthetic-key", scheme=scheme)
    with pytest.raises(Refused), m.connect() as db:
        apply(db, b.sid, b.token, "synthetic-key", body)
    assert m.snapshot() == before
