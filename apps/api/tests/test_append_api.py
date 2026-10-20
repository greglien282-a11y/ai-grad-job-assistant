"""A/V/R/L/U matrix: real independent LOGIN, synthetic random schemas only."""
import copy
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import facts, fact_append
from app.append_api import get_append_factory
from app.append_contract import AppendCommand, append_spans
from app.fact_maintenance_models import ConversationOperation, FactChangeSource
from app.main import app
from app.maintenance_errors import ConversationError
from app.mining_validation import atomic
from app.models import ConversationTurn, ExperienceFact, ExperienceSession, FactChange, FactSource
from test_maintenance_api import (service, seed, key, command, post as v1post,
    recovery as v1recovery, current, error, READS, worker_url, ambiguous, resolve, resolution_body)
from test_fact_source_maintenance import stored
from test_http_api import api
from test_deepseek_mining_integration import offline_guard, test_database_only


@pytest.fixture
def append_service(service):
    s = service
    role = 'b2c_run_' + uuid4().hex
    password = secrets.token_urlsafe(32)
    engine = None
    with s.admin.begin() as db:
        quote = db.bind.dialect.identifier_preparer.quote_identifier
        q, r = quote(s.schema), quote(role)
        db.execute(text(f"CREATE ROLE {r} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"))
        db.execute(text(f'GRANT USAGE ON SCHEMA {q} TO {r}'))
        for table in READS:
            db.execute(text(f'GRANT SELECT ON {q}.{table} TO {r}'))
        for table in ('conversation_turns', 'experience_facts', 'fact_sources', 'fact_changes',
                      'conversation_operations', 'fact_change_sources'):
            db.execute(text(f'GRANT INSERT ON {q}.{table} TO {r}'))
        db.execute(text(f'GRANT UPDATE(updated_at,context_revision) ON {q}.experience_sessions TO {r}'))
    try:
        url = s.admin.kw['bind'].url.set(username=role, password=password)
        engine = create_engine(url, hide_parameters=True, poolclass=NullPool,
                               connect_args={'options': '-csearch_path=' + s.schema})
        s.append_runtime = sessionmaker(engine, expire_on_commit=False)
        s.append_role = role
        app.dependency_overrides[get_append_factory] = lambda: s.append_runtime
        yield s
    finally:
        app.dependency_overrides.pop(get_append_factory, None)
        if engine:
            engine.dispose()
        with s.admin.begin() as db:
            db.execute(text(f'DROP OWNED BY {r} RESTRICT'))
            db.execute(text(f'DROP ROLE {r}'))


SENTENCES = ['我编写了清洗脚本。', '我测试了导出按钮。', '我制作了结果图。', '我整理了27条缺失记录。', '我部署了服务。']


def body(b, sentences=None, **overrides):
    sentences = SENTENCES[:3] if sentences is None else sentences
    content = ''.join(sentences)
    spans, cursor = [], 0
    for sentence in sentences:
        spans.append(dict(start=cursor, end=cursor + len(sentence), quote=sentence))
        cursor += len(sentence)
    result = dict(contract_version=2, base_revision=b.revision, action='append',
                  input={'content': content}, statements=spans)
    result.update(overrides)
    return result


def path(b):
    return f'/api/v1/experience/sessions/{b.sid}/conversation-appends'


def post(s, b, value=None, h=None):
    return s.client.post(path(b), headers=h or key(b), json=value if value is not None else body(b))


def recover(s, b, h):
    return s.client.get(path(b) + '/recovery', headers=h)


@pytest.mark.parametrize('n', [1, 3, 5])
def test_A01_bijection_and_get_only_recovery(append_service, n):
    s = append_service; b = seed(s); h = key(b); value = body(b, SENTENCES[:n])
    before = stored(s.admin)
    response = post(s, b, value, h)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['contract_version'] == 2 and result['effect_count'] == n
    assert [e['effect_slot'] for e in result['effects']] == list(range(1, n + 1))
    assert result['provider_calls'] == 0 and result['mining_run_id'] is None
    after = stored(s.admin)
    for table, delta in [('conversation_turns', 1), ('experience_facts', n), ('fact_changes', n),
                         ('fact_sources', n), ('fact_change_sources', n), ('conversation_operations', 1)]:
        assert len(after[table]) - len(before[table]) == delta
    with s.admin() as db:
        for i, effect in enumerate(result['effects']):
            f = db.get(ExperienceFact, UUID(effect['fact_id']))
            c = db.get(FactChange, UUID(effect['change_id']))
            fs = db.scalar(select(FactSource).where(FactSource.fact_id == f.id))
            assert f.statement == c.after['statement'] == fs.citations[0]['quote'] == SENTENCES[i]
            assert (f.status, f.version, f.evidence_id, f.origin, f.ai_run_id) == ('pending', 1, None, 'manual', None)
        assert db.scalar(text('SELECT count(*) FROM ai_mining_runs')) == 0
        assert db.scalar(text('SELECT count(*) FROM paid_calls')) == 0
    assert recover(s, b, h).json() == result
    assert s.client.get(path(b) + '/' + result['operation_id'], headers=h).json() == result
    replay = post(s, b, value, h)
    assert replay.status_code == 200 and replay.headers['Idempotency-Replayed'] == 'true'
    assert replay.json() == result and stored(s.admin) == after


@pytest.mark.parametrize('bad', ['zero', 'six', 'missing', 'extra', 'bool', 'float', 'long', 'content_long',
    'quote', 'overlap', 'reverse', 'duplicate', 'team', 'negation', 'hypothesis', 'plan', 'composite', 'hidden',
    'utf16', 'typed', 'related_plan', 'unknown_version'])
