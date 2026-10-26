import hashlib
import psycopg
import pytest
from research.g3_choice_protocol.runtime import command, apply
from research.g4_trusted_boundary.runtime import seal, permit, admit_gate
from research.g4_0e_hardening.guard import install, verify
from research.g4_0e_hardening.test_transactions import ShortIssuer, wait_for_expiry, record


@pytest.mark.parametrize('boundary', ['credential'], indirect=True)
def test_synchronous_guard_blocks_early_check_then_second_operation_even_different_session(boundary):
    x = boundary; install(x); m = x.model; b = m.seed(); other = m.seed(); before = m.snapshot()
    for target, revision in [(b, 2), (other, 1)]:
        with pytest.raises(psycopg.errors.UniqueViolation) as caught, m.connect() as db:
            verify(db, x); admit_gate(db, x.gate)
            a, _ = apply(db, b.sid, b.token, 'A', command(b.sid, b.pid, ['我部署了服务。']))
            permit(db, x.gate, a['operation_id'], x.issuer.issue(seal(db, x.gate, a['operation_id'])))
            db.execute('SET CONSTRAINTS ALL IMMEDIATE'); db.execute('SET CONSTRAINTS ALL DEFERRED')
            apply(db, target.sid, target.token, 'B', command(target.sid, target.pid, ['我编写了脚本。'], revision=revision))
        assert caught.value.sqlstate == '23505' and m.snapshot() == before


@pytest.mark.parametrize('boundary', ['credential'], indirect=True)
def test_existing_revision_guard_still_blocks_unpaired_update_after_early_check(boundary):
    x = boundary; install(x); m = x.model; b = m.seed(); before = m.snapshot()
    with pytest.raises(psycopg.errors.CheckViolation, match='ref_revision_without_operation'), m.connect() as db:
        verify(db, x); admit_gate(db, x.gate)
        a, _ = apply(db, b.sid, b.token, 'A', command(b.sid, b.pid, ['我部署了服务。']))
        permit(db, x.gate, a['operation_id'], x.issuer.issue(seal(db, x.gate, a['operation_id'])))
        db.execute('SET CONSTRAINTS ALL IMMEDIATE'); db.execute('SET CONSTRAINTS ALL DEFERRED')
        db.execute('UPDATE ref_sessions SET revision=revision+1 WHERE id=%s', (b.sid,))
    assert m.snapshot() == before


@pytest.mark.parametrize('boundary', ['credential'], indirect=True)
def test_guarded_single_operation_commits_but_does_not_claim_strict_deadline(boundary):
    x = boundary; install(x); m = x.model; b = m.seed()
    with m.connect() as db:
        verify(db, x); admit_gate(db, x.gate)
        a, _ = apply(db, b.sid, b.token, 'single', command(b.sid, b.pid, ['我部署了服务。']))
        p = ShortIssuer(x).issue(seal(db, x.gate, a['operation_id']))
        permit(db, x.gate, a['operation_id'], p)
        db.execute('SET CONSTRAINTS ALL IMMEDIATE'); db.execute('SET CONSTRAINTS ALL DEFERRED')
        wait_for_expiry(db, p.expires)
    # Important retained BLOCK: synchronous graph guard cannot create a COMMIT hook.
    assert len(m.snapshot()['ref_facts']) == 1
    with m.connect() as db:
        assert hashlib.sha256(seal(db, x.gate, a['operation_id']).encode()).hexdigest() == hashlib.sha256(p.seal.encode()).hexdigest()
    record('guarded-T2-still-BLOCK', {'committed': True, 'strict_commit_deadline_guaranteed': False})
