"""Real PostgreSQL question-answer identity, history, recovery and compatibility."""
from uuid import UUID, uuid4
from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from test_mining import stack, request, aggregate, count, ROOT
from test_idempotency import headers
from test_http_api import api, create, patch
from app import facts, idempotency as idem
from app.models import AnswerQuestion, ConversationTurn, ExperienceFact, MiningQuestion, MiningReceipt, MiningRun, utcnow
from app.mining_api import Start


def initial(stack):
    client,_,_,_,_=stack
    url,h,body=request(stack)
    r=client.post(url,headers=h,json=body)
    assert r.status_code==201
    return r.json()


def action(stack,q,action,content=None):
    client,_,_,data,auth=stack
    body=dict(action=action,expected_version=q['version'],base_revision=aggregate(client,data,auth)['context_revision'])
    if content is not None: body['content']=content
    r=client.patch(ROOT+f'/sessions/{data["session_id"]}/mining-questions/{q["id"]}',headers=auth,json=body)
    assert r.status_code==200
    return r.json()


def test_two_questions_answer_one_skip_other_recovery_export_and_replay(stack):
    client,factory,provider,data,auth=stack
    first=initial(stack);q1,q2=first['questions']
    action(stack,q2,'skip')
    url,h,body=request(stack,'Synthetic personal answer to first question',answered_question_ids=[q1['id']])
    result=client.post(url,headers=h,json=body).json()
    expected=[{'question_id':q1['id'],'question_version':1}]
    assert result['answered_questions']==expected
    revision=aggregate(client,data,auth)['context_revision']
    for _ in range(2):
        assert client.post(url,headers=h,json=body).json()['answered_questions']==expected
        assert client.get(url+'/recovery',headers=h).json()['answered_questions']==expected
        assert client.get(url+'/'+result['id'],headers=auth).json()['answered_questions']==expected
    state=aggregate(client,data,auth)
    turn=next(t for t in state['turns'] if t['id']==result['input_turn_id'])
    assert turn['answered_questions']==expected and turn['content']==body['content']
    assert aggregate(client,data,auth)['context_revision']==revision and provider.calls==2
    exported=client.get(ROOT+f'/sessions/{data["session_id"]}/export',headers=auth).json()['data']
    assert next(t for t in exported['turns'] if t['id']==turn['id'])['answered_questions']==expected
    with factory() as db:
        links=list(db.scalars(select(AnswerQuestion)))
        assert len(links)==1 and links[0].turn_id==UUID(turn['id'])
        assert db.get(MiningQuestion,UUID(q2['id'])).state=='skipped'
    assert count(factory,AnswerQuestion)==1


def test_two_selected_questions_order_is_canonical_and_binding_is_idempotent(stack):
    client,factory,provider,data,auth=stack
    first=initial(stack);ids=[q['id'] for q in first['questions']]
    url,h,body=request(stack,'Synthetic answer to both questions',answered_question_ids=ids)
    result=client.post(url,headers=h,json=body).json()
    assert {v['question_id'] for v in result['answered_questions']}==set(ids)
    revision=aggregate(client,data,auth)['context_revision']
    assert client.post(url,headers=h,json={**body,'answered_question_ids':list(reversed(ids))}).json()['id']==result['id']
    for altered in ({**body,'answered_question_ids':[ids[0]]},{**body,'content':'Synthetic changed answer'}, {**body,'answered_question_ids':[]}):
        r=client.post(url,headers=h,json=altered)
        assert r.status_code==409 and r.json()['error']['code']=='idempotency_payload_mismatch'
    assert aggregate(client,data,auth)['context_revision']==revision and count(factory,AnswerQuestion)==2
    assert provider.calls==2


@pytest.mark.parametrize('state',['skip','hide','delete'])
def test_non_answerable_states_do_not_save_an_answer(stack,state):
    client,factory,provider,data,auth=stack
    q=initial(stack)['questions'][0]
    action(stack,q,state)
    before=count(factory,ConversationTurn)
    url,h,body=request(stack,'Synthetic answer after state change',answered_question_ids=[q['id']])
    r=client.post(url,headers=h,json=body)
    assert r.status_code==409 and r.json()['error']['code']=='mining_question_not_answerable'
    assert count(factory,AnswerQuestion)==0 and count(factory,ConversationTurn)==before and provider.calls==1