def test_A02_A04_L01_invalid_batch_zero_write(append_service, bad):
    s = append_service; b = seed(s); value = body(b)
    if bad == 'zero': value['statements'] = []
    elif bad == 'six': value = body(b, SENTENCES + ['我搭建了原型。'])
    elif bad == 'missing': del value['input']
    elif bad == 'extra': value['force'] = True
    elif bad in ('bool', 'float'): value['statements'][0]['start'] = True if bad == 'bool' else 0.0
    elif bad == 'long': value = body(b, ['我制作了' + '图' * 500 + '。'])
    elif bad == 'content_long': value['input']['content'] = '我' * 10001
    elif bad == 'quote': value['statements'][0]['quote'] = '我编写了新脚本。'
    elif bad == 'overlap': value['statements'][1]['start'] = 1
    elif bad == 'reverse': value['statements'].reverse()
    elif bad == 'duplicate': value = body(b, [SENTENCES[0]] * 2)
    elif bad == 'hidden': value['input']['content'] += '这是假设。'
    elif bad == 'utf16': value = body(b, ['我制作了🧪原型图。']); value['statements'][0]['end'] += 1
    elif bad == 'typed': value['statements'][0]['fact_kind'] = 'personal_action'
    elif bad == 'related_plan': value['related_plan'] = str(b.fid)
    elif bad == 'unknown_version': value['contract_version'] = 3
    else:
        value = body(b, [SENTENCES[0], {'team': '我们整理了27条缺失记录。', 'negation': '我没有整理过27条缺失记录。',
            'hypothesis': '如果我整理了27条缺失记录。', 'plan': '我计划整理27条缺失记录。',
            'composite': '我整理并测试了27条记录。'}[bad]])
    before = stored(s.admin)
    response = post(s, b, value)
    assert response.status_code == 422, response.text
    assert stored(s.admin) == before


@pytest.mark.parametrize('content', ['我整理了27条缺失记录。', '我制作了🧪原型图。',
    '我制作了e\u0301图。', '我制作了👩\u200d💻图。'])
def test_L01_U01_unicode_exact_and_global_atomic_frozen(append_service, content):
    s = append_service; b = seed(s)
    if content == '我整理了27条缺失记录。': assert not atomic(content)
    value = body(b, [content])
    value['input']['content'] = '\r\n ' + content + ' \r\n'
    value['statements'][0].update(start=3, end=3 + len(content))
    response = post(s, b, value)
    assert response.status_code == 201, response.text
    with s.admin() as db:
        t = db.get(ConversationTurn, UUID(response.json()['input_turn_id']))
        assert t.content == value['input']['content']


@pytest.mark.parametrize('change', ['nth', 'order', 'revision', 'span'])
def test_A07_V06_payload_conflict(append_service, change):
    s = append_service; b = seed(s); h = key(b); value = body(b)
    assert post(s, b, value, h).status_code == 201
    changed = copy.deepcopy(value)
    if change == 'nth': changed['statements'][-1]['quote'] = '我制作了表格。'
    elif change == 'order': changed['statements'].reverse()
    elif change == 'revision': changed['base_revision'] += 1
    else: changed['statements'][-1]['end'] -= 1
    before = stored(s.admin)
    error(post(s, b, changed, h), 409, 'idempotency_payload_mismatch')
    assert stored(s.admin) == before


@pytest.mark.parametrize('first', ['append', 'correct', 'withdraw'])
def test_V01_V03_both_get_routes_and_cross_route_post(append_service, first):
    s = append_service; b = seed(s); h = key(b)
    result = (post(s, b, h=h) if first == 'append' else v1post(s, b, command(b, action=first), h)).json()
    before = stored(s.admin)
    if first == 'append':
        responses = [v1recovery(s, b, h), s.client.get(path(b).replace('conversation-appends', 'conversation-operations')
            + '/' + result['operation_id'], headers=h), v1post(s, b, command(b), h)]
    else:
        responses = [recover(s, b, h), s.client.get(path(b) + '/' + result['operation_id'], headers=h), post(s, b, h=h)]
    for response in responses: error(response, 409, 'conversation_contract_mismatch')
    assert stored(s.admin) == before


def test_R01_R05_conservative_rejected_zero_write_and_success_recovery_priority(append_service):
    s = append_service; b = seed(s); h = key(b); value = body(b)
    result = post(s, b, value, h).json()
    with s.admin.begin() as db:
        facts.change_fact(db, b.fid, b.token, status='rejected', expected_version=1)
    current(s, b)
    before = stored(s.admin)
    for sentence in [SENTENCES[0], '我验证了其他表格。', '我测试了2个导出按钮。']:
        response = post(s, b, body(b, [sentence]))
        error(response, 409, 'append_requires_clarification')
        assert '尚未保存' in response.json()['error']['message']
        assert 'operation_id' not in response.text
    assert recover(s, b, h).json() == result
    assert post(s, b, value, h).json() == result
    assert stored(s.admin) == before


def test_A09_two_connections_same_key_and_different_keys(append_service):
    s = append_service; b = seed(s); value = body(b); h = key(b)
    barrier = Barrier(2)
    def submit(headers):
        barrier.wait()
        return post(s, b, value, headers)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, [h, h]))
    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json() == results[1].json()
    before = stored(s.admin)
    error(post(s, b, value), 409, 'context_conflict')
    current(s, b)
    error(post(s, b), 409, 'conversation_input_already_submitted')
    assert stored(s.admin) == before


def test_V07_recovery_single_readonly_connection(append_service):
    s = append_service; b = seed(s); h = key(b)
    assert post(s, b, h=h).status_code == 201
    sql, connections = [], set()
    def capture(conn, cursor, statement, parameters, context, many):
        sql.append(statement); connections.add(id(conn))
    event.listen(s.append_runtime.kw['bind'], 'before_cursor_execute', capture)
    before = stored(s.admin)
    try:
        assert recover(s, b, h).status_code == 200
        assert len(connections) == 1
        assert any('SHOW transaction_read_only' in q for q in sql)
        assert any('SHOW transaction_isolation' in q for q in sql)
        assert all(q.lstrip().split()[0].upper() in ('SELECT', 'SHOW') for q in sql)
        assert not any('pg_advisory' in q or 'FOR UPDATE' in q for q in sql)
    finally:
        event.remove(s.append_runtime.kw['bind'], 'before_cursor_execute', capture)
    assert stored(s.admin) == before


