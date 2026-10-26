"""True old COs, HMACs, LOGIN roles, GET recovery and future reference graph."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic import command as alembic
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from app import facts, idempotency as idem
from app.fact_maintenance_models import ConversationOperation
from app.maintenance_errors import ConversationError
from test_maintenance_api import (
    seed,
    key,
    command,
    post as post1,
    recovery as recover1,
    current,
    KIND,
    error,
)
from test_append_api import body, post as post2, recover as recover2
from research.g3_choice_protocol.runtime import command as future_body, digest
from research.g4_trusted_boundary.runtime import submit, read
from research.g4_real_co_interop.preflight import prepare


def all_tables(factory):
    with factory() as db:
        names = db.scalars(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename"
            )
        ).all()
        return {
            n: db.scalars(
                text(
                    f'SELECT to_jsonb(t)::text FROM "{n}" t ORDER BY to_jsonb(t)::text'
                )
            ).all()
            for n in names
        }


def attach_reference(x, b):
    # Synthetic fixture provisioning BEFORE request, same identity/scope/real
    # Bearer, separate disposable store. Never edit the formal old history.
    x.model.admin.execute(
        "INSERT INTO ref_sessions(id,project_id,subject_id,credential_hash,revision) VALUES(%s,%s,%s,%s,%s)",
        (b.sid, b.pid, uuid4(), digest(b.token), b.revision),
    )


@pytest.mark.parametrize("first", [1, 2])
@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_real_old_receipts_then_future_graph_get_only_and_collision(
    append_service, boundary, first
):
    s = append_service
    x = boundary
    b = seed(s)
    h = key(b)
    value = command(b) if first == 1 else body(b)
    post, recover = (post1, recover1) if first == 1 else (post2, recover2)
    original = post(s, b, value, h)
    assert original.status_code == 201, original.text
    original = original.json()
    current(s, b)
    attach_reference(x, b)
    fbody = future_body(b.sid, b.pid, ["我部署了服务。"], revision=b.revision)
    before = all_tables(s.admin)
    for candidate in (fbody, {**fbody, "content": "我计划部署服务。"}):
        with pytest.raises(
            ConversationError, match="research_old_contract_collision"
        ), s.append_runtime() as db:
            prepare(db, b.sid, b.token, h["Idempotency-Key"], candidate)
    assert all_tables(s.admin) == before
    future_key = key(b)["Idempotency-Key"]
    with s.append_runtime() as db:
        parsed, tag = prepare(db, b.sid, b.token, future_key, fbody)
        assert parsed.digest == digest(future_key) and len(tag) == 64
    with x.model.connect() as db:
        submit(db, x.gate, b, future_key, fbody, issuer=x.issuer)
    formal = all_tables(s.admin)
    reference = x.model.snapshot()
    queries = []
    engine = (s.runtime if first == 1 else s.append_runtime).kw["bind"]

    def capture(conn, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert recover(s, b, h).json() == original
        assert queries and all(
            q.lstrip().split()[0].upper() in ("SELECT", "SHOW") for q in queries
        )
        assert any("transaction_read_only" in q for q in queries)
        assert not any("FOR UPDATE" in q or "pg_advisory" in q for q in queries)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert post(s, b, value, h).json() == original
    assert all_tables(s.admin) == formal and x.model.snapshot() == reference
    # No implicit routing: existing v1/v2 handlers still reject a typed request.
    wrong = deepcopy(value)
    wrong["contract_version"] = 3
    assert post(s, b, wrong, key(b)).status_code == 422
    error(
        (recover2 if first == 1 else recover1)(s, b, h),
        409,
        "conversation_contract_mismatch",
    )
    assert all_tables(s.admin) == formal


@pytest.mark.parametrize("first", [1, 2])
def test_real_same_key_changed_body_and_cross_version_never_reexecute(
    append_service, first
):
    s = append_service
    b = seed(s)
    h = key(b)
    post = post1 if first == 1 else post2
    value = command(b) if first == 1 else body(b)
    assert post(s, b, value, h).status_code == 201
    before = all_tables(s.admin)
    changed = deepcopy(value)
    changed["input"]["content"] += " "
    error(post(s, b, changed, h), 409, "idempotency_payload_mismatch")
    error(
        (post2 if first == 1 else post1)(s, b, h=h),
        409,
        "conversation_contract_mismatch",
    )
    assert all_tables(s.admin) == before


@pytest.mark.parametrize(
    "fault", ["credential", "session", "scope", "version", "choice"]
)
def test_actual_hmac_and_future_request_digest_identity_bindings(append_service, fault):
    s = append_service
    b = seed(s)
    h = key(b)
    candidate = future_body(b.sid, b.pid, ["我部署了服务。"])
    before = all_tables(s.admin)
    if fault == "credential":
        other = seed(s)
        before = all_tables(s.admin)
        with pytest.raises(
            idem.IdempotencyError, match="idempotency_credential_invalid"
        ), s.append_runtime() as db:
            prepare(db, b.sid, other.token, h["Idempotency-Key"], candidate)
    elif fault in {"session", "scope"}:
        other = seed(s)
        before = all_tables(s.admin)
        with pytest.raises(
            idem.IdempotencyError, match="idempotency_credential_invalid"
        ), s.append_runtime() as db:
            prepare(db, other.sid, b.token, h["Idempotency-Key"], candidate)
    elif fault == "version":
        candidate["contract_version"] = True
        with pytest.raises(
            ConversationError, match="research_future_contract_unsupported"
        ), s.append_runtime() as db:
            prepare(db, b.sid, b.token, h["Idempotency-Key"], candidate)
    else:
        with s.append_runtime() as db:
            _, a = prepare(db, b.sid, b.token, h["Idempotency-Key"], candidate)
            candidate["items"][0]["progress_stage"] = "in_progress"
            _, btag = prepare(db, b.sid, b.token, h["Idempotency-Key"], candidate)
            assert a != btag
    assert all_tables(s.admin) == before


@pytest.mark.parametrize("first", [1, 2])
@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_counterexample_future_separate_store_is_invisible_to_old_writer(
    append_service, boundary, first
):
    s = append_service
    x = boundary
    b = seed(s)
    h = key(b)
    attach_reference(x, b)
    fbody = future_body(b.sid, b.pid, ["我部署了服务。"], revision=b.revision)
    with s.append_runtime() as db:
        prepare(db, b.sid, b.token, h["Idempotency-Key"], fbody)
    with x.model.connect() as db:
        submit(db, x.gate, b, h["Idempotency-Key"], fbody, issuer=x.issuer)
    # Genuine failure evidence: formal old writer has no knowledge of this
    # separate research store. No marker, owner rewrite or relaxed assertions.
    response = (post1 if first == 1 else post2)(s, b, h=h)
    assert response.status_code == 201, response.text
    with s.admin() as db:
        rows = db.scalars(
            select(ConversationOperation).where(
                ConversationOperation.key_digest == digest(h["Idempotency-Key"])
            )
        ).all()
        assert len(rows) == 1 and rows[0].contract_version == first
    assert len(x.model.snapshot()["ref_operations"]) == 1
    # Consequently no formal CO1/CO2/CO3 global at-most-once claim is made.


@pytest.mark.parametrize("first", [1, 2])
def test_delete_actual_old_tombstone_no_resurrection(append_service, first):
    s = append_service
    b = seed(s)
    h = key(b)
    post, recover = (post1, recover1) if first == 1 else (post2, recover2)
    assert post(s, b, h=h).status_code == 201
    assert (
        s.client.delete(
            f"/api/v1/experience/sessions/{b.sid}",
            headers={"Authorization": "Bearer " + b.token},
        ).status_code
        == 204
    )
    before = all_tables(s.admin)
    error(recover(s, b, h), 410, "conversation_resource_deleted")
    error(post(s, b, h=h), 410, "conversation_resource_deleted")
    with s.admin() as db:
        row = db.scalar(select(ConversationOperation))
        assert (
            row.state == "deleted"
            and row.contract_version == first
            and row.request_tag is None
        )
    assert all_tables(s.admin) == before


def test_actual_formal_check_rejects_version3_insert_without_any_migration(
    append_service,
):
    s = append_service
    b = seed(s)
    h = key(b)
    assert post2(s, b, h=h).status_code == 201
    before = all_tables(s.admin)
    with pytest.raises(IntegrityError), s.append_runtime.begin() as db:
        db.execute(
            text(
                "INSERT INTO conversation_operations(id,contract_version,key_digest,state) VALUES(:id,3,:key,'applied')"
            ),
            {"id": uuid4(), "key": digest("synthetic-unaccepted-v3")},
        )
    assert all_tables(s.admin) == before


@pytest.mark.parametrize("kind", ["correct", "withdraw", "resolution"])
def test_actual_0013_to_0015_preserves_old_json_hmac_and_recovery(
    append_service, migrated_connection, kind
):
    from test_maintenance_api import ambiguous, resolve, resolution_body

    s = append_service
    conn, cfg = migrated_connection
    alembic.downgrade(cfg, "0013_fact_maintenance")
    conn.commit()
    b = seed(s)
    h = key(b)
    if kind == "resolution":
        parent, _, _ = ambiguous(s, b)
        value = resolution_body(s, b)
        response = resolve(s, b, parent, value, h)
    else:
        value = command(b, action=kind)
        response = post1(s, b, value, h)
    assert response.status_code == 201, response.text
    old = response.json()
    old_get = recover1(s, b, h).json()
    before = all_tables(s.admin)
    assert old_get == old
    alembic.upgrade(cfg, "head")
    conn.commit()
    # New functions receive the same test NOLOGIN owner as the reviewed old
    # runtime policy. This is fixture setup, not an application impersonation.
    with s.admin.begin() as db:
        quote = db.bind.dialect.identifier_preparer.quote_identifier
        for fn in db.scalars(
            text(
                "SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'classification_%'"
            )
        ):
            db.execute(text(f"ALTER FUNCTION {fn} OWNER TO {quote(s.auditor)}"))
    after = all_tables(s.admin)
    for table in (
        "fact_changes",
        "fact_sources",
        "fact_change_sources",
        "conversation_operations",
        "conversation_turns",
    ):
        assert after[table] == before[table]
    assert recover1(s, b, h).json() == old
    replay = (
        resolve(s, b, parent, value, h)
        if kind == "resolution"
        else post1(s, b, value, h)
    )
    assert replay.status_code == 200 and replay.json() == old
    assert all_tables(s.admin) == after