def test_corrected_question_version_and_later_deletion_preserve_confirmed_answer(stack):
    client,factory,provider,data,auth=stack
    original=provider.mine
    async def first_question(ctx):
        output=await original(ctx)
        output.questions=['Synthetic unique original question?', 'Synthetic second original question?']
        return output
    provider.mine=first_question
    q=initial(stack)['questions'][0];old_text=q['content']
    provider.mine=original
    url,h,old_body=request(stack,'Synthetic before correction',answered_question_ids=[q['id']])
    q=action(stack,q,'correct','Synthetic corrected question about own work?')
    assert client.post(url,headers=h,json=old_body).json()['error']['code']=='context_conflict'
    url,h,body=request(stack,'Synthetic answer to corrected question',answered_question_ids=[q['id']])
    result=client.post(url,headers=h,json=body).json()
    expected=[{'question_id':q['id'],'question_version':2}]
    assert result['answered_questions']==expected
    fact=next(f for f in aggregate(client,data,auth)['facts'] if f['ai_run_id']==result['id'])
    fact=patch(client,fact,auth,'confirm').json()
    q=action(stack,q,'correct','Synthetic later correction?')
    assert client.get(url+'/'+result['id'],headers=auth).json()['answered_questions']==expected
    action(stack,q,'delete')
    # Historical ID/version remains; the deleted question text is nowhere duplicated.
    assert client.post(url,headers=h,json=body).json()['answered_questions']==expected
    export=client.get(ROOT+f'/sessions/{data["session_id"]}/export',headers=auth).json()
    assert old_text not in str(export) and 'Synthetic corrected question about own work?' not in str(export)
    assert 'Synthetic later correction?' not in str(export)
    assert next(f for f in export['data']['facts'] if f['id']==fact['id'])['status']=='user_confirmed'
    assert next(t for t in export['data']['turns'] if t['id']==result['input_turn_id'])['answered_questions']==expected
    assert count(factory,AnswerQuestion)==1
    client.delete(ROOT+f'/sessions/{data["session_id"]}',headers=auth)
    assert count(factory,AnswerQuestion)==0


def test_unknown_retry_inherits_links_after_question_deletion_without_revision_bump(stack):
    client,factory,provider,data,auth=stack
    q=initial(stack)['questions'][0]
    original=provider.mine
    async def invalid(ctx): return {}
    provider.mine=invalid
    url,h,body=request(stack,'Synthetic durable failed answer',answered_question_ids=[q['id']])
    first=client.post(url,headers=h,json=body).json();assert first['state']=='failed'
    action(stack,q,'delete')
    provider.mine=original
    url,h,body=request(stack);body.pop('input_turn_id');body.update(retry_of=first['id'],confirm_retry=True)
    bad_h,_=headers('mining_run','session:'+data['session_id'],data['access_token'])
    bad=client.post(url,headers=bad_h,json={**body,'answered_question_ids':[]})
    assert bad.json()['error']['code']=='mining_retry_questions_changed'
    result=client.post(url,headers=h,json=body).json()
    assert result['answered_questions']==first['answered_questions']
    assert result['input_turn_id']==first['input_turn_id'] and result['reserved_revision']==body['base_revision']
    assert count(factory,AnswerQuestion)==1


@pytest.mark.parametrize('case',['cross_session','nonexistent','duplicate','three','old_round'])
def test_invalid_question_identity_permissions_and_round_scope(stack,case):
    client,factory,provider,data,auth=stack
    first=initial(stack);ids=[first['questions'][0]['id']]
    expected=422
    if case=='cross_session':
        other,other_auth=create(client)
        url=ROOT+f'/sessions/{other["session_id"]}/mining-runs'
        h,_=headers('mining_run','session:'+other['session_id'],other['access_token'])
        r=client.post(url,headers=h,json=dict(project_id=other['project_id'],base_revision=aggregate(client,other,other_auth)['context_revision'],input_turn_id=other['initial_turn_id']))
        ids=[r.json()['questions'][0]['id']];expected=404
    if case=='nonexistent': ids=[str(uuid4())];expected=404
    if case=='duplicate': ids=ids*2
    if case=='three': ids=ids*3
    if case=='old_round':
        url,h,b=request(stack,'Synthetic free supplementary round')
        assert client.post(url,headers=h,json=b).status_code==201
        expected=409
    before=count(factory,ConversationTurn)
    url,h,body=request(stack,'Synthetic invalid association',answered_question_ids=ids)
    r=client.post(url,headers=h,json=body)
    assert r.status_code==expected and count(factory,AnswerQuestion)==0
    assert count(factory,ConversationTurn)==before


