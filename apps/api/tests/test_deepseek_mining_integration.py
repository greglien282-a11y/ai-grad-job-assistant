"""Offline HTTP -> existing mining state machine -> real isolated PostgreSQL.

No real Provider dependency override. Runtime schemas/DTOs remain scripted-only;
the direct test executor is a seam demonstration, NOT production admission.
"""
import asyncio
from datetime import timedelta
import hashlib
import json
import os
import socket
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from test_http_api import api, patch
from test_idempotency import headers
from app import mining, idempotency
from app.main import app
from app.mining_api import Start, get_mining_factory, get_provider
from app.mining_context import MiningContext, StopContext, UserContext
from app.mining_provider import MiningInput
from app.models import ExperienceFact, ExperienceSession, MiningRun, utcnow
from app.offline_output_contract import HISTORICAL_SHA, historical_body, envelope
from app.cost_ledger import canonical
from offline_deepseek_mining import OfflineDeepSeekMining, build_request, REQUEST_VERSION

ROOT = '/api/v1/experience'
TEXT = '我编写了离线校验器。'  # independent synthetic integration fixture, not S03/b


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('External network or native credential access forbidden')
    # libpq connects only to the explicit disposable TEST_DATABASE_URL below.
    # HTTPX MockTransport needs neither Python sockets nor native credential APIs.
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)
    import ctypes
    monkeypatch.setattr(ctypes, 'WinDLL', forbidden, raising=False)


@pytest.fixture(scope='module', autouse=True)
def test_database_only():
    value = os.getenv('TEST_DATABASE_URL')
    if value:
        url = make_url(value)
        assert url.host in ('127.0.0.1', 'localhost')
        assert url.database in ('pathwise_test', 'pathwise_e2e')


@pytest.fixture
def flow(api):
    client, factory = api
    app.dependency_overrides[get_mining_factory] = lambda: factory
    response = client.post(ROOT + '/sessions', json={'raw_input': TEXT})
    assert response.status_code == 201
    data = response.json()
    auth = {'Authorization': 'Bearer ' + data['access_token']}
    yield client, factory, data, auth


def aggregate(flow):
    client, _, data, auth = flow
    result = client.get(ROOT + '/sessions/' + data['session_id'], headers=auth)
    assert result.status_code == 200
    return result.json()


def reserve(flow, *, content=None, answered_question_ids=None):
    _, factory, data, _ = flow
    sid, token = UUID(data['session_id']), data['access_token']
    scope = 'session:' + str(sid)
    h, _ = headers('mining_run', scope, token)
    key = idempotency.parse(h['Idempotency-Key'], token, 'mining_run', scope)
    body = Start(project_id=data['project_id'], base_revision=aggregate(flow)['context_revision'],
                 answered_question_ids=answered_question_ids,
                 **({'content': content} if content else {'input_turn_id': data['initial_turn_id']}))
    rid, fresh = mining.reserve(factory, sid, token, key, body)
    assert fresh
    return sid, token, rid, key, body


def output(context, *, candidate=True):
    turn = context.user_turns[0]
    return dict(schema_version=2, candidates=[dict(citation=dict(turn_id=str(turn.turn_id),
        quote=turn.content, start=0, end=len(turn.content)))] if candidate else [],
        questions=[dict(text='是否有可供你自行核对的依据？', purpose='verification',
                        source_turn_ids=[str(turn.turn_id)])], stop=False, stop_reason=None)


def provider(mutate=None, *, after=None, fault=None):
    def respond(request):
        context = MiningContext.model_validate_json(json.loads(request.content)['messages'][1]['content'])
        value = envelope(canonical(output(context)))
        if mutate: mutate(value, context)
        if after: after()
        if fault == 'timeout': raise httpx.ReadTimeout('fixture text must not escape')
        if fault == 'disconnect': raise httpx.ReadError('fixture text must not escape')
        if fault == 'cancel': raise asyncio.CancelledError()
        return httpx.Response(200, json=value)
    return OfflineDeepSeekMining(httpx.MockTransport(respond))


def execute(flow, p, reserved):
    sid, token, rid, *_ = reserved
    asyncio.run(mining.execute(flow[1], p, sid, token, rid))
    return aggregate(flow)['mining_runs'][-1]