def test_independent_role_and_default_closed(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('CONVERSATION_APPEND_ENABLED', 'true')
    response = client.get(f'/api/v1/experience/sessions/{uuid4()}/conversation-appends/{uuid4()}',
                          headers={'Authorization': 'Bearer ' + 'x' * 43})
    error(response, 503, 'conversation_append_disabled')


def worker(s, b, h, value, mode):
    import json, os, subprocess, sys
    from pathlib import Path
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if k in os.environ}
    env['PYTHONIOENCODING'] = 'utf-8'
    data = dict(url=worker_url(s.append_runtime.kw['bind'].url).render_as_string(hide_password=False),
                schema=s.schema, sid=str(b.sid), headers=h, body=value, mode=mode)
    return subprocess.run([sys.executable, str(Path(__file__).with_name('append_process_worker.py'))],
        input=json.dumps(data), text=True, encoding='utf-8', capture_output=True, timeout=30, env=env)


@pytest.mark.parametrize('mode,exit_code,committed', [('turn', 73, False), ('first_fact', 73, False),
    ('last_fact', 73, False), ('fcs', 73, False), ('before_commit', 71, False), ('after_commit', 72, True)])
def test_A08_real_process_crash_new_process_get_only(append_service, mode, exit_code, committed):
    import json
    s = append_service; b = seed(s); h = key(b); value = body(b); before = stored(s.admin)
    crashed = worker(s, b, h, value, mode)
    assert crashed.returncode == exit_code, (crashed.returncode, crashed.stdout, crashed.stderr)
    assert crashed.stdout == '' and crashed.stderr == ''
    stable = stored(s.admin)
    if not committed: assert stable == before
    else:
        assert len(stable['experience_facts']) == 4
        assert len(stable['conversation_operations']) == 1
    restarted = worker(s, b, h, value, 'recover')
    assert restarted.returncode == 0 and restarted.stderr == ''
    result = json.loads(restarted.stdout)
    assert result['status'] == (200 if committed else 404)
    if committed: assert result['result']['effect_count'] == 3
    assert stored(s.admin) == stable


@pytest.mark.parametrize('bad', ['fact_update', 'source_update', 'funds', 'ddl', 'missing_read',
    'missing_insert', 'public_execute', 'login_owner', 'owner_money', 'membership', 'b2b_identity'])
def test_C03_independent_role_fail_closed(append_service, bad):
    s = append_service; b = seed(s)
    with s.admin.begin() as db:
        q, r, a = f'"{s.schema}"', f'"{s.append_role}"', f'"{s.auditor}"'
        if bad == 'fact_update': sql = f'GRANT UPDATE(statement) ON {q}.experience_facts TO {r}'
        elif bad == 'source_update': sql = f'GRANT UPDATE ON {q}.fact_sources TO {r}'
        elif bad == 'funds': sql = f'GRANT UPDATE ON {q}.paid_funding TO {r}'
        elif bad == 'ddl': sql = f'GRANT CREATE ON SCHEMA {q} TO {r}'
        elif bad == 'missing_read': sql = f'REVOKE SELECT ON {q}.fact_change_sources FROM {r}'
        elif bad == 'missing_insert': sql = f'REVOKE INSERT ON {q}.experience_facts FROM {r}'
        elif bad == 'public_execute': sql = f'GRANT EXECUTE ON FUNCTION {q}.maintenance_validate(uuid) TO PUBLIC'
        elif bad == 'login_owner': sql = f'ALTER ROLE {a} LOGIN'
        elif bad == 'owner_money': sql = f'GRANT UPDATE ON {q}.paid_funding TO {a}'
        elif bad == 'membership': sql = f'GRANT {a} TO {r}'
        else: sql = None
        if sql: db.execute(text(sql))
    if bad == 'b2b_identity': app.dependency_overrides[get_append_factory] = lambda: s.runtime
    before = stored(s.admin)
    error(post(s, b), 503, 'conversation_runtime_unapproved')
    error(recover(s, b, key(b)), 503, 'conversation_runtime_unapproved')
    assert stored(s.admin) == before


def test_C03_append_role_is_rejected_by_original_b2b_gate(append_service):
    from app.maintenance_api import get_maintenance_factory
    s = append_service; b = seed(s); before = stored(s.admin)
    app.dependency_overrides[get_maintenance_factory] = lambda: s.append_runtime
    error(v1post(s, b), 503, 'conversation_runtime_unapproved')
    assert stored(s.admin) == before


@pytest.mark.parametrize('attack', ['source', 'span_slot', 'after_null', 'after_missing', 'after_string',
    'after_mismatch', 'current_mismatch', 'missing_effect', 'unreceipted_fact', 'extra_turn', 'extra_assistant', 'origin', 'evidence'])
def test_A05_A06_direct_runtime_sql_corruption_rolls_back(append_service, attack, monkeypatch):
    # Use the real runtime identity, not admin, for every malicious effect.
    s = append_service; b = seed(s); before = stored(s.admin)
    # Suppress only the response projection so deferred database constraints,
    # rather than the application projector, must reject every malformed batch.
    monkeypatch.setattr(fact_append, 'view', lambda db, row: {})
    def mutate(db, context, instances):
        for obj in list(db.new):
            if isinstance(obj, FactChange) and obj.action == 'created':
                if attack == 'evidence': obj.after = dict(obj.after, evidence_id='synthetic')
                if attack.startswith('after_'):
                    after = dict(obj.after)
                    if attack == 'after_null': after['statement'] = None
                    elif attack == 'after_missing': del after['statement']
                    elif attack == 'after_string': after['version'] = '1'
                    else: after['statement'] = '我制作了伪造图。'
                    obj.after = after
            if isinstance(obj, FactChangeSource):
                if attack == 'source': obj.quote = '伪造引用'
                elif attack == 'span_slot': obj.effect_slot = 5
                elif attack == 'missing_effect': db.expunge(obj)
            if isinstance(obj, ExperienceFact):
                if attack == 'current_mismatch': obj.statement = '与引用不符'
                elif attack == 'origin': obj.origin = 'ai_extracted'
    event.listen(s.append_runtime, 'before_flush', mutate)
    try:
        # Direct service transaction must fail at projection or deferred COMMIT.
        from app.idempotency import parse
        from test_maintenance_api import KIND
        h = key(b); k = parse(h['Idempotency-Key'], b.token, KIND, f'session:{b.sid}')
        with pytest.raises((IntegrityError, ConversationError)), s.append_runtime.begin() as db:
            result, _ = fact_append.apply(db, b.sid, b.token, k, AppendCommand.model_validate(body(b)))
            if attack in ('unreceipted_fact', 'extra_turn', 'extra_assistant'):
                # Insert the unreceipted effect directly; preserve all triggers.
                if attack == 'extra_turn': db.add(ConversationTurn(session_id=b.sid, role='user', content='额外原文'))
                elif attack == 'extra_assistant': db.add(ConversationTurn(session_id=b.sid, role='assistant', content='额外未引用回复'))
                else: db.add(ExperienceFact(session_id=b.sid, project_id=b.pid, statement='未入回执事实'))
            db.flush()
    finally:
        event.remove(s.append_runtime, 'before_flush', mutate)
    assert stored(s.admin) == before


