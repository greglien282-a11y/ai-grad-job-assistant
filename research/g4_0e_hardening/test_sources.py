"""Defensive source contract regressions using synthetic, restricted PG only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy, copy
from dataclasses import replace
from pathlib import Path
import shutil
from threading import Barrier
from uuid import uuid4
import pytest

from research.g3_choice_protocol.runtime import command, Refused
from research.g4_source_binding.binding import stage, approved_hash
from research.g4_0e_hardening.execution_pin import ExecutionPin, inventory, FILES
import research.g4_trusted_boundary.runtime as trusted

pytestmark = pytest.mark.parametrize('boundary', ['credential'], indirect=True)


@pytest.mark.parametrize('mutation', ['selection_id', 'start', 'end', 'quote', 'entire_batch', 'project', 'session', 'bearer', 'subject'])
def test_exact_source_fields_and_cross_identity_are_zero_effect(bound, mutation):
    z = bound; x = z.x; m = x.model; b = m.seed(); other = m.seed()
    body = command(b.sid, b.pid, ['我部署了服务。', '我编写了脚本。', '我测试了导出按钮。'])
    with m.connect('reader', True) as db: origin = z.ingress.capture(db, x.gate, b, 'fields', body)
    requested = deepcopy(body); identity = b
    if mutation == 'selection_id': requested['items'][0]['selection_id'] = str(uuid4())
    if mutation == 'start': requested['items'][0]['start'] += 1
    if mutation == 'end': requested['items'][0]['end'] -= 1
    if mutation == 'quote': requested['items'][0]['quote'] = '我部署了推荐服务。'
    if mutation == 'entire_batch':
        requested = command(b.sid, b.pid, ['我制作了结果图。', '我整理了27条缺失记录。', '我验证了导出按钮。'])
    if mutation == 'project': requested['project_id'] = str(other.pid)
    if mutation == 'session': identity = other; requested.update(session_id=str(other.sid), project_id=str(other.pid))
    if mutation == 'bearer': identity = copy(b); identity.token = other.token
    if mutation == 'subject': origin = replace(origin, subject=str(other.subject))
    before = m.snapshot()
    with pytest.raises(Refused), m.connect() as db: stage(db, x.gate, identity, 'fields', requested, origin, z.issuer)
    assert m.snapshot() == before


@pytest.mark.parametrize('original,changed', [('我制作了é原型图。', '我制作了é原型图。'), ('我制作了👩‍💻原型图。', '我制作了🧪原型图。')])
def test_unicode_forms_remain_exact_without_normalization_or_utf16_offsets(bound, original, changed):
    z = bound; x = z.x; m = x.model; b = m.seed()
    body = command(b.sid, b.pid, [original])
    with m.connect('reader', True) as db: source = z.ingress.capture(db, x.gate, b, 'unicode', body)
    bad = deepcopy(body); bad['content'] = changed; bad['items'][0].update(quote=changed, end=len(changed))
    before = m.snapshot()
    with pytest.raises(Refused, match='authenticated_source_mismatch'), m.connect() as db: stage(db, x.gate, b, 'unicode', bad, source, z.issuer)
    assert m.snapshot() == before
    with m.connect() as db: stage(db, x.gate, b, 'unicode', body, source, z.issuer)
    assert len(m.snapshot()['ref_facts']) == 1


def test_same_source_and_key_replay_is_not_second_effect_and_new_key_refuses(bound):
    z = bound; x = z.x; m = x.model; b = m.seed(); body = command(b.sid, b.pid, ['我部署了服务。'])
    with m.connect('reader', True) as db: source = z.ingress.capture(db, x.gate, b, 'repeat', body)
    with m.connect() as db: stage(db, x.gate, b, 'repeat', body, source, z.issuer)
    before = m.snapshot()
    with m.connect() as db: _, status = stage(db, x.gate, b, 'repeat', body, source, None)
    assert status == 'replayed' and m.snapshot() == before
    changed = command(b.sid, b.pid, ['我编写了脚本。'], revision=2)
    with pytest.raises(Refused, match='authenticated_source_mismatch'), m.connect() as db: stage(db, x.gate, b, 'new-key', changed, source, z.issuer)
    assert m.snapshot() == before


def test_source_snapshot_revision_race_uses_two_real_connections_and_refuses_stale_write(bound):
    z = bound; x = z.x; m = x.model; b = m.seed()
    old = command(b.sid, b.pid, ['我部署了服务。']); current = command(b.sid, b.pid, ['我编写了脚本。'])
    with m.connect('reader', True) as snapshot:
        assert snapshot.execute('SELECT revision FROM ref_sessions WHERE id=%s', (b.sid,)).fetchone()['revision'] == 1
        with m.connect('reader', True) as reader: fresh = z.ingress.capture(reader, x.gate, b, 'current', current)
        with m.connect() as writer: stage(writer, x.gate, b, 'current', current, fresh, z.issuer)
        stale = z.ingress.capture(snapshot, x.gate, b, 'stale', old)
    before = m.snapshot()
    with pytest.raises(Refused, match='context_conflict'), m.connect() as db: stage(db, x.gate, b, 'stale', old, stale, z.issuer)
    assert m.snapshot() == before


def test_concurrent_same_source_same_key_commits_one_graph(bound):
    z = bound; x = z.x; m = x.model; b = m.seed(); body = command(b.sid, b.pid, ['我部署了服务。'])
    with m.connect('reader', True) as db: source = z.ingress.capture(db, x.gate, b, 'parallel', body)
    barrier = Barrier(2)
    def request():
        with m.connect() as db:
            barrier.wait(timeout=10)
            return stage(db, x.gate, b, 'parallel', body, source, z.issuer)[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request(), range(2)))
    assert sorted(results) == ['replayed','staged']
    assert len(m.snapshot()['ref_facts']) == len(m.snapshot()['g4_permits']) == 1


def test_file_inventory_covers_execution_dependency_omitted_by_old_hash(bound, tmp_path):
    from research.g4_0e_hardening.execution_pin import ROOT
    pin = ExecutionPin(inventory()); unchanged = approved_hash()
    for relative in FILES:
        destination = tmp_path/relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/relative, destination)
    changed = tmp_path/'research/g4_trusted_boundary/runtime.py'
    changed.write_bytes(changed.read_bytes() + b'\n# synthetic dependency change\n')
    with pytest.raises(Refused, match='execution_chain_unapproved'): pin.verify(tmp_path)
    assert approved_hash() == unchanged
    pin.verify()


def test_loaded_dependency_substitution_refuses_before_writes_even_when_file_hash_is_same(bound, monkeypatch):
    pin = ExecutionPin(inventory()); before = bound.x.model.snapshot(); unchanged = approved_hash()
    def unavailable(self, graph): raise Refused('synthetic_unavailable_dependency')
    monkeypatch.setattr(trusted.Issuer, 'issue', unavailable)
    assert approved_hash() == unchanged
    with pytest.raises(Refused, match='execution_chain_unapproved'): pin.verify()
    assert bound.x.model.snapshot() == before
