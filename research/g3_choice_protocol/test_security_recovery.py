"""Reference LOGIN/ACL, actual process termination and collision evidence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from research.g3_choice_protocol.runtime import (
    apply,
    recover,
    command,
    digest,
    Refused,
    TABLES,
    admit,
)
from research.g3_choice_protocol.test_postgres import saved, TEXTS


@pytest.mark.parametrize("scheme", ["A", "B"])
@pytest.mark.parametrize("point", ["before_commit", "after_commit"])
def test_real_process_kill_and_readonly_recovery(model, scheme, point):
    m = model
    b = m.seed()
    body = command(b.sid, b.pid, TEXTS[:3], scheme=scheme)
    before = m.snapshot()
    config = dict(
        dsn=m.dsn("writer"),
        sid=str(b.sid),
        token=b.token,
        key="crash",
        body=body,
        point=point,
    )
    process = subprocess.Popen(
        [sys.executable, "-B", str(Path(__file__).with_name("crash_worker.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        process.stdin.write(json.dumps(config, ensure_ascii=True) + "\n")
        process.stdin.flush()
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                line = pool.submit(process.stdout.readline).result(timeout=15).strip()
            except BaseException:
                # Kill before executor shutdown waits for the blocked pipe.
                process.kill()
                process.wait(timeout=10)
                raise
        assert line == ("STAGED" if point == "before_commit" else "COMMITTED")
        if point == "before_commit":
            assert m.snapshot() == before
        process.kill()
        process.wait(timeout=10)
        assert process.returncode != 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdin.close()
        process.stdout.close()
    if point == "before_commit":
        assert m.snapshot() == before
        with pytest.raises(Refused, match="not_found"), m.connect("reader", True) as db:
            recover(db, b.sid, b.token, "crash", scheme=scheme)
        assert m.snapshot() == before
    else:
        committed = m.snapshot()
        with m.connect("reader", True) as db:
            result = recover(db, b.sid, b.token, "crash", scheme=scheme)
        assert len(result["effects"]) == 3
        assert m.snapshot() == committed
        with m.connect() as db:
            replay, kind = apply(db, b.sid, b.token, "crash", body)
        assert kind == "replayed" and replay == result and m.snapshot() == committed


@pytest.mark.parametrize("stored", [1, 2, 3])
@pytest.mark.parametrize("requested", [1, 2, 3])
def test_real_reference_collision_domain_with_opaque_old_versions(
    model, stored, requested
):
    m = model
    b = m.seed()
    body = command(b.sid, b.pid, TEXTS[:1])
    if stored == 3:
        saved(m, b, key="collision")
    else:
        legacy = dict(
            contract_version=stored,
            scheme="opaque",
            opaque_reference="not-a-formal-receipt",
        )
        # Only fixture owner arranges an opaque OLD marker; the normal request
        # path never creates v1/v2 records or rewrites a real legacy receipt.
        with m.connect() as db:
            from research.g3_choice_protocol.runtime import request_digest

            tag = request_digest(db, legacy)
        m.admin.execute(
            "INSERT INTO ref_operations(id,key_digest,scope_digest,owner_digest,contract_version,scheme,session_id,project_id,item_count,request_digest) VALUES(%s,%s,%s,%s,%s,'opaque',%s,%s,0,%s)",
            (
                uuid4(),
                digest("collision"),
                digest(str(b.sid)),
                digest(b.token),
                stored,
                b.sid,
                b.pid,
                tag,
            ),
        )
    before = m.snapshot()
    scheme = "A" if requested == 3 else "opaque"
    if stored == requested:
        with m.connect("reader", True) as db:
            result = recover(
                db, b.sid, b.token, "collision", version=requested, scheme=scheme
            )
        assert result["contract_version"] == stored
    else:
        with pytest.raises(Refused, match="contract_mismatch"), m.connect(
            "reader", True
        ) as db:
            recover(db, b.sid, b.token, "collision", version=requested, scheme=scheme)
    if stored in (1, 2):
        with m.connect() as db:
            assert apply(db, b.sid, b.token, "collision", legacy)[1] == "replayed"
        with pytest.raises(Refused, match="contract_mismatch"), m.connect() as db:
            apply(db, b.sid, b.token, "collision", body)
    assert m.snapshot() == before


@pytest.mark.parametrize(
    "field",
    [
        "content",
        "base_revision",
        "scheme",
        "fact_kind",
        "progress_stage",
        "selection_id",
        "start",
        "end",
        "quote",
    ],
)
def test_real_same_key_payload_identity_covers_choices_and_versions(model, field):
    m = model
    b = m.seed()
    body, result = saved(m, b)
    changed = deepcopy(body)
    if field == "content":
        changed[field] = "我编写了脚本。"
    elif field == "base_revision":
        changed[field] += 1
    elif field == "scheme":
        changed[field] = "B"
    elif field == "selection_id":
        changed["items"][0][field] = str(uuid4())
    elif field in ("start", "end"):
        changed["items"][0][field] += 1
    else:
        changed["items"][0][field] = "different"
    before = m.snapshot()
    with pytest.raises(
        Refused, match="contract_mismatch" if field == "scheme" else "payload_mismatch"
    ), m.connect() as db:
        apply(db, b.sid, b.token, "synthetic-key", changed)
    assert m.snapshot() == before


@pytest.mark.parametrize("table", TABLES[1:])
@pytest.mark.parametrize("action", ["update", "delete", "truncate"])
def test_real_immutable_graph_even_for_test_mutator_login(model, table, action):
    m = model
    b = m.seed()
    saved(m, b, scheme="B", n=3)
    before = m.snapshot()
    query = {
        "update": (
            f"UPDATE {table} SET operation_id=operation_id"
            if table != "ref_operations"
            else "UPDATE ref_operations SET scheme=scheme"
        ),
        "delete": f"DELETE FROM {table}",
        "truncate": f"TRUNCATE {table} CASCADE",
    }[action]
    with pytest.raises(psycopg.errors.CheckViolation, match="ref_immutable"), m.connect(
        "mutator"
    ) as db:
        db.execute(query)
    assert m.snapshot() == before


def test_real_role_boundaries_readonly_owner_and_credential_not_client_actor(model):
    m = model
    b = m.seed()
    body, result = saved(m, b)
    before = m.snapshot()
    with m.connect("reader", True) as db:
        result = recover(db, b.sid, b.token, "synthetic-key")
        assert (
            db.execute(
                "SELECT current_setting('transaction_isolation') AS v"
            ).fetchone()["v"]
            == "repeatable read"
        )
        assert result["persistence_authorized"] is False
    with pytest.raises(Refused, match="readonly_snapshot_required"), m.connect(
        "reader"
    ) as db:
        recover(db, b.sid, b.token, "synthetic-key")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect("reader") as db:
        db.execute("SELECT ref_record_auth(%s,%s,%s)", (uuid4(), b.sid, b.token))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect(
        "reader", True
    ) as db:
        db.execute("SELECT ref_lock_operation(%s)", (digest("synthetic-key"),))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect() as db:
        db.execute("SELECT * FROM ref_operations FOR UPDATE")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect() as db:
        db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(m.roles["owner"])))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect() as db:
        db.execute("UPDATE ref_choices SET fact_version=2")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect("reader") as db:
        db.execute("CREATE TABLE unauthorized(id integer)")
    with pytest.raises(Refused, match="reference_runtime_unapproved"):
        admit(m.admin)
    assert m.snapshot() == before


def test_real_revision_cannot_be_bumped_without_an_atomic_graph(model):
    m = model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(
        psycopg.errors.CheckViolation, match="ref_revision_without_operation"
    ), m.connect() as db:
        db.execute("UPDATE ref_sessions SET revision=revision+1 WHERE id=%s", (b.sid,))
    assert m.snapshot() == before


def test_real_auth_function_qualified_against_temporary_table_shadow(model):
    m = model
    b = m.seed()
    before = m.snapshot()
    with m.connect() as db:
        db.execute("CREATE TEMP TABLE ref_sessions(id uuid,credential_hash text)")
        db.execute(
            "INSERT INTO pg_temp.ref_sessions VALUES(%s,%s)",
            (b.sid, digest("forged-token")),
        )
        assert (
            db.execute(
                "SELECT ref_authorize(%s,%s) AS valid", (b.sid, "forged-token")
            ).fetchone()["valid"]
            is False
        )
    assert m.snapshot() == before


def test_real_tombstone_not_deletable_and_foreign_session_post_cannot_probe(model):
    m = model
    b = m.seed()
    body, result = saved(m, b, n=5, scheme="B")
    other = m.seed()
    with m.connect("eraser") as db:
        db.execute("SELECT ref_erase(%s,%s)", (b.sid, b.token))
    before = m.snapshot()
    with pytest.raises(psycopg.errors.CheckViolation, match="ref_immutable"), m.connect(
        "mutator"
    ) as db:
        db.execute("DELETE FROM ref_operations")
    with pytest.raises(Refused, match="resource_unavailable"), m.connect() as db:
        apply(
            db,
            other.sid,
            other.token,
            "synthetic-key",
            command(other.sid, other.pid, TEXTS[:1]),
        )
    assert m.snapshot() == before


@pytest.mark.parametrize(
    "defect",
    [
        "missing_select",
        "extra_update",
        "schema_create",
        "public_execute",
        "function_search_path",
        "disabled_trigger",
        "missing_table",
    ],
)
def test_real_admission_fails_closed_on_acl_or_schema_fault(model, defect):
    m = model
    b = m.seed()
    saved(m, b)
    before = m.snapshot()
    # Owner arranges a fault outside the request; no owner request can turn red
    # data green. The actual recovery must still use the restricted LOGIN.
    target = sql.Identifier(m.schema, "ref_choices")
    role = sql.Identifier(m.roles["reader"])
    if defect == "missing_select":
        m.admin.execute(sql.SQL("REVOKE SELECT ON {} FROM {}").format(target, role))
    elif defect == "extra_update":
        m.admin.execute(
            sql.SQL("GRANT UPDATE(fact_version) ON {} TO {}").format(target, role)
        )
    elif defect == "schema_create":
        m.admin.execute(
            sql.SQL("GRANT CREATE ON SCHEMA {} TO {}").format(
                sql.Identifier(m.schema), role
            )
        )
    elif defect == "public_execute":
        m.admin.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {}(uuid,uuid,text) TO PUBLIC").format(
                sql.Identifier(m.schema, "ref_record_auth")
            )
        )
    elif defect == "function_search_path":
        m.admin.execute(
            sql.SQL("ALTER FUNCTION {}(uuid) SET search_path=public").format(
                sql.Identifier(m.schema, "ref_validate")
            )
        )
    elif defect == "disabled_trigger":
        m.admin.execute(
            sql.SQL("ALTER TABLE {} DISABLE TRIGGER ref_consistency").format(target)
        )
    else:
        m.admin.execute(
            sql.SQL("ALTER TABLE {} RENAME TO missing_choices").format(target)
        )
    with pytest.raises(
        Refused,
        match="reference_(acl_unapproved|function_unapproved|schema_unavailable)",
    ), m.connect("reader", True) as db:
        recover(db, b.sid, b.token, "synthetic-key")
    if defect != "missing_table":
        assert m.snapshot() == before
    else:
        m.admin.execute(
            sql.SQL("ALTER TABLE {} RENAME TO ref_choices").format(
                sql.Identifier(m.schema, "missing_choices")
            )
        )
        assert m.snapshot() == before


@pytest.mark.parametrize("column", ["recorded_at", "created_xid", "expires_at"])
def test_real_client_cannot_override_server_metadata(model, column):
    m = model
    b = m.seed()
    saved(m, b)
    before = m.snapshot()
    with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect() as db:
        db.execute(
            sql.SQL(
                "INSERT INTO ref_operations(id,{}) SELECT id,{} FROM ref_operations"
            ).format(sql.Identifier(column), sql.Identifier(column))
        )
    assert m.snapshot() == before


@pytest.mark.parametrize("scheme", ["A", "B"])
def test_real_reverse_scheme_collision_and_unknown_version_never_reexecute(
    model, scheme
):
    m = model
    b = m.seed()
    body, _ = saved(m, b, scheme=scheme)
    before = m.snapshot()
    for version, other in (
        (3, "B" if scheme == "A" else "A"),
        (0, scheme),
        (4, scheme),
    ):
        with pytest.raises(Refused, match="contract_mismatch"), m.connect(
            "reader", True
        ) as db:
            recover(db, b.sid, b.token, "synthetic-key", version=version, scheme=other)
        with pytest.raises(Refused, match="contract_mismatch"), m.connect() as db:
            apply(
                db,
                b.sid,
                b.token,
                "synthetic-key",
                {**body, "contract_version": version, "scheme": other},
            )
    assert m.snapshot() == before
