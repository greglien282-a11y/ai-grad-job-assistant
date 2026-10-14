"""Synthetic HTTP/provider and independent PostgreSQL tests. No network models."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from test_http_api import api, create, patch
from test_idempotency import headers
from app import facts, mining
from app.main import app
from app.mining_api import Start, get_mining_factory, get_provider
from app.mining_provider import ScriptedProvider, CostReservation
from app.models import ConversationTurn, ExperienceFact, ExperienceProject, ExperienceSession, FactChange, FactSource, MiningQuestion, MiningReceipt, MiningRun, utcnow

ROOT = '/api/v1/experience'


class CountingProvider(ScriptedProvider):
    def __init__(self): self.calls = 0
    async def mine(self, context):
        self.calls += 1
        return await super().mine(context)


@pytest.fixture
def stack(api):
    client, factory = api
    provider = CountingProvider()
    app.dependency_overrides[get_mining_factory] = lambda: factory
    app.dependency_overrides[get_provider] = lambda: provider
    data, auth = create(client)
    return client, factory, provider, data, auth


def aggregate(client, data, auth):
    return client.get(ROOT+f'/sessions/{data["session_id"]}', headers=auth).json()


def request(stack, content=None, **extra):
    client, _, _, data, auth = stack
    body = dict(project_id=data['project_id'], base_revision=aggregate(client,data,auth)['context_revision'])
    body.update({'content':content} if content is not None else {'input_turn_id':data['initial_turn_id']})
    body.update(extra)
    h, _ = headers('mining_run','session:'+data['session_id'], data['access_token'])
    return ROOT+f'/sessions/{data["session_id"]}/mining-runs', h, body


def count(factory, model):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_default_disabled_and_unapproved_budget(stack, monkeypatch):
    client,factory,provider,data,auth=stack
    app.dependency_overrides.pop(get_provider)
    monkeypatch.delenv('AI_ENABLED',raising=False)
    url,h,body=request(stack, 'Synthetic zero writes')
    assert client.post(url,headers=h,json=body).json()['error']['code']=='ai_disabled'
    monkeypatch.setenv('AI_ENABLED','true'); monkeypatch.setenv('AI_PROVIDER','unapproved-paid')
    assert client.post(url,headers=h,json=body).json()['error']['code']=='ai_provider_unapproved'
    app.dependency_overrides[get_provider]=lambda: provider
    provider.reserve_cost=lambda: CostReservation('unknown',1)
    assert client.post(url,headers=h,json=body).json()['error']['code']=='ai_provider_unapproved'
    assert count(factory,MiningRun)==0 and count(factory,ConversationTurn)==1


def test_unicode_full_quote_confirmation_edit_summary_export(stack):
    client,factory,provider,data,auth=stack
    content='合成：团队完成演示 🚀，我大概做了 2 个页面，没有负责部署；如果再做一次会先测试。'
    url,h,body=request(stack, content)
    base=body['base_revision']
    result=client.post(url,headers=h,json=body)
    assert result.status_code==201
    run=result.json(); assert run['state']=='completed' and run['reserved_revision']==base+2
    state=aggregate(client,data,auth); fact=state['facts'][0]
    assert fact['statement']==content and fact['status']=='pending' and fact['origin']=='ai_extracted'
    assert fact['memory_state']=='unspecified' and fact['citations'][0]['end']==len(content)
    assert state['context_revision']>run['reserved_revision']
    summary=ROOT+f'/projects/{data["project_id"]}/experience-summary'
    assert client.get(summary,headers=auth).json()['text']==''
    fact=patch(client,fact,auth,'set_memory',memory_state='approximate').json()
    assert fact['status']=='pending'
    fact=patch(client,fact,auth,'confirm').json()
    assert client.get(summary,headers=auth).json()['text']==content
    fact=patch(client,fact,auth,'edit',statement='Synthetic B: I built the test screen.').json()
    assert fact['status']=='pending' and fact['citations']==[]
    fact=patch(client,fact,auth,'confirm').json()
    assert fact['source_kind']=='user_edit' and fact['source_turn_ids']==[]
    assert client.get(summary,headers=auth).json()['text']==fact['statement']
    exported=client.get(ROOT+f'/sessions/{data["session_id"]}/export',headers=auth).json()
    assert exported['data']['mining_runs'][0]['synthetic']
    leaked=data['access_token'] in str(exported) or h['Idempotency-Key'] in str(exported)
    assert not leaked
    with factory() as db:
        source=db.scalar(select(FactSource).where(FactSource.fact_id==UUID(fact['id'])))
        assert source.citations[0]['quote']==content
        assert db.scalar(select(func.count()).select_from(FactChange))==5


def test_replay_recovery_no_revision_or_calls_and_payload_conflict(stack):
    client,factory,provider,data,auth=stack
    url,h,body=request(stack,'Synthetic own answer')
    missing=client.get(url+'/recovery',headers=h)
    assert missing.status_code==404 and count(factory,ConversationTurn)==1
    first=client.post(url,headers=h,json=body).json()
    revision=aggregate(client,data,auth)['context_revision']
    # Discarded POST response can be recovered by key without knowing run ID.
    for _ in range(2):
        assert client.get(url+'/recovery',headers=h).json()['id']==first['id']
        assert client.post(url,headers=h,json=body).json()['id']==first['id']
    assert aggregate(client,data,auth)['context_revision']==revision and provider.calls==1
    assert count(factory,ConversationTurn)==3
    conflict=client.post(url,headers=h,json={**body,'content':'Synthetic different answer'})
    assert conflict.status_code==409 and conflict.json()['error']['code']=='idempotency_payload_mismatch'
    bad={**h,'Authorization':'Bearer '+'x'*43}
    assert client.get(url+'/recovery',headers=bad).status_code==401
    # New key referencing a known submitted input cannot silently write a second answer.
    url2,h2,b2=request(stack,input_turn_id=first['input_turn_id'])
    assert client.post(url2,headers=h2,json=b2).json()['error']['code']=='mining_input_already_submitted'


@pytest.mark.parametrize('tamper', ['cross_session','assistant','fragment','utf16','number','hypothesis','extra_status','three_questions','empty','negative_offset'])
def test_invalid_sources_semantics_and_outputs_fail_closed(stack,tamper):
    client,factory,provider,data,auth=stack
    other,_=create(client)
    url,h,body=request(stack,'合成 🚀 团队大概完成了 2 页；我没有部署，如果部署会先测试。')
    original=provider.mine
    async def invalid(ctx):
        output=(await original(ctx)).model_dump(mode='json')
        c=output['candidates'][0]['citation']
        if tamper=='cross_session': c['turn_id']=other['initial_turn_id']
        if tamper=='assistant':
            with factory() as db,db.begin():
                t=ConversationTurn(session_id=UUID(other['session_id']),role='assistant',content=ctx.content)
                db.add(t);db.flush();c['turn_id']=str(t.id)
        if tamper=='fragment': c.update(quote='部署',start=ctx.content.index('部署'),end=ctx.content.index('部署')+2)
        if tamper=='utf16': c['end']=len(ctx.content.encode('utf-16-le'))//2
        if tamper=='number': c['quote']=ctx.content.replace('2','20')
        if tamper=='hypothesis': c['quote']='我独立主导部署并提升性能 80%'
        if tamper=='extra_status': output['candidates'][0]['status']='user_confirmed'
        if tamper=='three_questions': output['questions']=['A?','B?','C?']
        if tamper=='empty': return {}
        if tamper=='negative_offset': c['start']=-1
        return output
    provider.mine=invalid
    result=client.post(url,headers=h,json=body).json()
    assert result['state']=='failed' and result['error_code']=='provider_output_invalid'
    assert count(factory,ExperienceFact)==0 and count(factory,MiningQuestion)==0
    assert provider.calls==1
    assert len([t for t in aggregate(client,data,auth)['turns'] if t['role']=='user'])==2


def test_one_project_db_constraint_and_assistant_source(stack):
    client,factory,provider,data,auth=stack
    with pytest.raises(IntegrityError),factory() as db,db.begin():
        db.add(ExperienceProject(session_id=UUID(data['session_id']),raw_input='Synthetic other project'));db.flush()
    with factory() as db,db.begin():
        t=ConversationTurn(session_id=UUID(data['session_id']),role='assistant',content='Synthetic unsupported response')
        db.add(t);db.flush();tid=t.id
    response=client.post(ROOT+f'/projects/{data["project_id"]}/facts',headers=auth,
        json={'statement':'Synthetic guess','source_turn_ids':[str(tid)]})
    assert response.status_code==422
    with pytest.raises(IntegrityError),factory() as db,db.begin():
        fact=ExperienceFact(session_id=UUID(data['session_id']),project_id=UUID(data['project_id']),statement='Synthetic guess')
        db.add(fact);db.flush()
        db.add(FactSource(fact_id=fact.id,turn_id=tid,session_id=fact.session_id));db.flush()


def test_question_delete_scrubs_single_text_location(stack):
    client,factory,provider,data,auth=stack
    url,h,body=request(stack)
    run=client.post(url,headers=h,json=body).json()
    q=run['questions'][0]; original=q['content']
    fact=aggregate(client,data,auth)['facts'][0]
    patch(client,fact,auth,'confirm')
    endpoint=ROOT+f'/sessions/{data["session_id"]}/mining-questions/{q["id"]}'
    for action in ('skip','hide','correct','delete'):
        payload=dict(action=action,expected_version=q['version'],base_revision=aggregate(client,data,auth)['context_revision'])
        if action=='correct': payload['content']='Synthetic corrected question?'
        q=client.patch(endpoint,headers=auth,json=payload).json()
    assert q['content'] is None and q['state']=='deleted'
    export=client.get(ROOT+f'/sessions/{data["session_id"]}/export',headers=auth).json()
    assert original not in str(export) and 'Synthetic corrected question?' not in str(export)
    with factory() as db:
        assert db.get(MiningQuestion,UUID(q['id'])).content is None
        assert all(original not in t.content for t in db.scalars(select(ConversationTurn)))
        assert count(factory,ExperienceFact)==1
        assert db.scalar(select(ExperienceFact.status))=='user_confirmed'
    assert client.patch(endpoint,headers=auth,json={**payload,'base_revision':aggregate(client,data,auth)['context_revision'],'expected_version':q['version']}).status_code==410


def test_timeout_expired_lease_readonly_and_explicit_retry(stack,monkeypatch):
    client,factory,provider,data,auth=stack
    monkeypatch.setattr(mining,'CALL_TIMEOUT_SECONDS',.01)
    async def slow(ctx):
        provider.calls+=1
        await asyncio.sleep(1)
    original=provider.mine; provider.mine=slow
    url,h,body=request(stack,'Synthetic persisted answer')
    first=client.post(url,headers=h,json=body).json()
    assert first['state']=='unknown'
    assert client.get(url+'/recovery',headers=h).json()['state']=='unknown'
    assert provider.calls==1
    provider.mine=original
    url2,h2,b2=request(stack)
    b2.pop('input_turn_id');b2.update(retry_of=first['id'],confirm_retry=True)
    second=client.post(url2,headers=h2,json=b2).json()
    assert second['state']=='completed' and second['input_turn_id']==first['input_turn_id']
    assert count(factory,ConversationTurn)==3 and provider.calls==2
    assert second['reserved_revision']==second['base_revision']


@pytest.mark.parametrize('state',['reserved','running'])
def test_crashed_run_lease_projection_reclaim_and_late_worker(stack,state):
    client,factory,provider,data,auth=stack
    url,h,body=request(stack,'Synthetic crash saved answer')
    key=__import__('app.idempotency',fromlist=['parse']).parse(h['Idempotency-Key'],data['access_token'],'mining_run','session:'+data['session_id'])
    rid,fresh=mining.reserve(factory,UUID(data['session_id']),data['access_token'],key,Start(**body))
    with factory() as db,db.begin():
        r=db.get(MiningRun,rid);r.state=state;r.lease_until=utcnow()-timedelta(seconds=1)
    before=aggregate(client,data,auth)['context_revision']
    for _ in range(3): assert client.get(url+'/recovery',headers=h).json()['state']=='unknown'
    with factory() as db: assert db.get(MiningRun,rid).state==state
    assert provider.calls==0 and aggregate(client,data,auth)['context_revision']==before
    url2,h2,b2=request(stack);b2.pop('input_turn_id');b2.update(retry_of=str(rid),confirm_retry=True)
    result=client.post(url2,headers=h2,json=b2).json()
    assert result['state']=='completed'
    with factory() as db: assert str(db.get(MiningRun,rid).input_turn_id)==result['input_turn_id']
    with factory() as db: assert db.get(MiningRun,rid).state=='unknown'
    mining.complete(factory,UUID(data['session_id']),data['access_token'],rid,{})
    assert count(factory,ExperienceFact)==1


@pytest.mark.parametrize('during',['old_turn','end','stop','delete'])
def test_concurrent_changes_fence_provider_and_delete_never_revives(stack,during):
    client,factory,provider,data,auth=stack
    entered,release=Event(),Event()
    original=provider.mine
    async def blocked(ctx):
        entered.set(); await asyncio.to_thread(release.wait,5)
        return await original(ctx)
    provider.mine=blocked
    url,h,body=request(stack,'Synthetic delayed answer')
    with ThreadPoolExecutor(2) as pool:
        future=pool.submit(client.post,url,headers=h,json=body)
        assert entered.wait(3)
        try:
            if during=='old_turn': assert client.post(ROOT+f'/sessions/{data["session_id"]}/turns',headers=auth,json={'content':'Synthetic later context'}).status_code==201
            if during=='end': assert client.post(ROOT+f'/sessions/{data["session_id"]}/end',headers=auth).status_code==200
            if during=='stop': assert client.post(ROOT+f'/sessions/{data["session_id"]}/mining-stop',headers=auth,json={'base_revision':aggregate(client,data,auth)['context_revision']}).status_code==200
            if during=='delete': assert client.delete(ROOT+f'/sessions/{data["session_id"]}',headers=auth).status_code==204
        finally: release.set()
        result=future.result()
    if during=='delete':
        assert result.status_code==404
        assert count(factory,MiningRun)==count(factory,ExperienceFact)==count(factory,ConversationTurn)==0
        with factory() as db:
            receipt=db.scalar(select(MiningReceipt));assert receipt.state=='deleted'
            assert receipt.session_id is receipt.run_id is receipt.request_tag is None
        assert client.get(url+'/recovery',headers=h).status_code==404
        assert client.post(url,headers=h,json=body).status_code==404
    else:
        assert result.json()['state']=='stale' and count(factory,ExperienceFact)==0


def test_concurrent_same_key_one_call_and_different_keys_busy(stack):
    client,factory,provider,data,auth=stack
    entered,release=Event(),Event(); original=provider.mine
    async def blocked(ctx):
        entered.set(); await asyncio.to_thread(release.wait,5);return await original(ctx)
    provider.mine=blocked
    url,h,body=request(stack,'Synthetic concurrent answer')
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(client.post,url,headers=h,json=body);assert entered.wait(3)
        try:
            replay=client.post(url,headers=h,json=body)
            assert replay.status_code==202 and replay.json()['state']=='running'
            h2,_=headers('mining_run','session:'+data['session_id'],data['access_token'])
            body2={**body,'base_revision':aggregate(client,data,auth)['context_revision']}
            assert client.post(url,headers=h2,json=body2).json()['error']['code']=='mining_busy'
        finally: release.set()
        assert first.result().json()['state']=='completed'
    assert count(factory,MiningRun)==1 and provider.calls==1 and count(factory,ConversationTurn)==3


def test_0003_upgrade_legacy_data_and_rollback(migrated_connection):
    connection,cfg=migrated_connection
    command.downgrade(cfg,'0003_idempotency')
    sid,pid,tid,fid=[uuid4() for _ in range(4)]
    connection.execute(text("INSERT INTO experience_sessions(id,created_at,access_token_hash,status,updated_at) VALUES (:id,now(),'synthetic','active',now())"),{'id':sid})
    connection.execute(text("INSERT INTO experience_projects(id,created_at,session_id,raw_input) VALUES (:id,now(),:sid,'Synthetic old input')"),{'id':pid,'sid':sid})
    connection.execute(text("INSERT INTO conversation_turns(id,created_at,session_id,role,content) VALUES (:id,now(),:sid,'user','Synthetic old input')"),{'id':tid,'sid':sid})
    connection.execute(text("INSERT INTO experience_facts(id,created_at,project_id,session_id,statement,status,updated_at,version) VALUES (:id,now(),:pid,:sid,'Synthetic confirmed old','user_confirmed',now(),2)"),{'id':fid,'pid':pid,'sid':sid})
    connection.execute(text('INSERT INTO fact_sources(fact_id,turn_id,session_id) VALUES (:fid,:tid,:sid)'),{'fid':fid,'tid':tid,'sid':sid})
    connection.commit(); command.upgrade(cfg,'head'); command.check(cfg)
    row=connection.execute(text('SELECT statement,status,version,origin,memory_state FROM experience_facts WHERE id=:id'),{'id':fid}).one()
    assert tuple(row)==('Synthetic confirmed old','user_confirmed',2,'manual','unspecified')
    connection.commit(); command.downgrade(cfg,'0003_idempotency')
    assert connection.scalar(text('SELECT count(*) FROM experience_facts'))==1
    connection.commit();command.upgrade(cfg,'head');command.check(cfg)


def test_old_writes_increment_context_but_replays_and_gets_do_not(stack):
    client,factory,provider,data,auth=stack
    def rev(): return aggregate(client,data,auth)['context_revision']
    initial=rev()
    h,_=headers('add_turn','session:'+data['session_id'],data['access_token'])
    url=ROOT+f'/sessions/{data["session_id"]}/turns'
    t=client.post(url,headers=h,json={'content':'Synthetic supplementary source'}).json()
    assert rev()==initial+1
    client.post(url,headers=h,json={'content':'Synthetic supplementary source'})
    assert rev()==initial+1
    h,_=headers('add_fact','project:'+data['project_id'],data['access_token'])
    url=ROOT+f'/projects/{data["project_id"]}/facts'
    body={'statement':'Synthetic A','source_turn_ids':[t['id']]}
    fact=client.post(url,headers=h,json=body).json(); assert rev()==initial+2
    client.post(url,headers=h,json=body); assert rev()==initial+2
    before=rev();fact=patch(client,fact,auth,'confirm').json();assert rev()==before+1
    before=rev();fact=patch(client,fact,auth,'verify_material',material_reference='synthetic:2',basis='User checked report').json();assert rev()==before+2
    before=rev();fact=patch(client,fact,auth,'edit',statement='Synthetic B').json();assert rev()==before+1
    before=rev();patch(client,fact,auth,'reject');assert rev()==before+1
    client.post(ROOT+f'/sessions/{data["session_id"]}/end',headers=auth);before=rev()
    client.post(ROOT+f'/sessions/{data["session_id"]}/end',headers=auth);assert rev()==before


def test_no_silent_new_key_after_unknown_and_retry_contract(stack):
    client,factory,provider,data,auth=stack
    async def fail(ctx): raise RuntimeError('Synthetic private failure')
    provider.mine=fail
    url,h,body=request(stack,'Synthetic uncertain saved answer')
    r=client.post(url,headers=h,json=body).json();assert r['state']=='unknown'
    url2,h2,b2=request(stack,'Synthetic uncertain saved answer')
    assert client.get(url2+'/recovery',headers=h2).status_code==404
    assert client.post(url2,headers=h2,json=b2).json()['error']['code']=='mining_retry_requires_confirmation'
    assert count(factory,ConversationTurn)==2
    b2.pop('content');b2.update(retry_of=r['id'])
    assert client.post(url2,headers=h2,json=b2).status_code==422


def test_completed_response_loss_cannot_be_hidden_with_new_key(stack):
    client,factory,provider,data,auth=stack
    url,h,body=request(stack,'Synthetic saved once')
    assert client.post(url,headers=h,json=body).json()['state']=='completed'
    url2,h2,b2=request(stack,'Synthetic saved once')
    assert client.post(url2,headers=h2,json=b2).json()['error']['code']=='mining_input_already_submitted'
    assert provider.calls==1 and count(factory,ConversationTurn)==3


def test_provider_partial_storage_failure_rolls_back_result_only(stack,monkeypatch,caplog):
    client,factory,provider,data,auth=stack
    original=facts.record_change
    def partial(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('Synthetic private model text and key must not escape')
    monkeypatch.setattr(facts,'record_change',partial)
    url,h,body=request(stack,'Synthetic durable answer')
    result=client.post(url,headers=h,json=body)
    assert result.json()['state']=='unknown'
    assert count(factory,ExperienceFact)==count(factory,FactSource)==count(factory,FactChange)==count(factory,MiningQuestion)==0
    assert count(factory,ConversationTurn)==2
    leaked=data['access_token'] in caplog.text or 'Synthetic private model text' in caplog.text
    assert not leaked


def test_request_cancellation_marks_unknown_and_no_duplicate_answer(stack):
    client,factory,provider,data,auth=stack
    from app import idempotency as idem
    url,h,body=request(stack,'Synthetic cancelled answer')
    sid=UUID(data['session_id']);token=data['access_token']
    key=idem.parse(h['Idempotency-Key'],token,'mining_run','session:'+str(sid))
    rid,_=mining.reserve(factory,sid,token,key,Start(**body))
    async def scenario():
        entered=asyncio.Event()
        async def wait(ctx):
            provider.calls+=1; entered.set(); await asyncio.Event().wait()
        provider.mine=wait
        task=asyncio.create_task(mining.execute(factory,provider,sid,token,rid))
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())
    assert client.get(url+'/recovery',headers=h).json()['state']=='unknown'
    assert count(factory,ConversationTurn)==2 and provider.calls==1


def test_two_empty_rounds_stop_and_no_automatic_followup(stack):
    client,factory,provider,data,auth=stack
    async def empty(ctx):
        provider.calls+=1
        return {'candidates':[],'questions':['Synthetic open question?']}
    provider.mine=empty
    for i in range(2):
        url,h,body=request(stack,f'Synthetic unclear round {i}')
        r=client.post(url,headers=h,json=body).json()
        assert r['state']=='completed'
    assert aggregate(client,data,auth)['mining_status']=='stopped'
    assert r['questions']==[]
    url,h,body=request(stack,'Synthetic third round')
    assert client.post(url,headers=h,json=body).json()['error']['code']=='mining_stopped'
    assert provider.calls==2


def test_rejected_and_edited_origins_are_not_resurrected(stack):
    client,factory,provider,data,auth=stack
    url,h,body=request(stack)
    assert client.post(url,headers=h,json=body).json()['state']=='completed'
    fact=aggregate(client,data,auth)['facts'][0]
    fact=patch(client,fact,auth,'edit',statement='Synthetic corrected B').json()
    patch(client,fact,auth,'reject')
    # An existing legacy user turn may repeat the original A; no second fact is added.
    turn=client.post(ROOT+f'/sessions/{data["session_id"]}/turns',headers=auth,json={'content':'Synthetic A: built a course tracker.'}).json()
    url,h,body=request(stack,input_turn_id=turn['id'])
    assert client.post(url,headers=h,json=body).json()['candidate_fact_ids']==[]
    assert count(factory,ExperienceFact)==1


def test_database_role_change_cannot_forge_existing_source(stack):
    client,factory,provider,data,auth=stack
    with pytest.raises(IntegrityError),factory() as db,db.begin():
        turn=db.get(ConversationTurn,UUID(data['initial_turn_id']))
        turn.role='assistant';db.flush()


def test_expired_keys_cleanup_cannot_revive_and_wrong_owner_hidden(stack):
    client,factory,provider,data,auth=stack
    from app import idempotency as idem
    url,h,body=request(stack)
    r=client.post(url,headers=h,json=body).json()
    other,other_auth=create(client)
    assert client.get(url+'/'+r['id'],headers=other_auth).status_code==404
    assert client.get(url+'/recovery',headers={**h,'Authorization':other_auth['Authorization']}).status_code==401
    old_h,_=headers('mining_run','session:'+data['session_id'],data['access_token'],issued=int(utcnow().timestamp())-86400)
    assert client.post(url,headers=old_h,json=body).status_code==410
    client.delete(ROOT+f'/sessions/{data["session_id"]}',headers=auth)
    with factory() as db,db.begin():
        row=db.scalar(select(MiningReceipt));row.expires_at=utcnow()-timedelta(seconds=1);db.flush()
        assert mining.cleanup(db)==1
    assert count(factory,MiningReceipt)==0 and count(factory,ExperienceSession)==1
    assert client.post(url,headers=h,json=body).status_code==404


def test_global_admission_is_atomic_across_sessions(stack):
    client,factory,provider,data,auth=stack
    from app import idempotency as idem
    def reserve_only(data,auth):
        body=Start(project_id=data['project_id'],base_revision=aggregate(client,data,auth)['context_revision'],input_turn_id=data['initial_turn_id'])
        h,_=headers('mining_run','session:'+data['session_id'],data['access_token'])
        key=idem.parse(h['Idempotency-Key'],data['access_token'],'mining_run','session:'+data['session_id'])
        return mining.reserve(factory,UUID(data['session_id']),data['access_token'],key,body)
    reserve_only(data,auth)
    second,second_auth=create(client);reserve_only(second,second_auth)
    third,third_auth=create(client)
    with pytest.raises(mining.MiningError) as error: reserve_only(third,third_auth)
    assert error.value.code=='mining_capacity'
    assert count(factory,MiningRun)==2


def test_multi_project_legacy_migration_refuses_without_data_loss(migrated_connection):
    connection,cfg=migrated_connection
    command.downgrade(cfg,'0003_idempotency')
    sid=uuid4()
    connection.execute(text("INSERT INTO experience_sessions(id,created_at,access_token_hash,status,updated_at) VALUES (:id,now(),'synthetic','active',now())"),{'id':sid})
    for _ in range(2):
        connection.execute(text("INSERT INTO experience_projects(id,created_at,session_id,raw_input) VALUES (:id,now(),:sid,'Synthetic legacy project')"),{'id':uuid4(),'sid':sid})
    connection.commit()
    with pytest.raises(IntegrityError): command.upgrade(cfg,'head')
    connection.rollback()
    assert connection.scalar(text('SELECT count(*) FROM experience_projects'))==2
    assert connection.scalar(text('SELECT version_num FROM alembic_version'))=='0003_idempotency'


def test_same_session_assistant_and_other_project_cannot_be_inputs(stack):
    client,factory,provider,data,auth=stack
    with factory() as db,db.begin():
        t=ConversationTurn(session_id=UUID(data['session_id']),role='assistant',content='Synthetic unsupported guess')
        db.add(t);db.flush();tid=t.id
    url,h,body=request(stack,input_turn_id=str(tid))
    assert client.post(url,headers=h,json=body).json()['error']['code']=='mining_invalid_source'
    other,_=create(client)
    url,h,body=request(stack,'Synthetic cross project',project_id=other['project_id'])
    assert client.post(url,headers=h,json=body).status_code==404
    assert count(factory,MiningRun)==0 and provider.calls==0


def test_retry_chain_cannot_start_second_attempt_for_same_parent(stack):
    client,factory,provider,data,auth=stack
    original=provider.mine
    async def invalid(ctx): return {}
    provider.mine=invalid
    url,h,body=request(stack,'Synthetic known invalid run')
    first=client.post(url,headers=h,json=body).json();assert first['state']=='failed'
    provider.mine=original
    url2,h2,b2=request(stack);b2.pop('input_turn_id');b2.update(retry_of=first['id'],confirm_retry=True)
    assert client.post(url2,headers=h2,json=b2).json()['state']=='completed'
    url3,h3,b3=request(stack);b3.pop('input_turn_id');b3.update(retry_of=first['id'],confirm_retry=True)
    assert client.post(url3,headers=h3,json=b3).json()['error']['code']=='mining_retry_superseded'
    assert count(factory,MiningRun)==2 and count(factory,ConversationTurn)==3


def test_lease_expiring_during_result_transaction_rolls_back_every_output(stack,monkeypatch):
    import time
    client,factory,provider,data,auth=stack
    monkeypatch.setattr(mining,'LEASE_SECONDS',1)
    original=facts.record_change
    def slow(*args,**kwargs):
        original(*args,**kwargs);time.sleep(1.1)
    monkeypatch.setattr(facts,'record_change',slow)
    url,h,body=request(stack,'Synthetic deadline answer')
    assert client.post(url,headers=h,json=body).json()['state']=='unknown'
    assert count(factory,ExperienceFact)==count(factory,FactSource)==count(factory,FactChange)==count(factory,MiningQuestion)==0
    assert count(factory,ConversationTurn)==2


def test_recovery_runs_in_postgresql_read_only_transaction(stack):
    from app import idempotency as idem
    client,factory,provider,data,auth=stack
    url,h,body=request(stack)
    result=client.post(url,headers=h,json=body).json()
    sid=UUID(data['session_id']);token=data['access_token']
    key=idem.parse(h['Idempotency-Key'],token,'mining_run','session:'+str(sid))
    with factory() as db,db.begin():
        db.execute(text('SET TRANSACTION READ ONLY'))
        assert mining.recover(db,sid,token,key)['id']==UUID(result['id'])
        assert mining.get_run(db,sid,token,UUID(result['id']),lock=False).state=='completed'
    assert provider.calls==1
