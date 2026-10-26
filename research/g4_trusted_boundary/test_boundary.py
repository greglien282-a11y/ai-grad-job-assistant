"""Real restricted LOGIN attacks. No owner data edits to manufacture safety."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import hmac
import json
import time
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from research.g3_choice_protocol.runtime import command, apply, Refused
from research.g3_choice_protocol.test_direct_sql import direct_stage
from research.g4_trusted_boundary.runtime import (
    submit,
    read,
    seal,
    permit,
    Proof,
    message,
    admit_gate,
)

TEXTS = [
    "我部署了服务。",
    "我编写了脚本。",
    "我测试了导出按钮。",
    "我制作了结果图。",
    "我整理了27条缺失记录。",
]


@pytest.mark.parametrize("n", [1, 3, 5])
def test_real_commit_and_readonly_lost_response_recovery(boundary, n):
    x = boundary
    m = x.model
    b = m.seed()
    body = command(b.sid, b.pid, TEXTS[:n])
    with m.connect() as db:
        result, state = submit(db, x.gate, b, "lost", body, issuer=x.issuer)
    saved = m.snapshot()
    with m.connect("reader", True) as db:
        recovered = read(db, x.gate, b, "lost")
    assert (
        recovered["operation_id"] == result["operation_id"]
        and len(recovered["effects"]) == n
    )
    assert (
        recovered["truth_verified"] is False
        and recovered["persistence_authorized"] is False
    )
    # Recovery and same-key POST replay work while independent service is down.
    with m.connect() as db:
        replay, state = submit(db, x.gate, b, "lost", body)
    assert state == "replayed" and replay == recovered and m.snapshot() == saved


def test_direct_insert_without_permit_cannot_commit(boundary):
    m = boundary.model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.errors.ForeignKeyViolation), m.connect() as db:
        direct_stage(db, b, "我计划部署服务。")
    assert m.snapshot() == before


@pytest.mark.parametrize(
    "text",
    [
        "我计划部署服务。",
        "我正在部署服务。",
        "我们部署了服务。",
        "我没有部署服务。",
        "如果我部署服务。",
        "我可能部署过服务。",
    ],
)
def test_normal_trusted_path_refuses_false_completed(boundary, text):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(Refused, match="language_not_supported"), m.connect() as db:
        submit(db, x.gate, b, "bad", command(b.sid, b.pid, [text]), issuer=x.issuer)
    assert m.snapshot() == before


@pytest.mark.parametrize("boundary", ["broker"], indirect=True)
def test_broker_untrusted_caller_has_no_insert_or_function_execution(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    for query, args in [
        ("INSERT INTO ref_turns(id) VALUES(%s)", (uuid4(),)),
        ("SELECT ref_record_auth(%s,%s,%s)", (uuid4(), b.sid, b.token)),
        (
            sql.SQL("SELECT {}(%s)").format(sql.Identifier(x.gate.schema, "seal")),
            (uuid4(),),
        ),
        ("SET ROLE " + m.roles["writer"], ()),
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect(
            "reader"
        ) as db:
            db.execute(query, args)
    assert m.snapshot() == before


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_fake_label_and_fake_mac_refused_by_independent_boundary(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(
        Refused, match="independent_language_refused"
    ), m.connect() as db:
        oid = direct_stage(db, b, "我计划部署服务。")
        x.issuer.issue(seal(db, x.gate, oid))
    with pytest.raises(psycopg.errors.CheckViolation), m.connect() as db:
        oid = direct_stage(db, b, "我计划部署服务。")
        forged = Proof(
            seal(db, x.gate, oid),
            str(uuid4()),
            int(time.time()) + 120,
            x.gate.validator_hash,
            b"x" * 32,
        )
        permit(db, x.gate, oid, forged)
    assert m.snapshot() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "body",
        "kind",
        "session",
        "fact",
        "version",
        "nonce",
        "expired",
        "unknown_validator",
        "mac",
    ],
)
@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_old_proof_cannot_bind_changed_graph_or_metadata(boundary, mutation):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.errors.CheckViolation), m.connect() as db:
        result, _ = apply(db, b.sid, b.token, "proof", command(b.sid, b.pid, TEXTS[:1]))
        oid = result["operation_id"]
        proof = x.issuer.issue(seal(db, x.gate, oid))
        if mutation in {"body", "kind", "session", "fact", "version"}:
            graph = json.loads(proof.seal)
            if mutation == "body":
                graph["turns"][0]["content"] = "我计划部署服务。"
            if mutation == "kind":
                graph["choices"][0]["progress_stage"] = "in_progress"
            if mutation == "session":
                graph["operation"]["session_id"] = str(uuid4())
            if mutation == "fact":
                graph["facts"][0]["id"] = str(uuid4())
            if mutation == "version":
                graph["facts"][0]["version"] = 2
            # Even a credential over caller-supplied different bytes cannot
            # replace the graph. For signature-only tampering see metadata cases.
            proof = replace(proof, seal=json.dumps(graph, ensure_ascii=False))
        if mutation == "nonce":
            proof = replace(proof, nonce=str(uuid4()))
        if mutation == "expired":
            proof = replace(proof, expires=int(time.time()) - 10)
        if mutation == "unknown_validator":
            proof = replace(proof, validator_hash="f" * 64)
        if mutation == "mac":
            proof = replace(proof, mac=b"0" * 32)
        if mutation in {"expired", "unknown_validator"}:
            # Authentic but expired / unapproved-version proof: don't confuse
            # signature failure with the independent time/version check.
            proof = replace(
                proof,
                mac=hmac.digest(
                    x.secret,
                    message(
                        proof.seal, proof.nonce, proof.expires, proof.validator_hash
                    ),
                    "sha256",
                ),
            )
        permit(db, x.gate, oid, proof)
    assert m.snapshot() == before


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_valid_proof_from_rolled_back_request_cannot_authorize_new_ids(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    with m.connect() as db:
        result, _ = apply(db, b.sid, b.token, "one", command(b.sid, b.pid, TEXTS[:1]))
        proof = x.issuer.issue(seal(db, x.gate, result["operation_id"]))
        db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation), m.connect() as db:
        result, _ = apply(db, b.sid, b.token, "two", command(b.sid, b.pid, TEXTS[:1]))
        permit(db, x.gate, result["operation_id"], proof)
    assert m.snapshot() == before


def test_missing_service_and_after_permit_failure_roll_back(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    if x.gate.mode == "credential":
        with pytest.raises(
            Refused, match="trusted_validator_unavailable"
        ), m.connect() as db:
            submit(db, x.gate, b, "offline", command(b.sid, b.pid, TEXTS[:1]))
        assert m.snapshot() == before
    with pytest.raises(RuntimeError, match="injected"), m.connect() as db:
        submit(db, x.gate, b, "fail", command(b.sid, b.pid, TEXTS[:1]), issuer=x.issuer)
        raise RuntimeError("injected")
    assert m.snapshot() == before


def test_two_connections_same_key_exactly_once(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    body = command(b.sid, b.pid, TEXTS[:3])
    barrier = Barrier(2)

    def run():
        with m.connect() as db:
            barrier.wait(timeout=10)
            return submit(db, x.gate, b, "race", body, issuer=x.issuer)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, bresult = list(pool.map(lambda _: run(), range(2)))
    assert {a[1], bresult[1]} == {"staged", "replayed"}
    assert a[0]["operation_id"] == bresult[0]["operation_id"]
    assert len(m.snapshot()["ref_facts"]) == 3 and len(m.snapshot()["g4_permits"]) == 1


def test_private_key_and_hmac_function_are_not_client_capabilities(boundary):
    x = boundary
    m = x.model
    before = m.snapshot()
    for kind in ("writer", "reader"):
        for query, args in [
            (
                sql.SQL("SELECT secret FROM {}").format(
                    sql.Identifier(x.gate.schema, "policy")
                ),
                (),
            ),
            (
                sql.SQL("SELECT {}(%s,%s)").format(
                    sql.Identifier(x.gate.schema, "hmac256")
                ),
                (b"body", b"key"),
            ),
            (
                sql.SQL("UPDATE {} SET mode='broker'").format(
                    sql.Identifier(x.gate.schema, "policy")
                ),
                (),
            ),
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), m.connect(
                kind
            ) as db:
                db.execute(query, args)
    assert m.snapshot() == before


@pytest.mark.parametrize(
    "key,msg",
    [
        (b"\x0b" * 20, b"Hi There"),
        (b"Jefe", b"what do ya want for nothing?"),
        (b"x" * 131, b"long key"),
    ],
)
def test_sql_hmac_matches_independent_python_rfc_algorithm(boundary, key, msg):
    x = boundary
    m = x.model
    # Privileged algorithm test OUTSIDE request. No ACL widened for the writer.
    actual = m.admin.execute(
        sql.SQL("SELECT {}(%s,%s) AS value").format(
            sql.Identifier(x.gate.schema, "hmac256")
        ),
        (msg, key),
    ).fetchone()["value"]
    assert actual == hmac.digest(key, msg, "sha256")


def test_temp_shadow_and_changed_validator_manifest_fail_closed(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(
        Refused, match="reference_runtime_unapproved"
    ), m.connect() as db:
        db.execute("CREATE TEMP TABLE ref_operations(id uuid)")
        submit(
            db, x.gate, b, "shadow", command(b.sid, b.pid, TEXTS[:1]), issuer=x.issuer
        )
    from copy import copy

    changed = copy(x.gate)
    changed.validator_hash = "e" * 64
    with pytest.raises(
        Refused, match="validator_version_unapproved"
    ), m.connect() as db:
        submit(
            db,
            changed,
            b,
            "new-code",
            command(b.sid, b.pid, TEXTS[:1]),
            issuer=x.issuer,
        )
    assert m.snapshot() == before


def test_trust_root_compromise_remains_real_counterexample(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    # This is explicitly NOT an attack by an ordinary A caller. It compromises
    # the private Broker identity, or B's independent signing authority/key.
    # DB graph integrity cannot prove natural-language truth under this threat.
    with m.connect() as db:
        oid = direct_stage(db, b, "我计划部署服务。")
        if x.gate.mode == "broker":
            permit(db, x.gate, oid)
        else:
            text = seal(db, x.gate, oid)
            nonce = str(uuid4())
            expiry = int(time.time()) + 120
            proof = Proof(
                text,
                nonce,
                expiry,
                x.gate.validator_hash,
                hmac.digest(
                    x.secret,
                    message(text, nonce, expiry, x.gate.validator_hash),
                    "sha256",
                ),
            )
            permit(db, x.gate, oid, proof)
    assert len(m.snapshot()["ref_facts"]) == 1


@pytest.mark.parametrize("fault", ["function", "public_execute", "missing_fk"])
def test_owner_injected_deployment_fault_admission_stops_before_writes(boundary, fault):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    # Owner arranges a deployment fault outside the request, never substitutes
    # for the limited runtime. The service must refuse its changed manifest.
    if fault == "function":
        m.admin.execute(
            sql.SQL("ALTER FUNCTION {}(uuid) COST 999").format(
                sql.Identifier(x.gate.schema, "seal")
            )
        )
    elif fault == "public_execute":
        m.admin.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {}(uuid) TO PUBLIC").format(
                sql.Identifier(x.gate.schema, "seal")
            )
        )
    else:
        m.admin.execute("ALTER TABLE ref_operations DROP CONSTRAINT g4_permit_required")
    with pytest.raises(
        Refused, match="trusted_boundary_unavailable"
    ), m.connect() as db:
        submit(
            db, x.gate, b, "fault", command(b.sid, b.pid, TEXTS[:1]), issuer=x.issuer
        )
    assert m.snapshot() == before


def test_wrong_identity_and_context_revision_are_zero_effect(boundary):
    from copy import copy

    x = boundary
    m = x.model
    b = m.seed()
    other = m.seed()
    before = m.snapshot()
    wrong = copy(b)
    wrong.token = other.token
    for subject, body, code in [
        (wrong, command(b.sid, b.pid, TEXTS[:1]), "resource_unavailable"),
        (b, command(b.sid, b.pid, TEXTS[:1], revision=2), "context_conflict"),
    ]:
        with pytest.raises(Refused, match=code), m.connect() as db:
            submit(db, x.gate, subject, "no", body, issuer=x.issuer)
    assert m.snapshot() == before


@pytest.mark.parametrize("mode", ["mode", "empty_mac", "other_schema"])
@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_direct_sql_cannot_relabel_b_as_a_or_omit_credential(boundary, mode):
    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    with pytest.raises(psycopg.errors.CheckViolation), m.connect() as db:
        oid = direct_stage(db, b, TEXTS[0])
        proof = x.issuer.issue(seal(db, x.gate, oid))
        if mode == "mode":
            permit(db, x.gate, oid)
        elif mode == "empty_mac":
            permit(db, x.gate, oid, replace(proof, mac=b""))
        else:
            g = json.loads(proof.seal)
            g["schema"] = "g3_ref_" + uuid4().hex
            permit(db, x.gate, oid, replace(proof, seal=json.dumps(g)))
    assert m.snapshot() == before


def test_choice_pending_and_hash_only_permit_do_not_claim_verification(boundary):
    x = boundary
    m = x.model
    b = m.seed()
    with m.connect() as db:
        submit(
            db,
            x.gate,
            b,
            "plan",
            command(b.sid, b.pid, ["我计划部署服务。"], kind="plan", stage="planned"),
            issuer=x.issuer,
        )
    rows = m.snapshot()
    fact = json.loads(rows["ref_facts"][0]["row"])
    assert (
        fact["fact_kind"],
        fact["progress_stage"],
        fact["status"],
        fact["version"],
        fact["evidence_id"],
    ) == ("plan", "planned", "pending", 1, None)
    row = json.loads(rows["g4_permits"][0]["row"])
    assert len(row["seal"]) == 64 and "我计划" not in row["seal"]


def test_modified_broker_code_is_not_an_independent_validator(boundary, monkeypatch):
    from types import SimpleNamespace
    import research.g3_choice_protocol.runtime as g3

    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    monkeypatch.setattr(
        g3,
        "validate_candidate",
        lambda payload: SimpleNamespace(status="eligible_candidate"),
    )
    if x.gate.mode == "credential":
        with pytest.raises(
            Refused, match="independent_language_refused"
        ), m.connect() as db:
            submit(
                db,
                x.gate,
                b,
                "modified",
                command(b.sid, b.pid, ["我计划部署服务。"]),
                issuer=x.issuer,
            )
        assert m.snapshot() == before
    else:
        # Compromised trusted Broker implementation remains a real trust root.
        with m.connect() as db:
            submit(
                db,
                x.gate,
                b,
                "modified",
                command(b.sid, b.pid, ["我计划部署服务。"]),
                issuer=x.issuer,
            )
        assert len(m.snapshot()["ref_facts"]) == 1


@pytest.mark.parametrize("point", ["before", "after"])
def test_real_process_kill_before_and_after_commit(boundary, point):
    import subprocess
    import sys
    from pathlib import Path

    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    payload = dict(
        dsn=m.dsn("writer"),
        gate=vars(x.gate),
        b=dict(sid=str(b.sid), token=b.token),
        secret=x.secret.hex(),
        body=command(b.sid, b.pid, TEXTS[:3]),
    )
    p = subprocess.Popen(
        [sys.executable, "-B", str(Path(__file__).with_name("crash_worker.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf8",
    )
    try:
        p.stdin.write(json.dumps(payload) + "\n")
        p.stdin.flush()
        assert p.stdout.readline().strip() == "STAGED"
        if point == "after":
            p.stdin.write("COMMIT\n")
            p.stdin.flush()
            assert p.stdout.readline().strip() == "COMMITTED"
        p.kill()
        p.wait(timeout=10)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)
        p.stdin.close()
        p.stdout.close()
        p.stderr.close()
    if point == "before":
        assert m.snapshot() == before
    else:
        saved = m.snapshot()
        with m.connect("reader", True) as db:
            result = read(db, x.gate, b, "crash")
        assert len(result["effects"]) == 3 and saved == m.snapshot()


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_independent_signer_real_process_and_unavailable_service(boundary):
    import os
    from research.g4_trusted_boundary.issuer_process import ProcessIssuer

    x = boundary
    m = x.model
    b = m.seed()
    before = m.snapshot()
    service = ProcessIssuer(x.secret, x.gate.validator_hash)
    try:
        assert service.process.pid != os.getpid() and not hasattr(service, "_secret")
        with pytest.raises(
            Refused, match="independent_language_refused"
        ), m.connect() as db:
            oid = direct_stage(db, b, "我计划部署服务。")
            service.issue(seal(db, x.gate, oid))
        assert m.snapshot() == before
        with m.connect() as db:
            submit(
                db,
                x.gate,
                b,
                "separate",
                command(b.sid, b.pid, TEXTS[:1]),
                issuer=service,
            )
        committed = m.snapshot()
        service.process.kill()
        service.process.wait(timeout=10)
        with pytest.raises(
            Refused, match="trusted_validator_unavailable"
        ), m.connect() as db:
            submit(
                db,
                x.gate,
                b,
                "offline",
                command(b.sid, b.pid, TEXTS[1:2], revision=2),
                issuer=service,
            )
        assert m.snapshot() == committed
    finally:
        service.close()


@pytest.mark.parametrize("attack", ["UPDATE", "DELETE", "TRUNCATE"])
def test_permit_immutable_even_with_extra_synthetic_mutator_privileges(
    boundary, attack
):
    x = boundary
    m = x.model
    b = m.seed()
    with m.connect() as db:
        submit(
            db,
            x.gate,
            b,
            "immutable",
            command(b.sid, b.pid, TEXTS[:1]),
            issuer=x.issuer,
        )
    before = m.snapshot()
    # Privilege fault arranged outside request; this mutation has a different
    # shape than G3 rows and needs its own trigger, not OLD.session_id access.
    m.admin.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(x.gate.schema), sql.Identifier(m.roles["mutator"])
        )
    )
    m.admin.execute(
        sql.SQL("GRANT UPDATE,DELETE,TRUNCATE ON {} TO {}").format(
            sql.Identifier(x.gate.schema, "permits"), sql.Identifier(m.roles["mutator"])
        )
    )
    query = sql.SQL(
        attack + " " + ("FROM " if attack == "DELETE" else "") + "{}"
    ).format(sql.Identifier(x.gate.schema, "permits"))
    if attack == "UPDATE":
        query += sql.SQL(" SET mode='broker'")
    with pytest.raises(
        psycopg.errors.CheckViolation, match="g4_permit_immutable"
    ), m.connect("mutator") as db:
        db.execute(query)
    assert m.snapshot() == before