@pytest.mark.parametrize('kind', ['correct', 'withdraw', 'ambiguity', 'resolution', 'prototype'])
def test_V04_M01_actual_upgrade_preserves_v1_receipts(append_service, migrated_connection, kind):
    from alembic import command as alembic
    from test_fact_maintenance import append_operation
    s = append_service; conn, cfg = migrated_connection
    alembic.downgrade(cfg, '0013_fact_maintenance'); conn.commit()
    b = seed(s); h = key(b); value = None
    if kind == 'prototype':
        from app.idempotency import parse
        from test_maintenance_api import KIND
        k = parse(h['Idempotency-Key'], b.token, KIND, f'session:{b.sid}')
        with s.admin.begin() as db:
            fixture = append_operation(db, b, operation={'key_digest': k.digest})
            oid = fixture.oid
    elif kind in ('ambiguity', 'resolution'):
        oid, h, value = ambiguous(s, b)
        if kind == 'resolution':
            parent = oid; h = key(b); value = resolution_body(s, b)
            result = resolve(s, b, parent, value, h)
            assert result.status_code == 201, result.text
            oid = UUID(result.json()['operation_id'])
    else:
        value = command(b, action=kind)
        result = v1post(s, b, value, h)
        assert result.status_code == 201, result.text
        oid = UUID(result.json()['operation_id'])
    old = v1recovery(s, b, h)
    assert old.status_code == 200, old.text
    before = stored(s.admin)
    with s.admin() as db:
        fingerprint = db.execute(text("SELECT oid,proowner,proacl::text FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname='maintenance_validate'")).one()
    alembic.upgrade(cfg, '0014_append_batch'); conn.commit()
    with s.admin() as db:
        assert db.execute(text("SELECT oid,proowner,proacl::text FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname='maintenance_validate'")).one() == fingerprint
    assert v1recovery(s, b, h).json() == old.json()
    v1path = path(b).replace('conversation-appends', 'conversation-operations')
    assert s.client.get(v1path + '/' + str(oid), headers=h).json() == old.json()
    if kind in ('correct', 'withdraw', 'ambiguity'):
        assert v1post(s, b, value, h).json() == old.json()
    elif kind == 'resolution':
        assert resolve(s, b, parent, value, h).json() == old.json()
    error(recover(s, b, h), 409, 'conversation_contract_mismatch')
    error(s.client.get(path(b) + '/' + str(oid), headers=h), 409, 'conversation_contract_mismatch')
    assert stored(s.admin) == before


@pytest.mark.parametrize('deleted', [False, True])
def test_M02_v2_history_or_tombstone_blocks_downgrade(append_service, migrated_connection, deleted):
    from alembic import command as alembic
    s = append_service; b = seed(s)
    assert post(s, b).status_code == 201
    if deleted:
        assert s.client.delete(f'/api/v1/experience/sessions/{b.sid}', headers={'Authorization': 'Bearer ' + b.token}).status_code == 204
    before = stored(s.admin)
    conn, cfg = migrated_connection
    with pytest.raises(RuntimeError, match='append_nonempty_downgrade_refused'):
        alembic.downgrade(cfg, '0013_fact_maintenance')
    conn.rollback()
    assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0015_fact_classification'
    conn.commit()
    assert stored(s.admin) == before


def test_M01_M02_empty_roundtrip_failure_atomic_and_metadata(migrated_connection):
    from alembic import command as alembic
    conn, cfg = migrated_connection
    alembic.check(cfg); conn.commit()
    alembic.downgrade(cfg, '0013_fact_maintenance'); conn.commit()
    before = conn.execute(text("SELECT oid,proowner,proacl::text,prosrc FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname='maintenance_validate'")).one()
    conn.commit()
    def fail(conn, cursor, statement, parameters, context, many):
        if 'CREATE OR REPLACE FUNCTION' in statement:
            raise RuntimeError('synthetic_append_migration_failure')
    event.listen(conn, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='synthetic_append_migration_failure'):
            alembic.upgrade(cfg, '0014_append_batch')
        conn.rollback()
    finally: event.remove(conn, 'before_cursor_execute', fail)
    assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0013_fact_maintenance'
    assert conn.execute(text("SELECT oid,proowner,proacl::text,prosrc FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname='maintenance_validate'")).one() == before
    conn.commit()
    alembic.upgrade(cfg, '0014_append_batch'); conn.commit()
    alembic.downgrade(cfg, '0013_fact_maintenance'); conn.commit()
    assert conn.execute(text("SELECT oid,proowner,proacl::text,prosrc FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proname='maintenance_validate'")).one() == before
    conn.commit()
    alembic.upgrade(cfg, 'head'); conn.commit(); alembic.check(cfg); conn.commit()