def test_full_chain_pending_sources_review_and_summary(flow):
    p = provider()
    held = reserve(flow)
    run = execute(flow, p, held)
    state = aggregate(flow)
    assert run['state'] == 'completed' and len(run['candidate_fact_ids']) == 1
    fact = state['facts'][0]
    assert fact['status'] == 'pending' and fact['statement'] == TEXT
    assert fact['source_turn_ids'] == [flow[2]['initial_turn_id']]
    assert fact['citations'] == [dict(turn_id=flow[2]['initial_turn_id'], quote=TEXT, start=0, end=len(TEXT))]
    assert p.calls == 1 and p.usage['input'] == 1000 and p.usage['output'] == 200
    assert hashlib.sha256(p.request.body).hexdigest() == p.request.request_sha
    assert p.request.version == REQUEST_VERSION and p.request.request_sha != HISTORICAL_SHA
    assert hashlib.sha256(historical_body()).hexdigest() == HISTORICAL_SHA
    wire = json.loads(p.request.body)
    assert json.loads(wire['messages'][1]['content'])['input_turn_id'] == flow[2]['initial_turn_id']
    assert flow[2]['access_token'] not in p.request.body.decode()
    assert wire['model'] == 'deepseek-flash' and wire['thinking'] == {'type': 'disabled'}
    assert wire['response_format'] == {'type': 'json_object'} and wire['stream'] is False
    client, factory, data, auth = flow
    summary = ROOT + '/projects/' + data['project_id'] + '/experience-summary'
    assert client.get(summary, headers=auth).json()['text'] == ''
    with factory() as db:
        stored = db.get(ExperienceFact, UUID(fact['id']))
        assert stored.status == 'pending' and str(stored.ai_run_id) == run['id']
        for table in ('cost_calls', 'paid_calls', 'paid_grants', 'controlled_probe'):
            assert db.scalar(text('SELECT count(*) FROM ' + table)) == 0
    confirmed = patch(client, fact, auth, 'confirm')
    assert confirmed.status_code == 200 and confirmed.json()['status'] == 'user_confirmed'
    assert client.get(summary, headers=auth).json()['text'] == TEXT
    # Existing DTO remains truthful about the unchanged synthetic test run. This
    # demonstrates why a real Provider cannot be admitted until DTO/schema work.
    assert run['provider'] == 'scripted' and run['synthetic'] is True


@pytest.mark.parametrize('case', ['empty', 'bad_json', 'bad_schema', 'bad_reference', 'offset',
    'negation_lost', 'team_promoted', 'team_exact', 'truncated', 'usage', 'model', 'duplicate_question'])
def test_validation_boundaries(flow, case):
    original = {'negation_lost': '我没有部署服务。', 'team_promoted': '我们团队部署了服务。',
                'team_exact': '我们团队部署了服务。'}.get(case)
    held = reserve(flow, content=original)
    def mutate(packet, context):
        result = output(context)
        if case == 'empty': result['candidates'] = []
        if case == 'bad_schema': result['status'] = 'user_confirmed'
        if case == 'bad_reference': result['candidates'][0]['citation']['turn_id'] = '22222222-2222-4222-8222-222222222222'
        if case == 'offset': result['candidates'][0]['citation']['end'] = len(TEXT.encode('utf-8'))
        if case in ('negation_lost', 'team_promoted'):
            result['candidates'][0]['citation'].update(quote='我部署了服务。', end=7)
        if case == 'duplicate_question': result['questions'] *= 2
        packet['choices'][0]['message']['content'] = '{' if case == 'bad_json' else canonical(result)
        if case == 'truncated': packet['choices'][0]['finish_reason'] = 'length'
        if case == 'usage': packet['usage']['total_tokens'] += 1
        if case == 'model': packet['model'] = 'not-approved'
    p = provider(mutate)
    run = execute(flow, p, held)
    assert run['state'] == ('completed' if case == 'empty' else 'failed')
    assert run['candidate_fact_ids'] == [] and aggregate(flow)['facts'] == []
    if case == 'empty': assert len(run['questions']) == 1
    else: assert run['questions'] == [] and run['error_code'] == 'provider_output_invalid'
    assert p.calls == 1


@pytest.mark.parametrize('fault', ['timeout', 'disconnect', 'cancel'])
def test_unknown_no_resend_and_readonly_recovery(flow, fault):
    p, held = provider(fault=fault), reserve(flow)
    run = execute(flow, p, held)
    assert run['state'] == 'unknown' and aggregate(flow)['facts'] == []
    sid, token, rid, key, body = held
    revision = aggregate(flow)['context_revision']
    assert mining.reserve(flow[1], sid, token, key, body) == (rid, False)
    execute(flow, p, held)
    with flow[1]() as db, db.begin():
        assert mining.recover(db, sid, token, key)['state'] == 'unknown'
    assert p.calls == 1 and aggregate(flow)['context_revision'] == revision


@pytest.mark.parametrize('change', ['revision', 'lease', 'stop', 'end'])
def test_late_valid_http_output_cannot_publish(flow, change):
    held = reserve(flow)
    sid, _, rid, *_ = held
    def change_state():
        with flow[1]() as db, db.begin():
            session = db.get(ExperienceSession, sid)
            if change == 'revision': session.context_revision += 1
            if change == 'lease': db.get(MiningRun, rid).lease_until = utcnow() - timedelta(seconds=1)
            if change == 'stop': session.mining_status = 'stopped'
            if change == 'end': session.status = 'ended'
    p = provider(after=change_state)
    run = execute(flow, p, held)
    assert run['state'] == ('unknown' if change == 'lease' else 'stale'), (run['error_code'], p.safe_code)
    assert aggregate(flow)['facts'] == [] and p.usage is not None
    assert p.calls == 1


def test_repeated_execution_never_republishes_or_resends(flow):
    p, held = provider(), reserve(flow)
    run = execute(flow, p, held)
    before = aggregate(flow)
    assert mining.reserve(flow[1], *held[:2], held[3], held[4]) == (held[2], False)
    assert execute(flow, p, held) == run
    after = aggregate(flow)
    assert p.calls == 1 and len(after['facts']) == 1
    assert after['context_revision'] == before['context_revision']


