"""Actual restricted SQL attack evidence, including properties NOT proved by DB.

No owner edits data to turn a rejection into success. This helper manually issues
INSERTs as the same limited writer LOGIN; it intentionally never calls c3a.
"""

from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
import pytest
from research.g3_choice_protocol.runtime import (
    command,
    digest,
    request_digest,
    apply,
    Refused,
    recover,
)


def direct_stage(db, b, text, *, fault=None, key="direct-sql"):
    body = command(b.sid, b.pid, [text])
    item = body["items"][0]
    oid, tid, fid, cid, eid = [uuid4() for _ in range(5)]
    labels = {
        k: item[k] for k in ("fact_kind", "progress_stage", "classification_contract")
    }
    db.execute(
        "INSERT INTO ref_operations(id,key_digest,scope_digest,owner_digest,contract_version,scheme,session_id,project_id,input_turn_id,item_count,base_revision,result_revision,request_digest) VALUES(%s,%s,%s,%s,3,'A',%s,%s,%s,1,1,2,%s)",
        (
            oid,
            digest(key),
            digest(str(b.sid)),
            digest(b.token),
            b.sid,
            b.pid,
            tid,
            request_digest(db, body),
        ),
    )
    ctx = db.execute(
        "SELECT ref_record_auth(%s,%s,%s) AS id", (oid, b.sid, b.token)
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO ref_turns(id,operation_id,session_id,purpose,role,content) VALUES(%s,%s,%s,'body',%s,%s)",
        (tid, oid, b.sid, "assistant" if fault == "assistant" else "user", text),
    )
    db.execute(
        "INSERT INTO ref_facts(id,operation_id,session_id,project_id,version,statement,status,memory_state,origin,fact_kind,progress_stage,classification_contract) VALUES(%s,%s,%s,%s,1,%s,'pending','unspecified','manual','personal_action','completed','explicit-typed-v1')",
        (fid, oid, b.sid, b.pid, text),
    )
    snap = dict(
        version=2 if fault == "snapshot_version" else 1,
        statement=text,
        status="pending",
        origin="manual",
        memory_state="unspecified",
        ai_run_id=None,
        evidence_id=None,
        **labels,
        original_turn_id=str(tid),
        start_cp=0,
        end_cp=len(text),
        quote=text,
        basis_id=str(eid)
    )
    db.execute(
        "INSERT INTO ref_changes(id,operation_id,session_id,fact_id,action,actor,before,after) VALUES(%s,%s,%s,%s,'created','system',%s,%s)",
        (
            cid,
            oid,
            b.sid,
            fid,
            Jsonb(None) if fault == "json_null_before" else None,
            Jsonb(snap),
        ),
    )
    db.execute(
        "INSERT INTO ref_sources(fact_id,operation_id,session_id,turn_id,start_cp,end_cp,quote) VALUES(%s,%s,%s,%s,0,%s,%s)",
        (fid, oid, b.sid, tid, len(text), text),
    )
    db.execute(
        "INSERT INTO ref_fcs(operation_id,effect_slot,session_id,fact_id,change_id,turn_id,start_cp,end_cp,quote,source_role) VALUES(%s,1,%s,%s,%s,%s,0,%s,%s,'statement')",
        (oid, b.sid, fid, cid, tid, len(text), text),
    )
    choice = (
        eid,
        oid,
        b.sid,
        b.pid,
        fid,
        cid,
        tid,
        len(text),
        text,
        item["selection_id"],
        Jsonb(labels),
        ctx,
    )
    query = """INSERT INTO ref_choices(id,operation_id,effect_slot,session_id,project_id,fact_id,fact_version,change_id,
      basis_contract,source_kind,fact_kind,progress_stage,classification_contract,statement_turn_id,start_cp,end_cp,quote,
      selection_id,selection,auth_context_id,validator_contract,validation_result)
      VALUES(%s,%s,1,%s,%s,%s,1,%s,'g3-choice-event-ref-v1','immutable_user_choice_event',
      'personal_action','completed','explicit-typed-v1',%s,0,%s,%s,%s,%s,%s,'typed-semantic-spike-v1','finite_rule_match')"""
    if fault != "missing_event":
        db.execute(query, choice)
    if fault == "duplicate_event":
        db.execute(query, choice)
    if fault == "extra_event":
        db.execute(query, (uuid4(), *choice[1:]))
    db.execute("UPDATE ref_sessions SET revision=revision+1 WHERE id=%s", (b.sid,))
    return oid


@pytest.mark.parametrize(
    "fault",
    [
        "assistant",
        "snapshot_version",
        "json_null_before",
        "missing_event",
        "duplicate_event",
        "extra_event",
    ],
)
def test_real_direct_sql_graph_invalid_without_application_validation(model, fault):
    m = model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.Error) as exc:
        with m.connect() as db:
            direct_stage(db, b, "我部署了服务。", fault=fault)
    assert exc.value.sqlstate in ("23514", "23505") and m.snapshot() == before


def test_real_db_does_not_prove_validator_executed_or_declared_completed_is_true(model):
    m = model
    b = m.seed()
    text = "我计划部署服务。"
    before = m.snapshot()
    # Normal reference adapter refuses this declared completed claim.
    with pytest.raises(Refused, match="language_not_supported"), m.connect() as db:
        apply(db, b.sid, b.token, "normal", command(b.sid, b.pid, [text]))
    assert m.snapshot() == before
    # An INSERT-capable compromised runtime can nevertheless report the fixed
    # validation label. The database proves the graph, NOT c3a execution. This
    # is a real counterexample/remaining gate, never a production guarantee.
    with m.connect() as db:
        direct_stage(db, b, text)
    committed = m.snapshot()
    with m.connect("reader", True) as db:
        result = recover(db, b.sid, b.token, "direct-sql")
    assert (
        result["truth_verified"] is False and result["persistence_authorized"] is False
    )
    assert len(result["effects"]) == 1 and m.snapshot() == committed


@pytest.mark.parametrize(
    "kind,stage,contract",
    [
        ("plan", "completed", "explicit-typed-v1"),
        ("background", "completed", "explicit-typed-v1"),
        ("personal_action", "planned", "explicit-typed-v1"),
        ("boundary", "in_progress", "explicit-typed-v1"),
        ("legacy_unspecified", "legacy_unknown", "legacy-v0"),
        ("personal_action", "completed", "unknown-v999"),
    ],
)
def test_real_reference_database_rejects_non_typed_or_illegal_pair(
    model, kind, stage, contract
):
    m = model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.errors.CheckViolation), m.connect() as db:
        db.execute(
            """INSERT INTO ref_facts(id,operation_id,session_id,project_id,version,statement,status,memory_state,origin,fact_kind,progress_stage,classification_contract)
          VALUES(%s,%s,%s,%s,1,'我部署了服务。','pending','unspecified','manual',%s,%s,%s)""",
            (uuid4(), uuid4(), b.sid, b.pid, kind, stage, contract),
        )
    assert m.snapshot() == before