@pytest.mark.parametrize('fault', ['unknown_version', 'wrong_decision', 'wrong_action', 'source_missing', 'source_corrupt'])
def test_V05_V07_corrupt_persistent_receipt_never_falls_back(append_service, fault):
    s = append_service; b = seed(s); h = key(b); result = post(s, b, h=h).json()
    oid = UUID(result['operation_id'])
    # Trusted fixture deliberately makes impossible legacy/corrupt state. These
    # DDL privileges are absent from either runtime LOGIN; never a service path.
    with s.admin.begin() as db:
        if fault in ('unknown_version', 'wrong_decision', 'wrong_action'):
            db.execute(text('ALTER TABLE conversation_operations DISABLE TRIGGER USER'))
            if fault != 'wrong_action':
                db.execute(text('ALTER TABLE conversation_operations DROP CONSTRAINT ck_co_identity'))
                db.execute(text('ALTER TABLE conversation_operations DROP CONSTRAINT ck_co_shape'))
            column, value = {'unknown_version': ('contract_version', 99),
                'wrong_decision': ('decision_contract', 'unknown-v9'), 'wrong_action': ('action', 'correct')}[fault]
            db.execute(text(f'UPDATE conversation_operations SET {column}=:v WHERE id=:o'), {'v': value, 'o': oid})
            db.execute(text('ALTER TABLE conversation_operations ENABLE TRIGGER USER'))
        else:
            db.execute(text('ALTER TABLE fact_change_sources DISABLE TRIGGER USER'))
            if fault == 'source_missing': db.execute(text('DELETE FROM fact_change_sources WHERE operation_id=:o'), {'o': oid})
            else: db.execute(text("UPDATE fact_change_sources SET quote='损坏' WHERE operation_id=:o"), {'o': oid})
            db.execute(text('ALTER TABLE fact_change_sources ENABLE TRIGGER USER'))
    before = stored(s.admin)
    code = 'conversation_contract_mismatch' if fault.startswith(('unknown', 'wrong')) else 'conversation_result_unavailable'
    for response in [recover(s, b, h), s.client.get(path(b) + '/' + str(oid), headers=h)]:
        error(response, 409 if code.endswith('mismatch') else 410, code)
    other = seed(s); before = stored(s.admin)
    error(s.client.get(path(other) + '/' + str(oid), headers={'Authorization': 'Bearer ' + other.token}), 404, 'resource_unavailable')
    wrong = dict(h, Authorization='Bearer ' + other.token)
    error(recover(s, b, wrong), 401, 'idempotency_credential_invalid')
    assert stored(s.admin) == before


@pytest.mark.parametrize('state', ['reserved', 'running', 'unknown', 'stopped', 'ended', 'six_rounds', 'failed', 'stale'])
def test_A12_gates_no_dispatch_no_round_reset(append_service, state):
    from datetime import timedelta
    from app.models import MiningRun, utcnow
    s = append_service; b = seed(s)
    with s.admin.begin() as db:
        session = db.get(ExperienceSession, b.sid)
        if state == 'stopped': session.mining_status = 'stopped'
        elif state == 'ended': session.status = 'ended'
        else:
            for i in range(6 if state == 'six_rounds' else 1):
                turn = facts.add_turn(db, b.sid, b.token, f'合成旧回合{i}。')
                db.refresh(session)
                db.add(MiningRun(session_id=b.sid, project_id=b.pid, input_turn_id=turn.id,
                    base_revision=1, reserved_revision=session.context_revision,
                    state='completed' if state == 'six_rounds' else state, lease_until=utcnow() + timedelta(minutes=1)))
    current(s, b); before = stored(s.admin)
    with s.admin() as db:
        runs = db.scalars(text('SELECT to_jsonb(r)::text FROM ai_mining_runs r ORDER BY id')).all()
        status = db.get(ExperienceSession, b.sid).mining_status
    response = post(s, b)
    if state in ('reserved', 'running', 'unknown', 'ended'):
        error(response, 409, 'session_ended' if state == 'ended' else 'mining_result_unresolved')
        assert stored(s.admin) == before
    else: assert response.status_code == 201, response.text
    with s.admin() as db:
        assert db.scalars(text('SELECT to_jsonb(r)::text FROM ai_mining_runs r ORDER BY id')).all() == runs
        assert db.get(ExperienceSession, b.sid).mining_status == status


@pytest.mark.parametrize('direction', ['old_turn', 'old_mining', 'new_turn', 'new_fact', 'new_mining'])
def test_A13_cross_entry_input_and_old_sources(append_service, direction):
    from app.mining_api import get_mining_factory, get_provider
    from app.mining_provider import ScriptedProvider
    from test_idempotency import headers
    s = append_service; b = seed(s); value = body(b); content = value['input']['content']
    if direction.startswith('old'):
        with s.admin.begin() as db:
            turn = facts.add_turn(db, b.sid, b.token, content)
            if direction == 'old_mining':
                from app.models import MiningRun, utcnow
                from datetime import timedelta
                db.refresh(db.get(ExperienceSession, b.sid))
                db.add(MiningRun(session_id=b.sid, project_id=b.pid, input_turn_id=turn.id,
                    base_revision=1, reserved_revision=db.get(ExperienceSession, b.sid).context_revision,
                    state='completed', lease_until=utcnow() + timedelta(minutes=1)))
        current(s, b); value['base_revision'] = b.revision; before = stored(s.admin)
        response = post(s, b, value)
    else:
        result = post(s, b, value).json(); before = stored(s.admin)
        h = {'Authorization': 'Bearer ' + b.token}
        root = '/api/v1/experience'
        if direction == 'new_turn':
            response = s.client.post(f'{root}/sessions/{b.sid}/turns', headers=h, json={'content': content})
        elif direction == 'new_fact':
            response = s.client.post(f'{root}/projects/{b.pid}/facts', headers=h,
                json={'statement': SENTENCES[0], 'source_turn_ids': [result['input_turn_id']]})
        else:
            class Never(ScriptedProvider):
                async def mine(self, *args, **kwargs): raise AssertionError('Provider must not run')
            app.dependency_overrides[get_mining_factory] = lambda: s.admin
            app.dependency_overrides[get_provider] = lambda: Never()
            current(s, b)
            response = s.client.post(f'{root}/sessions/{b.sid}/mining-runs',
                headers=headers('mining_run', f'session:{b.sid}', b.token)[0],
                json={'project_id': str(b.pid), 'base_revision': b.revision, 'input_turn_id': result['input_turn_id']})
    error(response, 409, 'conversation_input_already_submitted')
    assert stored(s.admin) == before