def test_database_fk_user_guard_and_max_two_slots(stack):
    client,factory,provider,data,auth=stack
    q=initial(stack)['questions'][0]
    other,other_auth=create(client)
    with pytest.raises(IntegrityError),factory() as db,db.begin():
        db.add(AnswerQuestion(turn_id=UUID(other['initial_turn_id']),question_id=UUID(q['id']),session_id=UUID(data['session_id']),question_version=1,slot=1));db.flush()
    with factory() as db:
        assistant=db.scalars(select(ConversationTurn).where(ConversationTurn.role=='assistant')).first().id
    with pytest.raises(IntegrityError),factory() as db,db.begin():
        db.add(AnswerQuestion(turn_id=assistant,question_id=UUID(q['id']),session_id=UUID(data['session_id']),question_version=1,slot=1));db.flush()
    with pytest.raises(IntegrityError),factory() as db,db.begin():
        db.add(AnswerQuestion(turn_id=UUID(data['initial_turn_id']),question_id=UUID(q['id']),session_id=UUID(data['session_id']),question_version=1,slot=3));db.flush()


def test_0004_compatibility_old_receipt_and_0005_roundtrip(stack,migrated_connection):
    client,factory,provider,data,auth=stack
    # Receipt generated without the optional field uses the pre-review canonical body.
    url,h,body=request(stack,'Synthetic legacy 0004 submitted answer')
    first=client.post(url,headers=h,json=body).json()
    with factory() as db:
        receipt=db.scalar(select(MiningReceipt).where(MiningReceipt.run_id==UUID(first['id'])))
        old_payload=Start(**body).model_dump(mode='json');old_payload.pop('answered_question_ids')
        key=idem.parse(h['Idempotency-Key'],data['access_token'],'mining_run','session:'+data['session_id'])
        assert receipt.request_tag==idem.request_tag(key,data['access_token'],old_payload)
    connection,cfg=migrated_connection
    command.downgrade(cfg,'0004_ai_mining');command.upgrade(cfg,'head');command.check(cfg)
    assert client.post(url,headers=h,json=body).json()['id']==first['id']
    assert aggregate(client,data,auth)['turns'][0]['answered_questions']==[]
    assert count(factory,AnswerQuestion)==0


def test_concurrent_same_key_answer_links_commit_once(stack):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    client,factory,provider,data,auth=stack
    q=initial(stack)['questions'][0]
    entered,release=Event(),Event();original=provider.mine
    async def waiting(ctx):
        entered.set();await asyncio.to_thread(release.wait,5)
        return await original(ctx)
    provider.mine=waiting
    url,h,body=request(stack,'Synthetic concurrent linked answer',answered_question_ids=[q['id']])
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(client.post,url,headers=h,json=body);assert entered.wait(3)
        try:
            second=client.post(url,headers=h,json=body)
            assert second.status_code==202
            assert second.json()['answered_questions']==[{'question_id':q['id'],'question_version':1}]
            reserved_revision=aggregate(client,data,auth)['context_revision']
            assert count(factory,AnswerQuestion)==1
            assert client.get(url+'/recovery',headers=h).json()['reserved_revision']==reserved_revision
            assert aggregate(client,data,auth)['context_revision']==reserved_revision
        finally: release.set()
        assert first.result().json()['state']=='completed'
    assert provider.calls==2 and count(factory,AnswerQuestion)==1


def test_0005_rollback_keeps_answer_fact_and_question_data(stack,migrated_connection):
    client,factory,provider,data,auth=stack
    q=initial(stack)['questions'][0]
    url,h,body=request(stack,'Synthetic answer before rollback',answered_question_ids=[q['id']])
    # Deliberately discard the POST response: recovery requires no run ID.
    client.post(url,headers=h,json=body)
    recovered=client.get(url+'/recovery',headers=h).json()
    assert recovered['answered_questions']==[{'question_id':q['id'],'question_version':1}]
    turn_id=UUID(recovered['input_turn_id'])
    facts_before=count(factory,ExperienceFact)
    connection,cfg=migrated_connection
    command.downgrade(cfg,'0004_ai_mining')
    assert connection.scalar(text('SELECT content FROM conversation_turns WHERE id=:id'),{'id':turn_id})==body['content']
    assert connection.scalar(text('SELECT count(*) FROM experience_facts'))==facts_before
    assert connection.scalar(text('SELECT content FROM ai_mining_questions WHERE id=:id'),{'id':UUID(q['id'])})==q['content']
    connection.commit();command.upgrade(cfg,'head');command.check(cfg)
    # Downgrade removed only linkage; never infer/backfill relationships from ordering.
    assert client.get(url+'/recovery',headers=h).json()['answered_questions']==[]
