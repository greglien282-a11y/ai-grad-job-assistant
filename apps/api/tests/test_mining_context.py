"""Real PostgreSQL/HTTP v2 evaluations; synthetic data only, no network model."""
import asyncio
import json
from pathlib import Path
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from test_http_api import api, create, patch
from test_mining import stack, aggregate, request, count
from app import facts, mining, mining_context
from app.main import app
from app.mining_api import get_provider
from app.mining_context import within_budget
from app.mining_fake import ContextFakeProvider
from app.mining_provider import MiningOutputV2
from app.mining_validation import atomic
from app.models import ConversationTurn, ExperienceFact, MiningQuestion

ROOT = '/api/v1/experience'


class Capture(ContextFakeProvider):
    def __init__(self): self.inputs = []; self.override = None
    async def mine(self, context):
        self.inputs.append(context)
        output = (await super().mine(context)).model_dump(mode='json')
        return self.override(context, output) if self.override else output


@pytest.fixture
def v2(stack):
    client, factory, _, data, auth = stack
    provider = Capture()
    app.dependency_overrides[get_provider] = lambda: provider
    return client, factory, provider, data, auth


def post(stack, content, **extra):
    url, h, body = request(stack, content, **extra)
    response = stack[0].post(url, headers=h, json=body)
    assert response.status_code == 201
    return response.json(), (url, h, body)