@pytest.mark.parametrize('action', ['update', 'delete', 'insert', 'move'])
def test_A11_audited_v2_original_sources_remain_immutable(append_service, action):
    s = append_service; b = seed(s); result = post(s, b).json()
    fid = UUID(result['effects'][0]['fact_id']); before = stored(s.admin)
    with pytest.raises(IntegrityError), s.admin.begin() as db:
        if action == 'update': db.execute(text("UPDATE fact_sources SET citations='[]' WHERE fact_id=:f"), {'f': fid})
        elif action == 'delete': db.execute(text('DELETE FROM fact_sources WHERE fact_id=:f'), {'f': fid})
        elif action == 'insert': db.add(FactSource(session_id=b.sid, fact_id=fid, turn_id=b.tid))
        else: db.execute(text('UPDATE fact_sources SET fact_id=:f WHERE fact_id=:old'), {'f': fid, 'old': b.fid})
    assert stored(s.admin) == before


@pytest.mark.parametrize('first', ['append', 'control'])
@pytest.mark.parametrize('control', ['edit', 'stop', 'end', 'delete'])
def test_A10_two_connection_controlled_lock_linearization(append_service, first, control):
    import time
    from threading import Event
    from app.idempotency import parse
    from test_maintenance_api import KIND
    s = append_service; b = seed(s); h = key(b); value = body(b)
    ready, release = Event(), Event()
    pids = {}
    def apply_control(db):
        session = facts.authorize(db, b.sid, b.token, lock=True)
        if control == 'edit': facts.change_fact(db, b.fid, b.token, statement='我测试了4个导出按钮。', expected_version=1)
        elif control == 'stop': session.mining_status = 'stopped'; db.flush()
        elif control == 'end': facts.end_session(db, b.sid, b.token); db.flush()
        else: db.delete(session); db.flush()
    def held():
        factory = s.append_runtime if first == 'append' else s.admin
        with factory.begin() as db:
            if first == 'append':
                k = parse(h['Idempotency-Key'], b.token, KIND, f'session:{b.sid}')
                fact_append.apply(db, b.sid, b.token, k, AppendCommand.model_validate(value))
            else: apply_control(db)
            ready.set(); assert release.wait(10)
    def waiting():
        if first == 'control': return post(s, b, value, h)
        with s.admin.begin() as db:
            pids['waiting'] = db.scalar(text('SELECT pg_backend_pid()'))
            apply_control(db)
    with ThreadPoolExecutor(2) as pool:
        holder = pool.submit(held); assert ready.wait(10)
        waiter = pool.submit(waiting)
        observed = False
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with s.admin() as db:
                    if first == 'control':
                        observed = db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND usename=:r AND wait_event_type='Lock')"), {'r': s.append_role})
                    elif 'waiting' in pids:
                        observed = db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=:pid AND wait_event_type='Lock')"), {'pid': pids['waiting']})
                if observed: break
                time.sleep(.02)
            assert observed, 'Expected real Session row lock wait'
        finally: release.set()
        holder.result(10); response = waiter.result(10)
    if first == 'control':
        if control == 'stop':
            # stop is allowed, but it advances context; the in-flight old
            # revision must conflict. A later explicit current request succeeds.
            error(response, 409, 'context_conflict')
            current(s, b)
            assert post(s, b).status_code == 201
        else: error(response, 404 if control == 'delete' else 409,
                    {'delete': 'resource_unavailable', 'end': 'session_ended', 'edit': 'context_conflict'}[control])
    if first == 'append':
        response = recover(s, b, h)
        if control == 'delete': error(response, 410, 'conversation_resource_deleted')
        else: assert response.status_code == 200 and response.json()['effect_count'] == 3


@pytest.mark.parametrize('same_key', [True, False])
def test_A09_real_process_concurrent_submission(append_service, same_key):
    import json
    s = append_service; b = seed(s); h = key(b); value = body(b)
    with ThreadPoolExecutor(2) as pool:
        jobs = [pool.submit(worker, s, b, headers, value, 'submit') for headers in (h, h if same_key else key(b))]
        results = [job.result(30) for job in jobs]
    assert all(r.returncode == 0 and r.stderr == '' for r in results)
    responses = [json.loads(r.stdout) for r in results]
    assert sorted(r['status'] for r in responses) == ([200, 201] if same_key else [201, 409])
    if same_key: assert responses[0]['result'] == responses[1]['result']
    with s.admin() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_operations')) == 1
        assert db.scalar(text('SELECT count(*) FROM experience_facts')) == 4
        assert db.scalar(text('SELECT count(*) FROM conversation_turns')) == 2


@pytest.mark.parametrize('attack', ['too_few', 'old_turn', 'old_change', 'missing_null'])
def test_A05_A06_v2_direct_sql_strictness_beyond_v1(append_service, attack):
    from test_fact_maintenance import append_operation, UNICODE
    s = append_service; b = seed(s); before = stored(s.admin)
    operation = {'contract_version': 2, 'decision_contract': 'append-batch-v1'}
    source, after = None, None
    if attack == 'too_few':
        # 0013 permits fewer effects than proposals; v2 must reject it.
        operation['proposal_spans'] = [dict(role='statement', start=0, end=len(UNICODE))] * 2
    elif attack == 'old_turn': operation['input_turn_id'] = b.tid
    elif attack == 'old_change':
        with s.admin() as db:
            change = db.scalar(select(FactChange).where(FactChange.fact_id == b.fid))
            source = {'change_id': change.id, 'fact_id': b.fid}
    else:
        def after(value):
            del value['evidence_id']
            return value
    with pytest.raises(IntegrityError), s.admin.begin() as db:
        append_operation(db, b, operation=operation, source=source, after=after)
    assert stored(s.admin) == before


