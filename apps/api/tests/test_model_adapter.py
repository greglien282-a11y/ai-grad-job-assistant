"""Offline adapter payloads, exact source fences and synthetic evaluations."""
import json
from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app import mining
from app.model_adapter import Adapter, AdapterError, MockTransport, OfflineRunner, Profile, parse_output
from app.offline_evaluation import evaluate, test_url as validate_url
from app.cost_ledger import Ledger
from app.models import ConversationTurn, ExperienceFact, ExperienceSession, MiningRun
from test_cost_ledger import ledger_stack, profile, context, response
from test_mining_context import v2, post
from test_mining import stack
from test_http_api import api


@pytest.mark.parametrize('index',[0,1,2])
def test_all_synthetic_cases_real_postgresql_no_vendor_requests(ledger_stack,index):
    ledger,factory,_=ledger_stack
    report=evaluate(factory,index)
    assert report['cases']==12 and report['real_vendor_requests']==0 and report['actual_cost_cny']=='0.000000'
    assert report['real_model_metrics'] is None and report['provider_latency_ms'] is None
    assert all(r['sources_accepted_mock'] for r in report['records'])
    assert sum(r['negative_boundary_gold'] for r in report['records'])==4
    assert sum(r['positive_contribution_gold'] for r in report['records'])>4
    assert any(e['kind']=='repeat_submission' and e['new_model_calls']==0 for e in report['events'])
    # Edited then explicitly user-confirmed S07 is a human event, not AI promotion.
    with factory() as db:
        confirmed=db.scalars(select(ExperienceFact).where(ExperienceFact.status=='user_confirmed')).all()
        assert len(confirmed)==1 and confirmed[0].statement=='我负责排序需求记录。'
        assert all(r.tokens_in==100 and r.tokens_out==80 for r in db.scalars(select(MiningRun)))
    assert all(r['real_quality'] is None and r['provider_latency_ms'] is None for r in report['records'])


@pytest.mark.parametrize('content',['{"schema_version":2,"schema_version":2}', '```json\n{}\n```','{} {}','{"schema_version":2,"candidates":[],"questions":[],"stop":true,"stop_reason":"no_new_information","tokens_in":0}', '{"schema_version":2,"candidates":[],"questions":[],"stop":true,"stop_reason":null}'])
def test_output_contract_no_repair_or_untrusted_usage(content):
    with pytest.raises(AdapterError,match='output_invalid'):parse_output(content)


def test_real_transport_and_profile_enablement_are_impossible(ledger_stack):
    p=profile()
    with pytest.raises(ValueError):Profile.model_validate(p.model_dump()|{'enabled':True})
    with pytest.raises(AdapterError,match='mock_transport_required'):OfflineRunner(ledger_stack[0],Adapter(p,{}),object())
    # Even ambient AI/key variables cannot create a live transport; no resolver exists.
    with patch('socket.socket.connect',side_effect=AssertionError('No provider network')),patch('socket.getaddrinfo',side_effect=AssertionError('No provider DNS')):
        request=Adapter(p,{}).build_request(context())
        assert 'Authorization' not in request and request['stream'] is False
    for change in [{'base_url':'https://unapproved.invalid'},{'model':'wrong-model'},{'region':'unverified-secret-like-label'},{'version':'unverified-version'},{'api_model':'deepseek-v4.1-flash'}]:
        with pytest.raises(AdapterError):Adapter(Profile.model_validate(p.model_dump()|change),{})


@pytest.mark.parametrize('url',[None,'sqlite:///test.db','postgresql://pathwise_test:x@127.0.0.1/pathwise_dev','postgresql://postgres:x@localhost/pathwise_test','postgresql://pathwise_test:x@remote.invalid/pathwise_test','postgresql://pathwise_test:x@localhost/pathwise_test?options=-csearch_path=public'])
def test_eval_refuses_unsafe_db_before_connecting(url):
    with pytest.raises(ValueError,match='isolated_test_database_required'):validate_url(url)


@pytest.mark.parametrize('mutation',['offset','turn','negation','confirmed','assistant','stale'])
def test_adapter_output_still_requires_runtime_database_source_fence(v2,mutation):
    client,factory,provider,data,auth=v2
    if mutation=='assistant':post(v2,'合成：先提供背景。')
    def modified(inp,old):
        ctx=inp.context;packet=response(profile(),ctx)
        wire=json.loads(packet['choices'][0]['message']['content'])
        wire['candidates']=[{'citation':{'turn_id':str(ctx.input_turn_id),'quote':'我没有负责部署。','start':0,'end':8}}]
        if mutation=='offset':wire['candidates'][0]['citation']['end']=7
        if mutation=='turn':wire['candidates'][0]['citation']['turn_id']=str(uuid4())
        if mutation=='negation':wire['candidates'][0]['citation'].update(quote='部署。',start=5,end=8)
        if mutation=='confirmed':wire['candidates'][0]['status']='user_confirmed'
        if mutation=='assistant':
            with factory() as db:wire['candidates'][0]['citation']['turn_id']=str(db.scalar(select(ConversationTurn.id).where(ConversationTurn.role=='assistant')))
        if mutation=='stale':
            with factory.begin() as db:db.get(ExperienceSession,__import__('uuid').UUID(data['session_id'])).status='ended'
        packet['choices'][0]['message']['content']=json.dumps(wire)
        return Adapter(profile(),{}).normalize(packet).output
    provider.override=modified
    run,_=post(v2,'我没有负责部署。')
    assert run['state']==('stale' if mutation=='stale' else 'failed')
    with factory() as db:assert not db.scalar(select(ExperienceFact.id))


@pytest.mark.parametrize('fault',['429','5xx','refusal','truncated','schema','source','timeout','crash'])
def test_evaluation_fault_reports_are_honest_and_never_retry(ledger_stack,fault):
    report=evaluate(ledger_stack[1],0,fault)
    assert report['executed_cases']==1 and report['same_operation_resends']==0
    assert report['real_model_metrics'] is None and report['provider_latency_ms'] is None
    row=report['records'][0]
    assert row['accepted_candidates']==0 and not row['sources_accepted_mock']
    if fault=='source':
        assert row['exact_gold_precision_mock']==0 and row['error']=='output_invalid'
        assert row['ledger']['actual']=='0.000000' # explicit known mock zero invoice
    else:
        assert row['ledger']['actual'] is None
        assert row['ledger']['state']==('sent' if fault=='crash' else 'unknown')
        group=report['cost_totals_mock']['provider:deepseek_official']
        assert group['unknown_usage_calls']==1 and group['unreconciled_calls']==1


def test_explicit_profiles_receive_identical_teacher_forced_contexts(ledger_stack):
    from sqlalchemy import delete
    factory=ledger_stack[1];hashes=[]
    for index in range(3):
        report=evaluate(factory,index)
        hashes.append([r['context_hash'] for r in report['records']])
        with factory.begin() as db:db.execute(delete(ExperienceSession))
    assert hashes[0]==hashes[1]==hashes[2]