CASES = json.loads((Path(__file__).parent/'fixtures/mining_multiturn.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_multiturn_synthetic_evaluation(v2, case):
    client, factory, provider, data, auth = v2
    question_ids = set()
    for text, expected in zip(case['turns'], case['facts']):
        run, _ = post(v2, text)
        assert run['state'] == 'completed'
        assert count(factory, ExperienceFact) == expected
        assert len(run['questions']) <= 2
        question_ids.update(q['id'] for q in run['questions'])
        snapshot = provider.inputs[-1].context
        assert snapshot.context_revision == run['reserved_revision']
        assert snapshot.input_turn_id == UUID(run['input_turn_id'])
        assert within_budget(snapshot)
    state = aggregate(client, data, auth)
    assert all(f['status'] == 'pending' and f['memory_state'] == 'unspecified' for f in state['facts'])
    assert len(provider.inputs[-1].context.user_turns) == len(case['turns']) + 1


@pytest.mark.parametrize('text,expected', [
    ('我实现了筛选。', True), ('我没有负责部署。', True),
    ('团队完成了演示。', False), ('我实现了筛选和分页。', False),
    ('我实现了筛选，我部署了服务。', False), ('我设计页面做测试。', False),
    ('我大概做了 2 页。', False), ('如果有时间我会部署。', False),
    ('我记不清技术细节。', False), ('我做了测试；团队做了部署。', False),
])
def test_atomic_boundary(text, expected): assert bool(atomic(text)) == expected


def test_links_skips_corrections_hidden_and_deleted_context(v2):
    client, factory, provider, data, auth = v2
    first, _ = post(v2, '合成：课程项目。')
    q1, q2 = first['questions']
    def action(q, operation, text=None):
        body = {'base_revision': aggregate(client,data,auth)['context_revision'], 'expected_version': q['version'], 'action': operation}
        if text: body['content'] = text
        r = client.patch(ROOT+f'/sessions/{data["session_id"]}/mining-questions/{q["id"]}', headers=auth, json=body)
        assert r.status_code == 200
        return r.json()
    action(q2, 'skip')
    second, _ = post(v2, '我实现了筛选。', answered_question_ids=[q1['id']])
    q1 = action(q1, 'correct', '合成纠正：你的具体贡献是什么？')
    q1 = action(q1, 'hide')
    action(q1, 'delete')
    post(v2, '我没有负责部署。')
    ctx = provider.inputs[-1].context
    old = next(q for q in ctx.questions if str(q.question_id) == q1['id'])
    assert old.state == 'deleted' and old.content is None and old.dedup_fingerprint is None
    assert old.answered_version == 1 and not old.answer_matches_current_version
    assert old.answered_turn_id == UUID(second['input_turn_id'])
    assert q1['content'] not in json.dumps(ctx.payload(), ensure_ascii=False)
    skipped = next(q for q in ctx.questions if str(q.question_id) == q2['id'])
    assert skipped.state == 'skipped' and skipped.answered_turn_id is None
    link = next(t for t in ctx.user_turns if str(t.turn_id) == second['input_turn_id']).answered_questions[0]
    assert str(link.question_id) == q1['id'] and link.question_version == 1


def test_current_fact_edits_memory_rejection_and_old_quote_non_resurrection(v2):
    client, factory, provider, data, auth = v2
    post(v2, '我实现了筛选。')
    fact = aggregate(client,data,auth)['facts'][0]
    fact = patch(client,fact,auth,'confirm').json()
    fact = patch(client,fact,auth,'edit',statement='合成 B：我负责空状态页面。').json()
    fact = patch(client,fact,auth,'set_memory',memory_state='approximate').json()
    post(v2, '我没有负责部署。')
    ctx = provider.inputs[-1].context
    current = next(f for f in ctx.facts if str(f.fact_id) == fact['id'])
    assert current.statement == fact['statement'] and current.status == 'pending'
    assert current.source_kind == 'user_edit' and current.memory_state == 'approximate'
    fact = patch(client,fact,auth,'reject').json()
    original = provider.inputs[0].context.user_turns[0]
    def old_quote(context, output):
        output['candidates'] = [{'citation': {'turn_id': str(original.turn_id), 'quote': original.content, 'start': 0, 'end': len(original.content)}}]
        return output
    provider.override = old_quote
    run, _ = post(v2, '合成：用户又补充了一些背景。')
    assert run['state'] == 'completed' and count(factory, ExperienceFact) == 2
    rejected = next(f for f in provider.inputs[-1].context.facts if str(f.fact_id) == fact['id'])
    assert rejected.status == 'rejected' and rejected.statement is None


@pytest.mark.parametrize('tamper', ['assistant', 'cross_session', 'utf16', 'partial_negation', 'invented_number', 'status', 'three_questions', 'repeated_question', 'repeated_candidate', 'private', 'question_number'])
def test_v2_output_rejection_is_atomic(v2, tamper):
    client, factory, provider, data, auth = v2
    other, _ = create(client)
    def bad(context, output):
        c = output['candidates'][0]['citation']
        if tamper == 'assistant':
            with factory() as db, db.begin():
                t = ConversationTurn(session_id=UUID(data['session_id']), role='assistant', content=context.content)
                db.add(t);db.flush();c['turn_id'] = str(t.id)
        if tamper == 'cross_session': c['turn_id'] = other['initial_turn_id']
        if tamper == 'utf16': c['end'] = len(context.content.encode('utf-16-le'))//2
        if tamper == 'partial_negation': c.update(quote='负责部署', start=context.content.index('负责部署'), end=context.content.index('负责部署')+4)
        if tamper == 'invented_number': c['quote'] = '我独立完成部署提高 80%。'
        if tamper == 'status': output['candidates'][0]['status'] = 'user_confirmed'
        if tamper == 'three_questions': output['questions'] *= 2
        if tamper == 'repeated_question': output['questions'][1] = output['questions'][0]
        if tamper == 'repeated_candidate': output['candidates'] *= 2
        if tamper == 'private': output['questions'][0]['text'] = '联系 synthetic@example.invalid？'
        if tamper == 'question_number': output['questions'][0]['text'] = '你提升了 80% 吗？'
        return output
    provider.override = bad
    run, _ = post(v2, '我没有负责部署 🚀。')
    # Assistant insertion itself legitimately invalidates context first.
    assert run['state'] == ('stale' if tamper == 'assistant' else 'failed')
    assert count(factory, ExperienceFact) == 0 and count(factory, MiningQuestion) == 0


def test_context_budget_redaction_omissions_and_trimmed_source_rejection(v2):
    client, factory, provider, data, auth = v2
    with factory() as db, db.begin():
        for n in range(12): facts.add_turn(db, UUID(data['session_id']), data['access_token'], f'我实现了第 {n} 个页面。')
        for n in range(36): facts.add_fact(db, UUID(data['project_id']), data['access_token'], f'合成 {n}：'+'资料'*1500, [UUID(data['initial_turn_id'])])
    run, _ = post(v2, '我负责页面。synthetic@example.invalid 13800000000')
    ctx = provider.inputs[-1].context
    wire = json.dumps(ctx.payload(), ensure_ascii=False)
    assert 'synthetic@example.invalid' not in wire and '13800000000' not in wire
    assert 'synthetic@example.invalid' not in provider.inputs[-1].content
    assert '█' in wire and within_budget(ctx)
    assert len(ctx.user_turns) <= 8 and ctx.omitted_turns >= 6 and ctx.omitted_facts > 0
    assert str(data['initial_turn_id']) not in {str(t.turn_id) for t in ctx.user_turns}
    assert data['access_token'] not in wire
    def omitted(context, output):
        output['candidates'] = [{'citation': {'turn_id': data['initial_turn_id'], 'quote': 'Synthetic course project', 'start': 0, 'end': 24}}]
        return output
    provider.override = omitted
    run, _ = post(v2, '我制作了另一个页面。')
    assert run['state'] == 'failed' and count(factory, ExperienceFact) == 37


def test_failed_context_can_retry_without_duplicate_answer(v2, monkeypatch):
    client, factory, provider, data, auth = v2
    with monkeypatch.context() as m:
        m.setattr(mining_context, 'MAX_BYTES', 100)
        run, _ = post(v2, '我实现了筛选。')
    assert run['state'] == 'failed' and run['error_code'] == 'mining_context_invalid'
    assert provider.inputs == []
    url, h, body = request(v2, retry_of=run['id'], confirm_retry=True)
    body.pop('input_turn_id', None)
    retry = client.post(url,headers=h,json=body).json()
    assert retry['state'] == 'completed'
    assert len([t for t in aggregate(client,data,auth)['turns'] if t['role']=='user']) == 2


def test_v2_replay_and_read_recovery_never_reinvoke(v2):
    client, factory, provider, data, auth = v2
    run, (url, h, body) = post(v2, '我实现了筛选。')
    revision = aggregate(client,data,auth)['context_revision']
    assert client.post(url,headers=h,json=body).status_code == 200
    assert client.get(url+'/recovery',headers=h).json()['id'] == run['id']
    assert len(provider.inputs) == 1 and aggregate(client,data,auth)['context_revision'] == revision
    different = {**body, 'content':'我实现了分页。'}
    assert client.post(url,headers=h,json=different).json()['error']['code'] == 'idempotency_payload_mismatch'


def test_v2_late_worker_cannot_publish_after_user_write(v2):
    client, factory, provider, data, auth = v2
    def mutate(context, output):
        with factory() as db, db.begin(): facts.add_turn(db,UUID(data['session_id']),data['access_token'],'合成：并发新资料。')
        return output
    provider.override = mutate
    run, _ = post(v2, '我实现了筛选。')
    assert run['state'] == 'stale' and count(factory, ExperienceFact) == 0


def test_output_schema_and_stop_contract():
    with pytest.raises(ValueError): MiningOutputV2(candidates=[], questions=[], stop=False)
    with pytest.raises(ValueError): MiningOutputV2(candidates=[], questions=[], stop=True)
    assert MiningOutputV2(candidates=[], questions=[], stop=True, stop_reason='user_uncertain').stop


def test_corrected_question_version_is_not_the_original_answer(v2):
    client, factory, provider, data, auth = v2
    first, _ = post(v2, '合成：课程项目。')
    q = first['questions'][0]
    second, _ = post(v2, '我实现了筛选。', answered_question_ids=[q['id']])
    changed = client.patch(ROOT+f'/sessions/{data["session_id"]}/mining-questions/{q["id"]}', headers=auth,
        json={'action':'correct', 'content':'合成纠正后的问题：哪个页面是你做的？', 'expected_version':1,
              'base_revision':aggregate(client,data,auth)['context_revision']})
    assert changed.status_code == 200
    post(v2, '我没有负责部署。')
    question = next(item for item in provider.inputs[-1].context.questions if str(item.question_id) == q['id'])
    assert question.version == 2 and question.answered_version == 1 and not question.answer_matches_current_version
    assert question.content == changed.json()['content']


def test_hidden_text_is_not_sent_and_question_is_not_reasked(v2):
    client, factory, provider, data, auth = v2
    first, _ = post(v2, '合成：课程项目。')
    q = first['questions'][0]
    result = client.patch(ROOT+f'/sessions/{data["session_id"]}/mining-questions/{q["id"]}', headers=auth,
        json={'action':'hide', 'expected_version':1, 'base_revision':aggregate(client,data,auth)['context_revision']})
    assert result.status_code == 200
    second, _ = post(v2, '我实现了筛选。')
    ctx = provider.inputs[-1].context
    hidden = next(item for item in ctx.questions if str(item.question_id) == q['id'])
    assert hidden.state == 'hidden' and hidden.content is None and hidden.dedup_fingerprint
    assert q['content'] not in json.dumps(ctx.payload(), ensure_ascii=False)
    assert q['content'] not in [item['content'] for item in second['questions']]


def test_v2_cancellation_recovery_and_explicit_retry(v2):
    client, factory, provider, data, auth = v2
    original = provider.mine
    async def cancelled(context):
        provider.inputs.append(context)
        raise asyncio.CancelledError()
    provider.mine = cancelled
    run, (url,h,body) = post(v2, '我实现了筛选。')
    assert run['state'] == 'unknown'
    revision = aggregate(client,data,auth)['context_revision']
    assert client.get(url+'/recovery',headers=h).json()['state'] == 'unknown'
    assert len(provider.inputs) == 1 and aggregate(client,data,auth)['context_revision'] == revision
    provider.mine = original
    url,h,body = request(v2,retry_of=run['id'],confirm_retry=True)
    body.pop('input_turn_id',None)
    retried = client.post(url,headers=h,json=body).json()
    assert retried['state'] == 'completed' and retried['input_turn_id'] == run['input_turn_id']
    assert len([t for t in aggregate(client,data,auth)['turns'] if t['role']=='user']) == 2


def test_concurrent_same_key_v2_runs_only_once(v2):
    client, factory, provider, data, auth = v2
    entered, release = Event(), Event()
    original = provider.mine
    async def blocked(context):
        entered.set(); await asyncio.to_thread(release.wait,5)
        return await original(context)
    provider.mine = blocked
    url,h,body = request(v2,'我实现了筛选。')
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(client.post,url,headers=h,json=body)
        assert entered.wait(3)
        try:
            replay = client.post(url,headers=h,json=body)
            assert replay.status_code == 202 and replay.json()['state'] == 'running'
        finally: release.set()
        assert future.result().json()['state'] == 'completed'
    assert len(provider.inputs) == 1 and count(factory,ExperienceFact) == 1


def test_exact_duplicate_answer_does_not_create_new_context(v2):
    client, factory, provider, data, auth = v2
    post(v2,'我实现了筛选。')
    url,h,body = request(v2,'我实现了筛选。')
    assert client.post(url,headers=h,json=body).json()['error']['code'] == 'mining_input_already_submitted'
    assert len(provider.inputs) == 1 and count(factory,ExperienceFact) == 1


def test_fragment_keeps_full_negative_sentence_and_emoji_offsets(v2):
    client, factory, provider, data, auth = v2
    text = '我实现了 🚀 筛选。\n我没有负责部署。'
    run,_ = post(v2,text)
    state = aggregate(client,data,auth)
    assert run['state'] == 'completed' and len(state['facts']) == 2
    for fact in state['facts']:
        c = fact['citations'][0]
        assert text[c['start']:c['end']] == c['quote'] == fact['statement']
    assert any(f['statement'] == '我没有负责部署。' for f in state['facts'])


@pytest.mark.parametrize('during',['end','stop','delete'])
def test_v2_snapshot_cannot_publish_after_management(v2, during):
    client, factory, provider, data, auth = v2
    entered, release = Event(), Event()
    original = provider.mine
    async def blocked(context):
        entered.set();await asyncio.to_thread(release.wait,5)
        return await original(context)
    provider.mine = blocked
    url,h,body = request(v2,'我实现了筛选。')
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(client.post,url,headers=h,json=body)
        assert entered.wait(3)
        try:
            endpoint = ROOT+f'/sessions/{data["session_id"]}'
            if during=='end': assert client.post(endpoint+'/end',headers=auth).status_code==200
            if during=='stop': assert client.post(endpoint+'/mining-stop',headers=auth,json={'base_revision':aggregate(client,data,auth)['context_revision']}).status_code==200
            if during=='delete': assert client.delete(endpoint,headers=auth).status_code==204
        finally: release.set()
        result = future.result()
    if during=='delete': assert result.status_code==404
    else: assert result.json()['state']=='stale'
    assert count(factory,ExperienceFact)==0


@pytest.mark.parametrize('state',['active','skipped','hidden','corrected'])
def test_prior_question_duplicate_rejected_across_states(v2,state):
    client, factory, provider, data, auth = v2
    first,_ = post(v2,'合成：课程项目。')
    q = first['questions'][0]
    if state!='active':
        with factory() as db,db.begin():
            row=db.get(MiningQuestion,UUID(q['id']));row.state=state;row.version+=1
            if state=='corrected': row.content='合成纠正后的问题是什么？'
            question=row.content
    else: question=q['content']
    def repeat(context,output):
        output['questions']=[{'text':'  '+question+'  ', 'purpose':'contribution', 'source_turn_ids':[str(context.turn_id)]}]
        return output
    provider.override=repeat
    run,_=post(v2,'我实现了筛选。')
    assert run['state']=='failed' and count(factory,ExperienceFact)==0


def test_v2_provider_cannot_downgrade_to_legacy_output(v2):
    provider=v2[2]
    provider.override=lambda context,output: {'candidates':[], 'questions':['Synthetic legacy downgrade?']}
    run,_=post(v2,'我实现了筛选。')
    assert run['state']=='failed' and count(v2[1],ExperienceFact)==0


def test_legal_unused_historical_user_turn_can_support_candidate(v2):
    client,factory,provider,data,auth=v2
    text='我实现了历史列表。'
    with factory() as db,db.begin():
        turn=facts.add_turn(db,UUID(data['session_id']),data['access_token'],text)
        tid=str(turn.id)
    def historical(context,output):
        assert tid in {str(t.turn_id) for t in context.context.user_turns}
        output['candidates']=[{'citation':{'turn_id':tid,'quote':text,'start':0,'end':len(text)}}]
        return output
    provider.override=historical
    run,_=post(v2,'我负责演示页面。')
    assert run['state']=='completed'
    fact=aggregate(client,data,auth)['facts'][0]
    assert fact['statement']==text and fact['source_turn_ids']==[tid] and fact['status']=='pending'


def test_generated_contract_schemas_match_models():
    from app.mining_context import MiningContext
    root=Path(__file__).resolve().parents[3]/'docs/contracts'
    for name,model in [('mining-input-v2',MiningContext),('mining-output-v2',MiningOutputV2)]:
        assert json.loads((root/(name+'.schema.json')).read_text(encoding='utf-8'))==model.model_json_schema()