def test_R03_known_legacy_semantic_gap_remains_production_block(append_service):
    s = append_service; b = seed(s, status='rejected')
    with s.admin.begin() as db:
        turn = facts.add_turn(db, b.sid, b.token, '我检查了另一个表述的导出按钮。')
    current(s, b)
    before = stored(s.admin)
    error(post(s, b, body(b, ['我测试了2个导出按钮。'])), 409, 'append_requires_clarification')
    assert stored(s.admin) == before
    # Explicitly document an existing gap, not a semantic protection claim.
    response = s.client.post(f'/api/v1/experience/projects/{b.pid}/facts',
        headers={'Authorization': 'Bearer ' + b.token},
        json={'statement': '我检查了导出按钮。', 'source_turn_ids': [str(turn.id)]})
    assert response.status_code == 201
    with s.admin() as db: assert db.get(ExperienceFact, b.fid).status == 'rejected'


def test_V03_root_resolution_same_key_is_payload_conflict(append_service):
    s = append_service; b = seed(s); parent, h, value = ambiguous(s, b)
    before = stored(s.admin)
    error(resolve(s, b, parent, resolution_body(s, b), h), 409, 'idempotency_payload_mismatch')
    assert stored(s.admin) == before
    rh = key(b); child_body = resolution_body(s, b)
    assert resolve(s, b, parent, child_body, rh).status_code == 201
    before = stored(s.admin)
    error(v1post(s, b, value, rh), 409, 'idempotency_payload_mismatch')
    error(post(s, b, h=rh), 409, 'conversation_contract_mismatch')
    assert stored(s.admin) == before


def test_v2_recovery_after_later_edit_confirm_and_legacy_export(append_service):
    s = append_service; b = seed(s); h = key(b); result = post(s, b, body(b, ['我制作了🧪原型图。']), h).json()
    effect = result['effects'][0]
    with s.admin.begin() as db:
        fact = facts.change_fact(db, UUID(effect['fact_id']), b.token, status='user_confirmed', expected_version=1)
        facts.change_fact(db, fact.id, b.token, statement='我制作了2张🧪原型图。', expected_version=2)
    before = stored(s.admin)
    restored = recover(s, b, h).json()
    assert restored['effects'][0] == dict(effect, current_version=3)
    export = s.client.get(f'/api/v1/experience/sessions/{b.sid}/export', headers=h)
    assert export.status_code == 200
    assert '🧪' in export.text
    assert stored(s.admin) == before


@pytest.mark.parametrize('space', ['\u00a0', '\u2003', '\u0085', '\u001c', '\u3000'])
def test_U01_unicode_whitespace_same_contract_in_python_and_postgresql(append_service, space):
    s = append_service; b = seed(s); value = body(b, [SENTENCES[0]])
    value['input']['content'] = space + SENTENCES[0] + space
    value['statements'][0].update(start=1, end=1 + len(SENTENCES[0]))
    response = post(s, b, value)
    assert response.status_code == 201, response.text


@pytest.mark.parametrize('content', ['我制作了\x00图。', '我制作了\ud800图。'])
def test_U01_invalid_postgresql_text_rejected_before_effects(content):
    if '\ud800' in content:
        with pytest.raises(ValidationError):
            AppendCommand.model_validate(body(type('B', (), {'revision': 1})(), [content]))
        return
    with pytest.raises(ConversationError, match='append_source_invalid'):
        append_spans(AppendCommand.model_validate(body(type('B', (), {'revision': 1})(), [content])))


@pytest.mark.parametrize('quote', ['团队整理了27条缺失记录。', '我可能整理过27条缺失记录。',
    '我没有整理了27条缺失记录。', '我整理了27条缺失记录但这是假设。', '我整理了“我完成了工作”的示例。',
    '我准备整理了27条缺失记录。', '我正在整理27条缺失记录。', '我整理了27条记录并制作了图。'])
def test_L01_additional_positive_only_adversarial_cases(quote):
    with pytest.raises(ConversationError, match='append_source_invalid'):
        append_spans(AppendCommand.model_validate(body(type('B', (), {'revision': 1})(), [quote])))


@pytest.mark.parametrize('failure', ['readonly', 'isolation'])
def test_V07_readonly_option_failure_refuses_projection(append_service, failure):
    s = append_service; b = seed(s); h = key(b); assert post(s, b, h=h).status_code == 201
    before = stored(s.admin)
    def alter_show(conn, cursor, statement, parameters, context, many):
        if failure == 'readonly' and statement == 'SHOW transaction_read_only': return "SELECT 'off'", parameters
        if failure == 'isolation' and statement == 'SHOW transaction_isolation': return "SELECT 'read committed'", parameters
        return statement, parameters
    event.listen(s.append_runtime.kw['bind'], 'before_cursor_execute', alter_show, retval=True)
    try: error(recover(s, b, h), 503, 'conversation_readonly_required')
    finally: event.remove(s.append_runtime.kw['bind'], 'before_cursor_execute', alter_show)
    assert stored(s.admin) == before


def legacy_rejected_history(s, b, current_status, history_field):
    """Trusted legacy fixture, never a new API transition or runtime bypass.

    Arrange an unaudited fact restored by a historical writer. Partial legacy
    snapshots exercise before/after independently; they are constructed before
    INSERT, never backfilled or rewritten by the 0014 upgrade.
    """
    with s.admin.begin() as db:
        session = facts.authorize(db, b.sid, b.token, lock=True)
        turn = facts.add_turn(db, b.sid, b.token, '我维护了旧清单。')
        fact = facts.add_fact(db, b.pid, b.token, turn.content, [turn.id])
        before = facts.snapshot(db, fact)
        fact.status = 'rejected'; db.flush()
        after = facts.snapshot(db, fact)
        if history_field == 'before': after.pop('status')
        db.add(FactChange(id=uuid4(), fact_id=fact.id, session_id=b.sid,
                         action='status_changed', actor='user', before=before, after=after))
        db.flush()
        before = facts.snapshot(db, fact)
        if history_field == 'after': before.pop('status')
        # Simulate a pre-existing old edit that restored pending. The current
        # HTTP/domain writer does not permit editing a rejected fact.
        fact.statement = '我维护了旧记录清单。'
        fact.status = 'pending'; db.flush()
        change = FactChange(id=uuid4(), fact_id=fact.id, session_id=b.sid,
                            action='edited', actor='user', before=before)
        change.after = facts.snapshot(db, fact, edit=change)
        db.add(change); db.flush()
        if current_status == 'user_confirmed':
            facts.change_fact(db, fact.id, b.token, status=current_status, expected_version=fact.version)
        db.refresh(session)
        return fact.id


