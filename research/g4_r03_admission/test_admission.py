"""Additional actual-entry observations; existing permissive behavior stays."""

from copy import deepcopy
import json
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, text
from app import facts
from app.models import ExperienceFact, ExperienceSession, FactChange
from test_maintenance_api import seed, key, command, post, current
from test_append_api import legacy_rejected_history
from test_cutoff_preflight import ROOT, auth
from test_typed_source_preflight import saved, request as source_request
from test_legacy_upgrade_handoff import digest
from research.g4_r03_admission.packet import review, CONTRACT

CASES = [
    ("digits", "我测试了3个导出按钮。", "我测试了三个导出按钮。", 422),
    ("synonym", "我测试了3个导出按钮。", "我验证了3个导出按钮。", 201),
    ("quantity", "我测试了3个导出按钮。", "我测试了4个导出按钮。", 201),
    ("team", "我们测试了3个导出按钮。", "我测试了3个导出按钮。", 201),
    ("negation", "我没有测试3个导出按钮。", "我测试了3个导出按钮。", 201),
    ("plan", "我计划测试3个导出按钮。", "我测试了3个导出按钮。", 201),
]


def restored_numeric_fixture(s, b, status):
    """Legal preexisting legacy restoration, arranged outside reader request.

    As in the reviewed old fixture, this is NOT a supported current API action.
    Append real snapshots instead of rewriting any existing history JSON.
    """
    with s.admin.begin() as db:
        f = db.get(ExperienceFact, b.fid)
        before = facts.snapshot(db, f)
        f.status = "rejected"
        db.flush()
        db.add(
            FactChange(
                fact_id=f.id,
                session_id=b.sid,
                action="status_changed",
                actor="user",
                before=before,
                after=facts.snapshot(db, f),
            )
        )
        db.flush()
        before = facts.snapshot(db, f)
        f.statement = "我测试了2个导出按钮。"
        f.status = "pending"
        db.flush()
        change = FactChange(
            id=uuid4(),
            fact_id=f.id,
            session_id=b.sid,
            action="edited",
            actor="user",
            before=before,
        )
        change.after = facts.snapshot(db, f, edit=change)
        db.add(change)
        db.flush()
        if status == "confirmed":
            facts.change_fact(
                db, f.id, b.token, status="user_confirmed", expected_version=f.version
            )


@pytest.mark.parametrize("entry", ["manual_edit", "co1_correct"])
@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0])
def test_real_existing_edit_and_maintenance_r03_differences(preflight, entry, case):
    _, old, new, co_status = case
    s = preflight
    b = seed(s, status="rejected", statement=old)
    target = new.replace("3", "2").replace("4", "2").replace("三个", "2个")
    with s.legacy.begin() as db:
        turn = facts.add_turn(db, b.sid, b.token, target)
        fact = facts.add_fact(db, b.pid, b.token, target, [turn.id])
        fid = fact.id
    original = b.fid
    b.fid = fid
    current(s, b)
    before = digest(s.admin)
    if entry == "manual_edit":
        response = s.client.patch(
            ROOT + f"/facts/{fid}",
            headers=auth(b),
            json=dict(action="edit", expected_version=b.version, statement=new),
        )
        expected = 200
    else:
        response = post(s, b, command(b, replacement=new), key(b))
        expected = co_status
    assert response.status_code == expected, response.text
    if expected == 422:
        assert digest(s.admin) == before
    with s.admin() as db:
        assert db.get(ExperienceFact, original).status == "rejected"
        assert db.get(ExperienceFact, fid).statement == (
            target if expected == 422 else new
        )
        assert db.scalar(text("SELECT count(*) FROM paid_calls")) == 0
    assert s.provider.calls == 0


@pytest.mark.parametrize("history", ["current", "pending", "confirmed"])
@pytest.mark.parametrize(
    "new", ["我测试了三个导出按钮。", "我验证了3个导出按钮。", "我部署了服务。"]
)
def test_real_readonly_review_packet_retains_rejection_and_unrelated_argument(
    reader, history, new
):
    s = reader
    b = seed(s, status="rejected" if history == "current" else "pending")
    if history != "current":
        restored_numeric_fixture(s, b, history)
    tid = saved(s, b, new)
    items = source_request(b, new)["items"]
    req = dict(contract=CONTRACT, revision=b.revision, items=items)
    before = digest(s.admin)
    result = review(s.reader, sid=b.sid, pid=b.pid, tid=tid, token=b.token, request=req)
    assert result["status"] == "requires_review" and result["conflicts"]
    conflict = result["conflicts"][0]
    assert (
        conflict["history"]
        and conflict["original_sources"]
        and conflict["rejected_snapshots"]
    )
    assert conflict["reason"] == (
        "distinct_literal_source_argument_only"
        if new == "我部署了服务。"
        else "known_reassertion_risk"
    )
    assert (
        result["semantic_independence"] == "NOT_PROVEN"
        and not result["truth_verified"]
        and not result["persistence_authorized"]
    )
    assert digest(s.admin) == before and b.token not in json.dumps(result, default=str)
    # Changed source identifier, new Turn, new key or a checkbox cannot make
    # this review packet a signed permit or enable any successful transition.
    for bad in (
        {**req, "force": True},
        {**req, "revision": b.revision + 1},
        {**req, "contract": "unknown"},
    ):
        denied = review(
            s.reader, sid=b.sid, pid=b.pid, tid=tid, token=b.token, request=bad
        )
        assert denied["status"] == "unavailable" and "conflicts" not in denied
    foreign = review(
        s.reader, sid=b.sid, pid=b.pid, tid=tid, token="foreign", request=req
    )
    assert foreign["code"] == "session_unavailable" and "conflicts" not in foreign
    assert digest(s.admin) == before


def test_review_packet_preserves_actual_fcs_and_all_before_after(reader):
    s = reader
    b = seed(s)
    response = post(s, b, command(b, action="withdraw"))
    assert response.status_code == 201, response.text
    tid = saved(s, b, "我部署了服务。")
    req = dict(
        contract=CONTRACT,
        revision=b.revision,
        items=source_request(b, "我部署了服务。")["items"],
    )
    before = digest(s.admin)
    result = review(s.reader, sid=b.sid, pid=b.pid, tid=tid, token=b.token, request=req)
    assert result["status"] == "requires_review"
    fcs = result["conflicts"][0]["change_sources"]
    assert (
        len(fcs) == 1
        and fcs[0]["source_role"] == "intent"
        and fcs[0]["quote"] == "撤回上一条。"
    )
    assert digest(s.admin) == before


@pytest.mark.parametrize("fault", ["permission", "history"])
def test_incomplete_history_or_missing_select_returns_no_partial_packet(reader, fault):
    from test_experience_read import corrupt

    s = reader
    b = seed(s, status="rejected")
    tid = saved(s, b, "我部署了服务。")
    req = dict(
        contract=CONTRACT,
        revision=b.revision,
        items=source_request(b, "我部署了服务。")["items"],
    )
    if fault == "permission":
        with s.admin.begin() as db:
            db.execute(
                text(f'REVOKE SELECT ON fact_change_sources FROM "{s.read_role}"')
            )
    else:
        corrupt(
            s,
            "fact_changes",
            "UPDATE fact_changes SET after=after-'status' WHERE fact_id=:fid",
            {"fid": b.fid},
        )
    before = digest(s.admin)
    result = review(s.reader, sid=b.sid, pid=b.pid, tid=tid, token=b.token, request=req)
    assert (
        result["status"] == "unavailable"
        and "original" not in result
        and "conflicts" not in result
    )
    assert digest(s.admin) == before
