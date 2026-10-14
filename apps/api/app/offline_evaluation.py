"""Isolated teacher-forced MOCK evaluation. Fixed repository synthetic data only."""
from contextlib import contextmanager
from datetime import timedelta
import json
from pathlib import Path
import re
from uuid import uuid5, NAMESPACE_URL

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import facts, mining
from app.cost_ledger import Ledger, canonical, digest
from app.mining_context import build_context, question_fingerprint
from app.model_adapter import Adapter, Profile, MockTransport, OfflineRunner, SimulatedCrash
from app.models import ExperienceSession, ExperienceProject, ConversationTurn, MiningRun, MiningQuestion, ExperienceFact, AnswerQuestion, utcnow

ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/'docs/evaluation/m12c2-synthetic-cases.json'
WIRE=ROOT/'docs/evaluation/provider-wire-output.schema.json'
PROFILES=ROOT/'docs/evaluation/m12c2-profile-drafts.json'
# Human annotations, not model/lexical inference. Bounds are separate from resume contributions.
BOUNDARY={('S01','c'),('S03','a'),('S05','b'),('S07','b')}
RATE={'currency':'CNY_SIMULATED','input':'2','cached':'1','output':'8'}


def fixed_id(value): return uuid5(NAMESPACE_URL,'pathwise-offline-eval-v1:'+value)


def test_url(value):
    try:
        u=make_url(value)
        if (u.get_backend_name()!='postgresql' or u.host not in ('localhost','127.0.0.1') or u.database not in ('pathwise_test','pathwise_e2e') or u.username in (None,'postgres','pathwise_dev') or u.query): raise ValueError()
        return u.set(drivername='postgresql+psycopg')
    except Exception: raise ValueError('isolated_test_database_required') from None


@contextmanager
def isolated_database(value):
    # No fallback to DATABASE_URL; fresh schema only, never upgrade public schema.
    url=test_url(value)
    from uuid import uuid4
    schema='test_eval_'+uuid4().hex
    engine=create_engine(url,hide_parameters=True,poolclass=NullPool)
    try:
        with engine.connect() as conn:
            actual=conn.scalar(text('SELECT current_database()'))
            if actual!=url.database: raise ValueError('database_mismatch')
            conn.execute(text(f'CREATE SCHEMA "{schema}"'));conn.execute(text(f'SET search_path TO "{schema}"'));conn.commit()
            cfg=Config(str(ROOT/'apps/api/alembic.ini'));cfg.attributes['connection']=conn
            try:
                command.upgrade(cfg,'head');command.check(cfg);conn.commit()
                isolated=create_engine(url,hide_parameters=True,poolclass=NullPool,connect_args={'options':f'-csearch_path={schema}'})
                try: yield sessionmaker(isolated,expire_on_commit=False)
                finally: isolated.dispose()
            finally:
                conn.rollback();conn.execute(text('SET search_path TO public'))
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'));conn.commit()
    finally: engine.dispose()


def fixture_response(profile, context, step, ordinal):
    # An oracle-shaped fixture proves plumbing only, NEVER vendor capability.
    candidates=[{'citation':{'turn_id':str(context.input_turn_id),**gold}} for gold in step['gold_candidates']]
    stop=not step['question_goals']
    questions=[] if stop else [{'text':f'合成追问第{ordinal}轮：请补充你本人实际完成的步骤，记不清可以跳过。'.replace(str(ordinal),'一' if ordinal==1 else '二' if ordinal==2 else '三'), 'purpose':step['question_goals'][0],'source_turn_ids':[str(context.input_turn_id)]}]
    output={'schema_version':2,'candidates':candidates,'questions':questions,'stop':stop,'stop_reason':'no_new_information' if stop else None}
    return {'model':profile.api_model,'choices':[{'finish_reason':'stop','message':{'content':canonical(output)}}],'usage':{'prompt_tokens':100,'completion_tokens':80}}


def evaluate(factory, profile_index=0, fault=None):
    # Stable fact/question IDs keep teacher-forced contexts identical across
    # explicitly selected profiles. Listener is restricted to THIS factory.
    def deterministic_ids(db,flush_context,instances):
        for item in db.new:
            if isinstance(item,ExperienceFact) and item.id is None:
                item.id=fixed_id('fact:'+str(item.project_id)+':'+str(item.ai_run_id)+':'+item.statement)
            elif isinstance(item,MiningQuestion) and item.id is None:
                item.id=fixed_id('question:'+str(item.run_id)+':'+item.content)
    event.listen(factory,'before_flush',deterministic_ids)
    try:return _evaluate(factory,profile_index,fault)
    finally:event.remove(factory,'before_flush',deterministic_ids)


