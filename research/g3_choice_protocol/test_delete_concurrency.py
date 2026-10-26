"""Real connections; deterministic barriers, no fixed sleeps or fake crashes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
import pytest
from research.g3_choice_protocol.runtime import apply, recover, command, Refused
from research.g3_choice_protocol.test_postgres import saved, TEXTS


@pytest.mark.parametrize("scheme", ["A", "B"])
def test_real_append_holds_session_lock_then_authorized_delete_erases_entire_graph(
    model, scheme
):
    m = model
    b = m.seed()
    started = Event()
    pids = []

    def erase():
        with m.connect("eraser") as eraser:
            pids.append(eraser.info.backend_pid)
            started.set()
            eraser.execute("SELECT ref_erase(%s,%s)", (b.sid, b.token))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with m.connect() as writer:
            apply(
                writer,
                b.sid,
                b.token,
                "append-before-delete",
                command(b.sid, b.pid, TEXTS[:3], scheme=scheme),
            )
            pending = pool.submit(erase)
            assert started.wait(timeout=10)
            # Observe the real database lock wait, not just thread startup.
            deadline = monotonic() + 5
            while True:
                row = m.admin.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                    (pids[0],),
                ).fetchone()
                if row and row["wait_event_type"] == "Lock":
                    break
                assert monotonic() < deadline, "eraser never reached the Session lock"
            # DELETE waits for the Session lock until this transaction commits.
        pending.result(timeout=15)
    state = m.snapshot()
    assert len(state["ref_operations"]) == 1
    assert all(not rows for name, rows in state.items() if name != "ref_operations")
    with pytest.raises(Refused, match="deleted"), m.connect("reader", True) as db:
        recover(db, b.sid, b.token, "append-before-delete", scheme=scheme)
    assert m.snapshot() == state


def test_real_recovery_uses_one_snapshot_during_delete_then_new_snapshot_sees_tombstone(
    model,
):
    m = model
    b = m.seed()
    saved(m, b, n=3)
    with m.connect("reader", True) as reader:
        prior = recover(reader, b.sid, b.token, "synthetic-key")
        with m.connect("eraser") as eraser:
            eraser.execute("SELECT ref_erase(%s,%s)", (b.sid, b.token))
        after_delete = m.snapshot()
        # Consistent old snapshot, not a partial graph assembled across commits.
        assert recover(reader, b.sid, b.token, "synthetic-key") == prior
        assert m.snapshot() == after_delete
    with pytest.raises(Refused, match="deleted"), m.connect("reader", True) as reader:
        recover(reader, b.sid, b.token, "synthetic-key")
    assert m.snapshot() == after_delete


def test_real_different_key_does_not_recreate_exact_original_source(model):
    m = model
    b = m.seed()
    saved(m, b)
    before = m.snapshot()
    with pytest.raises(Refused, match="exact_source_reuse"), m.connect() as db:
        apply(
            db, b.sid, b.token, "new-key", command(b.sid, b.pid, TEXTS[:1], revision=2)
        )
    assert m.snapshot() == before


def test_real_post_replay_never_returns_partial_graph_during_authorized_delete(model):
    m = model
    b = m.seed()
    body, prior = saved(m, b, n=3)
    paused, release, erase_started = Event(), Event(), Event()
    pids = []

    class PauseBeforeValidation:
        def __init__(self, db):
            self.db = db

        def execute(self, query, *args, **kwargs):
            if query == "SELECT ref_validate(%s)":
                paused.set()
                assert release.wait(timeout=10)
            return self.db.execute(query, *args, **kwargs)

    def replay():
        with m.connect() as db:
            return apply(
                PauseBeforeValidation(db), b.sid, b.token, "synthetic-key", body
            )

    def erase():
        with m.connect("eraser") as db:
            pids.append(db.info.backend_pid)
            erase_started.set()
            db.execute("SELECT ref_erase(%s,%s)", (b.sid, b.token))

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pool.submit(replay)
        try:
            assert paused.wait(timeout=10)
            deletion = pool.submit(erase)
            assert erase_started.wait(timeout=10)
            # Before the fix deletion COMMITs between the cached receipt and
            # graph queries. With a receipt row lock it observably waits.
            deadline = monotonic() + 5
            while not deletion.done():
                row = m.admin.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                    (pids[0],),
                ).fetchone()
                if row and row["wait_event_type"] == "Lock":
                    break
                assert monotonic() < deadline
        finally:
            release.set()
        replayed, tag = result.result(timeout=10)
        deletion.result(timeout=10)
    assert tag == "replayed" and replayed == prior
    state = m.snapshot()
    assert all(not rows for name, rows in state.items() if name != "ref_operations")
