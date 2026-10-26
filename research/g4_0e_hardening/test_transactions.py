"""Characterize actual PG16 transaction control, including successful attacks.

Expected unsafe outcomes are explicit research evidence, NEVER an admission.
No constraint disabling, clock monkeypatch, owner request or xfail.
"""
from dataclasses import replace
import hashlib
import hmac
import json
import os
from pathlib import Path
import time

import psycopg
from psycopg import sql
import pytest

from research.g3_choice_protocol.runtime import command, apply
from research.g4_trusted_boundary.runtime import seal, permit, message, admit_gate


class ShortIssuer:
    """Trusted synthetic issuer configuration: genuine signed 3-second TTL."""
    def __init__(self, x): self.x = x
    def issue(self, graph):
        p = replace(self.x.issuer.issue(graph), expires=int(time.time()) + 3)
        return replace(p, mac=hmac.digest(self.x.secret, message(p.seal, p.nonce, p.expires, p.validator_hash), 'sha256'))


def wait_for_expiry(db, deadline):
    # A deadline-driven experiment, not a sleep to hide a test race.
    db.execute('SELECT pg_sleep(GREATEST(0,%s-extract(epoch FROM clock_timestamp())+0.08))', (deadline,))


def record(name, evidence):
    target = os.getenv('G4_0E_EVIDENCE_FILE')
    if target:
        path = Path(target); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps({'case': name, **evidence}, sort_keys=True) + '\n')


def experiment(x, case):
    m = x.model; b = m.seed(); before = m.snapshot(); signed = {}; phase = 'connect'
    error = None; before_commit_epoch = None
    db = m.connect()
    try:
        phase = 'admission'; admit_gate(db, x.gate)
        role = db.execute('SELECT session_user AS identity,rolsuper,rolcreaterole,rolcreatedb,rolbypassrls FROM pg_roles WHERE rolname=session_user').fetchone()
        assert role['identity'] == m.roles['writer'] and not any(role[k] for k in ('rolsuper','rolcreaterole','rolcreatedb','rolbypassrls'))
        a, _ = apply(db, b.sid, b.token, 'transaction-A', command(b.sid, b.pid, ['我部署了服务。']))
        oid = a['operation_id']; phase = 'permit-A'
        p = (ShortIssuer(x) if case in ('T1', 'T2') else x.issuer).issue(seal(db, x.gate, oid))
        signed[oid] = hashlib.sha256(p.seal.encode()).hexdigest(); permit(db, x.gate, oid, p)
        if case in ('T2', 'T3'):
            phase = 'early-immediate'; db.execute('SET CONSTRAINTS ALL IMMEDIATE')
            phase = 'back-deferred'; db.execute('SET CONSTRAINTS ALL DEFERRED')
        if case in ('T1', 'T2'):
            phase = 'expiry-wait'; wait_for_expiry(db, p.expires)
        else:
            phase = 'stage-B'
            second, _ = apply(db, b.sid, b.token, 'transaction-B', command(b.sid, b.pid, ['我编写了脚本。'], revision=2))
            other = second['operation_id']; q = x.issuer.issue(seal(db, x.gate, other))
            signed[other] = hashlib.sha256(q.seal.encode()).hexdigest(); permit(db, x.gate, other, q)
        before_commit_epoch = db.execute('SELECT extract(epoch FROM clock_timestamp())::float8 AS epoch').fetchone()['epoch']
        if case in ('T1','T2'): assert before_commit_epoch > p.expires
        phase = 'COMMIT'; db.commit(); committed = True; state = None
    except psycopg.Error as exc:
        state = exc.sqlstate; error = exc.diag.message_primary; committed = False; db.rollback()
    finally:
        db.close()
    after = m.snapshot()
    with m.connect('reader', True) as reader:
        revision = reader.execute('SELECT revision FROM ref_sessions WHERE id=%s', (b.sid,)).fetchone()['revision']
    matches = []; final_hashes = []
    if committed:
        with m.connect() as writer:
            final_hashes = [hashlib.sha256(seal(writer, x.gate, oid).encode()).hexdigest() for oid in signed]
            matches = [actual == expected for actual,expected in zip(final_hashes,signed.values())]
    triggers = m.admin.execute('SELECT tgname,tgdeferrable,tginitdeferred,tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND NOT tgisinternal ORDER BY tgname', (x.gate.schema+'.permits',)).fetchall()
    counts = {k: len(after[k]) - len(before[k]) for k in ('ref_facts','ref_operations','g4_permits')}
    result = dict(committed=committed, sqlstate=state, error=error, phase=phase, session_revision=revision,
        counts=counts, signed_seals_match_final=matches, zero_effect=after == before, role=role, triggers=triggers,
        permit_expires_epoch=p.expires, server_epoch_before_commit=before_commit_epoch,
        expired_before_commit=before_commit_epoch > p.expires,
        signed_hashes=list(signed.values()), final_hashes=final_hashes,
        strict_commit_deadline_guaranteed=False)
    record(case, result)
    return result


@pytest.mark.parametrize('boundary', ['credential'], indirect=True)
@pytest.mark.parametrize('case,commits,revision,counts,matches', [
    ('T1', False, 1, 0, []),
    ('T2', True, 2, 1, [True]),
    ('T3', True, 3, 2, [False, True]),
    ('T4', False, 1, 0, []),
])
def test_actual_transaction_matrix_preserves_unsafe_commit_evidence(boundary, case, commits, revision, counts, matches):
    r = experiment(boundary, case)
    assert r['committed'] is commits
    assert r['session_revision'] == revision
    assert list(r['counts'].values()) == [counts] * 3
    assert r['signed_seals_match_final'] == matches
    assert r['zero_effect'] is (not commits)
    if not commits: assert r['sqlstate'] == '23514' and r['phase'] == 'COMMIT'
    if case in ('T1','T2'): assert r['expired_before_commit'] is True


@pytest.mark.parametrize('boundary', ['credential'], indirect=True)
def test_explicit_transaction_rollback_is_zero_effect(boundary):
    x = boundary; b = x.model.seed(); before = x.model.snapshot()
    with x.model.connect() as db:
        result, _ = apply(db, b.sid, b.token, 'rollback', command(b.sid, b.pid, ['我部署了服务。']))
        permit(db, x.gate, result['operation_id'], x.issuer.issue(seal(db, x.gate, result['operation_id'])))
        db.rollback()
    assert x.model.snapshot() == before
