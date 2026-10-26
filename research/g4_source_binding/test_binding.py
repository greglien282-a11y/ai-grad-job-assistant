from copy import deepcopy
from dataclasses import replace
import hmac
import time
from uuid import uuid4
import psycopg
import pytest
from research.g3_choice_protocol.runtime import command, apply, Refused
from research.g4_trusted_boundary.runtime import (
    submit,
    seal,
    permit,
    read,
    Issuer,
    validator_hash,
)
from research.g3_choice_protocol.test_direct_sql import direct_stage
from research.g4_source_binding.binding import stage, origin_message


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_original_boundary_counterexample_writer_rewrites_entire_received_turn(
    boundary,
):
    x = boundary
    m = x.model
    b = m.seed()
    received = command(b.sid, b.pid, ["我计划部署服务。"], kind="plan", stage="planned")
    rewritten = deepcopy(received)
    rewritten["content"] = "我部署了服务。"
    rewritten["items"][0].update(
        quote=rewritten["content"],
        end=len(rewritten["content"]),
        fact_kind="personal_action",
        progress_stage="completed",
    )
    # NO key theft, owner edits or changed validator: independent signer sees
    # self-consistent but fabricated source. This is a genuine original gap.
    with m.connect() as db:
        submit(db, x.gate, b, "rewritten", rewritten, issuer=x.issuer)
    assert (
        received["content"] == "我计划部署服务。"
        and len(m.snapshot()["ref_facts"]) == 1
    )


@pytest.mark.parametrize("n", [1, 3, 5])
@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_bound_original_commits_and_get_only_recovers(bound, n):
    z = bound
    x = z.x
    m = x.model
    b = m.seed()
    texts = [
        "我部署了服务。",
        "我编写了脚本。",
        "我测试了导出按钮。",
        "我制作了结果图。",
        "我整理了27条缺失记录。",
    ]
    body = command(b.sid, b.pid, texts[:n])
    before = m.snapshot()
    with m.connect("reader", True) as db:
        origin = z.ingress.capture(db, x.gate, b, "bound", body)
    assert m.snapshot() == before
    with m.connect() as db:
        stage(db, x.gate, b, "bound", body, origin, z.issuer)
    saved = m.snapshot()
    with m.connect("reader", True) as db:
        result = read(db, x.gate, b, "bound")
    assert len(result["effects"]) == n and m.snapshot() == saved
    # Successful old result remains replayable without a fresh source service.
    with m.connect() as db:
        _, status = stage(db, x.gate, b, "bound", body, None, None)
    assert status == "replayed" and m.snapshot() == saved


@pytest.mark.parametrize(
    "change",
    ["raw", "classification", "key", "nonce", "expired", "unknown_version", "missing"],
)
@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_writer_cannot_rebind_authenticated_ingress(bound, change):
    z = bound
    x = z.x
    m = x.model
    b = m.seed()
    body = command(b.sid, b.pid, ["我部署了服务。"])
    with m.connect("reader", True) as db:
        origin = z.ingress.capture(db, x.gate, b, "source", body)
    request = deepcopy(body)
    key = "source"
    if change == "raw":
        request["content"] = "我编写了脚本。"
        request["items"][0].update(
            quote=request["content"], end=len(request["content"])
        )
    if change == "classification":
        # An otherwise valid new claim still isn't the captured request.
        request["content"] = "我正在部署服务。"
        request["items"][0].update(
            quote=request["content"],
            end=len(request["content"]),
            progress_stage="in_progress",
        )
    if change == "key":
        key = "different"
    if change == "nonce":
        origin = replace(origin, nonce=str(uuid4()))
    if change == "expired":
        origin = replace(origin, expires=int(time.time()) - 10)
        origin = replace(
            origin, mac=hmac.digest(z.ingress_key, origin_message(origin), "sha256")
        )
    if change == "unknown_version":
        origin = replace(origin, contract="unknown")
    if change == "missing":
        origin = None
    before = m.snapshot()
    with pytest.raises(Refused, match="authenticated_source"), m.connect() as db:
        stage(db, x.gate, b, key, request, origin, z.issuer)
    assert m.snapshot() == before


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_received_plan_fabricated_completed_rejected_without_key_theft(bound):
    z = bound
    x = z.x
    m = x.model
    b = m.seed()
    original = command(b.sid, b.pid, ["我计划部署服务。"], kind="plan", stage="planned")
    with m.connect("reader", True) as db:
        origin = z.ingress.capture(db, x.gate, b, "anchor", original)
    fake = deepcopy(original)
    fake["content"] = "我部署了服务。"
    fake["items"][0].update(
        quote=fake["content"],
        end=len(fake["content"]),
        fact_kind="personal_action",
        progress_stage="completed",
    )
    before = m.snapshot()
    with pytest.raises(
        Refused, match="authenticated_source_mismatch"
    ), m.connect() as db:
        stage(db, x.gate, b, "anchor", fake, origin, z.issuer)
    assert m.snapshot() == before
    with m.connect() as db:
        stage(db, x.gate, b, "anchor", original, origin, z.issuer)
    assert len(m.snapshot()["ref_facts"]) == 1


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_direct_sql_lie_still_fails_language_and_old_issuer_cannot_downgrade(
    bound, monkeypatch
):
    z = bound
    x = z.x
    m = x.model
    b = m.seed()
    body = command(b.sid, b.pid, ["我计划部署服务。"])
    with m.connect("reader", True) as db:
        origin = z.ingress.capture(db, x.gate, b, "direct-sql", body)
    before = m.snapshot()
    # Preserve the ORIGINAL selection IDs in this direct-SQL fixture. No
    # validator is patched; otherwise the helper mints a different request and
    # is correctly rejected by source binding before the semantic check.
    monkeypatch.setattr(
        "research.g3_choice_protocol.test_direct_sql.command",
        lambda *args, **kwargs: deepcopy(body),
    )
    with pytest.raises(
        Refused, match="independent_language_refused"
    ), m.connect() as db:
        oid = direct_stage(db, b, "我计划部署服务。")
        permit(db, x.gate, oid, z.issuer.issue(seal(db, x.gate, oid), origin))
    with pytest.raises(psycopg.errors.CheckViolation), m.connect() as db:
        result, _ = apply(
            db, b.sid, b.token, "old", command(b.sid, b.pid, ["我部署了服务。"])
        )
        oid = result["operation_id"]
        permit(
            db,
            x.gate,
            oid,
            Issuer(x.secret, validator_hash()).issue(seal(db, x.gate, oid)),
        )
    assert m.snapshot() == before


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_source_authorization_and_cross_session_binding(bound):
    from copy import copy

    z = bound
    x = z.x
    m = x.model
    b = m.seed()
    other = m.seed()
    body = command(b.sid, b.pid, ["我部署了服务。"])
    foreign = copy(b)
    foreign.token = other.token
    before = m.snapshot()
    with pytest.raises(Refused, match="resource_unavailable"), m.connect(
        "reader", True
    ) as db:
        z.ingress.capture(db, x.gate, foreign, "auth", body)
    with m.connect("reader", True) as db:
        origin = z.ingress.capture(db, x.gate, b, "auth", body)
    moved = deepcopy(body)
    moved.update(session_id=str(other.sid), project_id=str(other.pid))
    with pytest.raises(
        Refused, match="authenticated_source_mismatch"
    ), m.connect() as db:
        stage(db, x.gate, other, "auth", moved, origin, z.issuer)
    assert m.snapshot() == before