def test_multiround_context_and_repeated_question_guard(flow):
    p = provider()
    first = execute(flow, p, reserve(flow))
    qid = first['questions'][0]['id']
    held = reserve(flow, content='我没有部署服务。', answered_question_ids=[qid])
    # An exact old question is not made valid by a correct envelope or citation.
    repeated = provider()
    failed = execute(flow, repeated, held)
    assert failed['state'] == 'failed'
    context = json.loads(json.loads(repeated.request.body)['messages'][1]['content'])
    assert len(context['user_turns']) == 2 and len(context['facts']) == 1
    answer = context['user_turns'][0]
    assert answer['content'] == '我没有部署服务。'
    assert answer['answered_questions'] == [dict(question_id=qid, question_version=1)]
    assert context['questions'][0]['answered_turn_id'] == answer['turn_id']
    assert len(aggregate(flow)['facts']) == 1


def test_multiround_new_question_and_preserved_negative_fact(flow):
    first = execute(flow, provider(), reserve(flow))
    def next_question(packet, context):
        value = output(context)
        value['questions'][0]['text'] = '还有可供核对的原始说明吗？'
        packet['choices'][0]['message']['content'] = canonical(value)
    held = reserve(flow, content='我没有部署服务。', answered_question_ids=[first['questions'][0]['id']])
    p = provider(next_question)
    run = execute(flow, p, held)
    state = aggregate(flow)
    assert run['state'] == 'completed' and len(state['facts']) == 2
    negative = next(f for f in state['facts'] if f['ai_run_id'] == run['id'])
    assert negative['statement'] == '我没有部署服务。' and negative['status'] == 'pending'
    assert negative['citations'][0]['turn_id'] == run['input_turn_id']


@pytest.mark.parametrize('original', ['我们团队部署了服务。', '我记不清部署细节。', '我计划部署服务。'])
def test_unclear_sources_can_clarify_without_creating_contribution(flow, original):
    def clarification(packet, context):
        value = output(context, candidate=False)
        value['questions'][0].update(text='你本人已经完成了什么？记不清可以说明。', purpose='contribution')
        packet['choices'][0]['message']['content'] = canonical(value)
    run = execute(flow, provider(clarification), reserve(flow, content=original))
    assert run['state'] == 'completed' and run['candidate_fact_ids'] == []
    assert aggregate(flow)['facts'] == [] and len(run['questions']) == 1


def test_db_checks_reject_other_session_even_with_a_valid_foreign_snapshot(flow):
    # Snapshot validation alone is insufficient: complete() must recheck actual
    # DB source ownership and snapshot project/revision, not just string slices.
    from app import facts
    held = reserve(flow)
    sid, token, rid, *_ = held
    snapshot = mining.claim(flow[1], sid, token, rid, contract_version=2).context
    with flow[1]() as db, db.begin():
        _, turn, _ = facts.create_experience(db, TEXT)
        foreign = snapshot.model_copy(update={'user_turns': (UserContext(turn_id=turn.id, content=TEXT),)})
    from app.mining_provider import MiningOutputV2
    valid_foreign = MiningOutputV2.model_validate(output(foreign))
    from app.mining_validation import validate_context_v2
    validate_context_v2(foreign, valid_foreign)  # pure spans pass, DB ownership must not
    with pytest.raises(ValueError, match='Invalid atomic source'):
        mining.complete(flow[1], sid, token, rid, valid_foreign, context=foreign)
    assert aggregate(flow)['facts'] == []


def test_no_factory_admission_or_nonmock_transport(monkeypatch):
    with pytest.raises(ValueError, match='offline_mock_required'):
        OfflineDeepSeekMining(None)
    with pytest.raises(mining.MiningError, match='ai_provider_unapproved'):
        mining.safe_provider(provider())
    monkeypatch.setenv('AI_ENABLED', 'true')
    monkeypatch.setenv('AI_PROVIDER', 'deepseek_official')
    with pytest.raises(mining.MiningError, match='ai_provider_unapproved'): get_provider()


def test_payload_only_ignores_legacy_raw_input():
    from uuid import uuid4
    # Numeric identifier fragments must not be mistaken for private user text.
    tid = UUID('13812345-6789-4111-8111-111111111111')
    context = MiningContext(project_id=uuid4(), context_revision=1, input_turn_id=tid,
        user_turns=(UserContext(turn_id=tid, content=TEXT),), questions=(), facts=(),
        stop=StopContext(round_count=1, consecutive_empty_rounds=0, user_stopped=False, session_ended=False))
    raw = MiningInput(tid, 'LEGACY_RAW_MUST_NEVER_BE_SENT', context)
    body = build_request(raw.context).body
    assert raw.content not in body.decode() and TEXT in body.decode()
    private = context.model_copy(update={'user_turns': (UserContext(turn_id=tid, content='x@example.com'),)})
    with pytest.raises(ValueError, match='offline_context_not_minimized'): build_request(private)