@pytest.mark.parametrize('entry', ['http', 'restricted_sql'])
@pytest.mark.parametrize('current_status', ['pending', 'user_confirmed'])
@pytest.mark.parametrize('history_field', ['before', 'after', 'both'])
def test_D3_legacy_rejected_history_blocks_after_upgrade_preserves_v1(
        append_service, migrated_connection, entry, current_status, history_field):
    from alembic import command as alembic
    from test_fact_maintenance import append_operation
    s = append_service; conn, cfg = migrated_connection
    alembic.downgrade(cfg, '0013_fact_maintenance'); conn.commit()
    b = seed(s); h = key(b); original_body = command(b)
    original = v1post(s, b, original_body, h)
    assert original.status_code == 201, original.text
    legacy_id = legacy_rejected_history(s, b, current_status, history_field)
    current(s, b)
    with s.admin() as db:
        assert db.get(ExperienceFact, legacy_id).status == current_status
        for field in ('before', 'after'):
            count = db.scalar(select(text('count(*)')).select_from(FactChange).where(
                FactChange.fact_id == legacy_id, getattr(FactChange, field)['status'].as_string() == 'rejected'))
            assert bool(count) == (history_field in (field, 'both'))
        assert db.scalar(select(ExperienceFact.id).where(
            ExperienceFact.session_id == b.sid, ExperienceFact.status == 'rejected').limit(1)) is None
    before = stored(s.admin)
    alembic.upgrade(cfg, '0014_append_batch'); conn.commit()
    assert stored(s.admin) == before  # No rewriting old facts, snapshots or v1 CO.
    if entry == 'http':
        fresh_key = key(b)
        response = post(s, b, h=fresh_key)  # Three new statements, all zero-write.
        error(response, 409, 'append_requires_clarification')
        assert '尚未保存' in response.json()['error']['message']
        assert 'operation_id' not in response.text
        error(recover(s, b, fresh_key), 404, 'conversation_operation_not_found')
    else:
        # No fact_append.apply()/D3 service guard or projector is invoked.
        # Real restricted LOGIN must be rejected by deferred v2 SQL at COMMIT.
        with pytest.raises(IntegrityError, match='append_v2_bijection'), s.append_runtime.begin() as db:
            assert db.scalar(text('SELECT current_user')) == s.append_role
            append_operation(db, b, operation={'contract_version': 2, 'decision_contract': 'append-batch-v1'})
    assert stored(s.admin) == before
    assert v1recovery(s, b, h).json() == original.json()
    v1path = path(b).replace('conversation-appends', 'conversation-operations')
    assert s.client.get(v1path + '/' + original.json()['operation_id'], headers=h).json() == original.json()
    replay = v1post(s, b, original_body, h)
    assert replay.status_code == 200 and replay.headers['Idempotency-Replayed'] == 'true'
    assert replay.json() == original.json()
    session = s.client.get(f'/api/v1/experience/sessions/{b.sid}', headers=h)
    assert session.status_code == 200, session.text
    assert stored(s.admin) == before


def test_D3_legacy_history_is_session_scoped_for_http_and_sql(append_service, migrated_connection):
    from alembic import command as alembic
    from test_fact_maintenance import append_operation
    s = append_service; conn, cfg = migrated_connection
    alembic.downgrade(cfg, '0013_fact_maintenance'); conn.commit()
    old = seed(s); legacy_rejected_history(s, old, 'user_confirmed', 'both')
    clean = seed(s)
    alembic.upgrade(cfg, '0014_append_batch'); conn.commit()
    assert post(s, clean).status_code == 201
    with s.append_runtime.begin() as db:
        append_operation(db, clean, operation={'contract_version': 2, 'decision_contract': 'append-batch-v1'})
    current(s, old); before = stored(s.admin)
    error(post(s, old), 409, 'append_requires_clarification')
    assert stored(s.admin) == before


def test_D3_committed_v2_recovery_precedes_later_legacy_history(append_service):
    s = append_service; b = seed(s); h = key(b); original_body = body(b)
    result = post(s, b, original_body, h)
    assert result.status_code == 201
    legacy_rejected_history(s, b, 'pending', 'both')
    current(s, b); before = stored(s.admin)
    assert recover(s, b, h).json() == result.json()
    assert s.client.get(path(b) + '/' + result.json()['operation_id'], headers=h).json() == result.json()
    replay = post(s, b, original_body, h)
    assert replay.status_code == 200 and replay.headers['Idempotency-Replayed'] == 'true'
    assert replay.json() == result.json()
    error(post(s, b), 409, 'append_requires_clarification')
    assert stored(s.admin) == before


@pytest.mark.parametrize('action', ['correct', 'withdraw', 'prototype'])
def test_D3_history_does_not_restrict_legal_v1_writes(append_service, migrated_connection, action):
    from alembic import command as alembic
    from app.idempotency import parse
    from test_fact_maintenance import append_operation
    from test_maintenance_api import KIND
    s = append_service; conn, cfg = migrated_connection
    alembic.downgrade(cfg, '0013_fact_maintenance'); conn.commit()
    b = seed(s); legacy_rejected_history(s, b, 'pending', 'both'); current(s, b)
    before = stored(s.admin)
    alembic.upgrade(cfg, '0014_append_batch'); conn.commit()
    assert stored(s.admin) == before
    h = key(b)
    if action == 'prototype':
        k = parse(h['Idempotency-Key'], b.token, KIND, f'session:{b.sid}')
        with s.append_runtime.begin() as db:
            fixture = append_operation(db, b, operation={'key_digest': k.digest})
            oid = fixture.oid
    else:
        response = v1post(s, b, command(b, action=action), h)
        assert response.status_code == 201, response.text
        oid = response.json()['operation_id']
    stable = stored(s.admin)
    restored = v1recovery(s, b, h)
    assert restored.status_code == 200 and restored.json()['contract_version'] == 1
    assert str(restored.json()['operation_id']) == str(oid)
    assert stored(s.admin) == stable