def _evaluate(factory, profile_index=0, fault=None):
    data=json.loads(DATA.read_text(encoding='utf8'));profiles=json.loads(PROFILES.read_text(encoding='utf8'))
    if len(data['cases'])!=12 or any(c.get('synthetic') is not True for c in data['cases']): raise ValueError('synthetic_dataset_required')
    profile=Profile.model_validate(profiles['profiles'][profile_index]);adapter=Adapter(profile,json.loads(WIRE.read_text(encoding='utf8')))
    ledger=Ledger(factory,'mock-'+profile.id)
    scopes={('global','all'):'30',('provider',profile.provider):'30',('model',profile.model):'30'}
    for case in data['cases']:scopes['session',case['id']]='2'
    ledger.configure(scopes)
    records=[];events=[];total_dispatch=0
    for case in data['cases']:
        sid=fixed_id(case['id']+'session');pid=fixed_id(case['id']+'project');token='offline-synthetic-only'
        with factory.begin() as db:
            db.add(ExperienceSession(id=sid,access_token_hash=facts.token_hash(token),status='active',mining_status='active'));db.flush()
            db.add(ExperienceProject(id=pid,session_id=sid,raw_input=case['project']));db.flush()
        saved={};fact_ids={};last_question=None;ordinal=0
        for step in case['steps']:
            kind=step['kind']
            if kind=='user':
                ordinal+=1;key=step['turn_key'];tid=fixed_id(case['id']+key+'turn');rid=fixed_id(case['id']+key+'run')
                with factory.begin() as db:
                    db.add(ConversationTurn(id=tid,session_id=sid,role='user',content=step['text']));db.flush()
                    if last_question:
                        q=db.get(MiningQuestion,last_question)
                        if q.state in ('active','corrected'):db.add(AnswerQuestion(turn_id=tid,question_id=q.id,session_id=sid,question_version=q.version,slot=1));db.flush()
                    session=db.get(ExperienceSession,sid);db.refresh(session)
                    run=MiningRun(id=rid,session_id=sid,project_id=pid,input_turn_id=tid,base_revision=session.context_revision,reserved_revision=session.context_revision,state='running',lease_until=utcnow()+timedelta(seconds=60),provider='offline_mock',prompt_version='eval-v1')
                    db.add(run);db.flush();ctx=build_context(db,run,session)
                packet=fixture_response(profile,ctx,step,ordinal)
                if fault=='429':packet={'status':429}
                elif fault=='5xx':packet={'status':503}
                elif fault=='refusal':packet['choices'][0]['message']['refusal']='synthetic refusal'
                elif fault=='truncated':packet['choices'][0]['finish_reason']='length'
                elif fault=='schema':packet['choices'][0]['message']['content']='{"status":"user_confirmed"}'
                elif fault=='source':
                    invalid=json.loads(packet['choices'][0]['message']['content'])
                    invalid['candidates']=[{'citation':{'turn_id':str(ctx.input_turn_id),'quote':'我负责部署。','start':0,'end':6}}]
                    packet['choices'][0]['message']['content']=canonical(invalid)
                transport=MockTransport(packet,fault=fault if fault in ('timeout','crash') else None)
                runner=OfflineRunner(ledger,adapter,transport)
                try:call_id,envelope=runner.run(ctx,case['id']+key,case['id'],'.05',RATE)
                except SimulatedCrash:
                    from app.models import CostCall
                    with factory() as db:call_id=db.scalar(select(CostCall.id).where(CostCall.namespace==ledger.namespace))
                    envelope=None
                saved[key]=(runner,ctx,call_id);total_dispatch+=transport.calls
                source_ok=False;error=None
                if envelope:
                    try:
                        # EXACT runtime source/atomicity validator and final fence.
                        mining.complete(factory,sid,token,rid,envelope.output,context=ctx)
                        with factory() as db:
                            run=db.get(MiningRun,rid);source_ok=run.state=='completed'
                            if not source_ok: error=run.error_code
                    except (ValueError,mining.MiningError):
                        error='output_invalid'
                        with factory.begin() as db:db.get(MiningRun,rid).state='failed'
                    # Known zero invoice ONLY because the transport is local.
                    ledger.reconcile(call_id,'0','mock-invoice-'+profile.id+case['id']+key)
                with factory() as db:
                    candidates=db.scalars(select(ExperienceFact).where(ExperienceFact.ai_run_id==rid)).all()
                    fact_ids[key]=[f.id for f in candidates]
                    questions=db.scalars(select(MiningQuestion).where(MiningQuestion.run_id==rid)).all()
                    last_question=questions[-1].id if questions else None
                    assert all(f.status=='pending' for f in candidates)
                count=len(envelope.output.candidates) if envelope else 0;boundary=(case['id'],key) in BOUNDARY
                gold={(g['quote'],g['start'],g['end']) for g in step['gold_candidates']}
                correct=sum((c.citation.quote,c.citation.start,c.citation.end) in gold and c.citation.turn_id==ctx.input_turn_id for c in envelope.output.candidates) if envelope else 0
                included={t.turn_id:t.content for t in ctx.user_turns}
                quote_matches=sum(c.citation.turn_id in included and included[c.citation.turn_id][c.citation.start:c.citation.end]==c.citation.quote for c in envelope.output.candidates) if envelope else 0
                history={q.dedup_fingerprint for q in ctx.questions if q.dedup_fingerprint}
                duplicate_questions=0;purpose_matches=0
                if envelope:
                    for q in envelope.output.questions:
                        fp=question_fingerprint(q.text);duplicate_questions+=int(fp in history);history.add(fp)
                        purpose_matches+=int(q.purpose in step['question_goals'])
                records.append({'case':case['id'],'step':key,'call_id':str(call_id),'context_hash':digest(canonical(ctx.payload())),'provider':profile.provider,'model':profile.model,'profile':profile.safe_snapshot(),'mode':'mock','reported_model_mock':envelope.evidence if envelope else None,'structure_success_mock':envelope is not None,'sources_accepted_mock':source_ok,'raw_candidates':count,'accepted_candidates':len(candidates),'positive_contribution_gold':0 if boundary else len(gold),'negative_boundary_gold':len(gold) if boundary else 0,'exact_gold_precision_mock':correct/count if count else None,'source_accuracy_mock':quote_matches/count if count else None,'question_count_mock':len(envelope.output.questions) if envelope else None,'duplicate_questions_exact_mock':duplicate_questions if envelope else None,'question_purpose_match_mock':purpose_matches/len(envelope.output.questions) if envelope and envelope.output.questions else None,'semantic_question_quality':None,'real_quality':None,'provider_latency_ms':None,'actual_model_tokens':None,'ledger':ledger.get(call_id),'error':error or ledger.get(call_id)['error_code']})
                if fault:
                    before=transport.calls
                    assert runner.run(ctx,case['id']+key,case['id'],'.05',RATE)[1] is None
                    assert transport.calls==before
                    return {'schema_version':1,'report_kind':'offline_fault_not_real_quality','fault':fault,'configured_cases':12,'executed_cases':1,'records':records,'same_operation_resends':0,'real_vendor_requests':0,'actual_cost_cny':'0.000000','real_model_metrics':None,'provider_latency_ms':None,'actual_model_tokens':None,'cost_totals_mock':ledger.report()}
            elif kind=='repeat_submission':
                runner,ctx,cid=saved[step['target_turn']];before=runner.transport.calls
                again,_=runner.run(ctx,case['id']+step['target_turn'],case['id'],'.05',RATE)
                assert again==cid and runner.transport.calls==before
                events.append({'case':case['id'],'kind':kind,'new_model_calls':0})
            elif kind in ('fact_edit','fact_confirm'):
                with factory.begin() as db:
                    ids=fact_ids[step['target_turn']]
                    for fid in ids:
                        fact=db.get(ExperienceFact,fid)
                        facts.change_fact(db,fid,token,expected_version=fact.version,**({'statement':step['new_statement']} if kind=='fact_edit' else {'status':'user_confirmed'}))
                events.append({'case':case['id'],'kind':kind,'status':step['expected_status']})
            elif kind=='question_action' and last_question:
                with factory.begin() as db:
                    q=db.get(MiningQuestion,last_question);q.version+=1
                    q.state={'skip':'skipped','hide':'hidden','correct':'corrected','delete':'deleted'}[step['action']]
                    if step['action']=='correct':q.content=step['new_wording']
                    if step['action']=='delete':q.content=None
                events.append({'case':case['id'],'kind':kind,'action':step['action']})
            elif kind=='user_stop':
                with factory.begin() as db:db.get(ExperienceSession,sid).mining_status='stopped'
                events.append({'case':case['id'],'kind':kind,'new_model_calls':0})
            elif kind=='expect_stopped':
                with factory() as db:assert db.get(ExperienceSession,sid).mining_status=='stopped'
                events.append({'case':case['id'],'kind':kind,'passed':True})
            elif kind=='assert_privacy':
                for marker in step['must_mask']:assert marker not in canonical(ctx.payload())
                events.append({'case':case['id'],'kind':kind,'passed':True})
    return {'schema_version':1,'report_kind':'offline_mock_not_real_quality','dataset_hash':digest(DATA.read_text(encoding='utf8')),'profile':profile.safe_snapshot(),'cases':12,'records':records,'events':events,'mock_dispatches':total_dispatch,'real_vendor_requests':0,'actual_cost_cny':'0.000000','real_model_metrics':None,'provider_latency_ms':None,'actual_model_tokens':None,'cost_totals_mock':ledger.report(),'limitations':['Golden fixtures exercise contracts, not model ability or semantic quality.','Rates and invoices are synthetic CNY simulations, not approved prices.','Real providers, keys and production ledger APIs are absent.']}
