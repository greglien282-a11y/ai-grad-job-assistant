"""Fictional quality scaffolding; never a real model or human benchmark."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import ctypes
from uuid import uuid4
import httpx
import psycopg
import pytest
import sqlalchemy

from app.cost_ledger import canonical
from app.mining_quality_data import (load_dataset,context_for,DATA_DIR,ROOT,DIMENSIONS,Case,QualityInputError)
from app.mining_quality_evaluation import evaluate,read_json,markdown_report,text_sha
from app.mining_quality_review import (templates,review_packet,summarize_reviews,reviews_markdown)
from app.model_adapter import Adapter


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def denied(*a,**k): raise AssertionError('Quality scoring cannot access providers, secrets or DB')
    for obj,name in ((socket,'create_connection'),(socket,'getaddrinfo'),(psycopg,'connect'),
        (sqlalchemy,'create_engine'),(httpx.HTTPTransport,'handle_request'),
        (httpx.AsyncHTTPTransport,'handle_async_request'),(Adapter,'build_request')):
        monkeypatch.setattr(obj,name,denied)
    monkeypatch.setattr(ctypes,'WinDLL',denied,raising=False)


def bundle(name='oracle'):
    return read_json(DATA_DIR/(name+'.outputs.json'))


def row_for(b,case_id):
    return next(r for r in evaluate(b)['rows'] if r['case_id']==case_id)


def changed(case_id,mutate):
    b=bundle();e=next(e for e in b['outputs'] if e['case_id']==case_id)
    raw=json.loads(e['content']);mutate(raw);e['content']=canonical(raw)
    return b


def demo_reviews(report,b):
    template=templates(report)
    r=next(r for r in template['reviews'] if r['case_id']=='GQ06')
    e=next(e for e in b['outputs'] if e['case_id']=='GQ06')
    index=e['content'].index('80%')
    evidence=dict(source='output',source_id=e['output_id'],quote='80%',start=index,end=index+3)
    for key in DIMENSIONS:
        r['ratings'][key]=dict(score=4,applicability='applicable',reason='仅验证演示流程，不是真实人工评分。',evidence=[evidence])
    r.update(demonstration=True,reviewer_ref='DEMO_A_NOT_A_PERSON',reviewer_status='demonstration',
        submission_status='submitted',needs_second_review=True,
        severe_errors=[dict(code='fabricated_metric',reason='合成输出预设未经提供的比例。',evidence=[evidence])])
    second=deepcopy(r);second['reviewer_ref']='DEMO_B_NOT_A_PERSON'
    second['ratings']['faithfulness']['score']=2
    return dict(template_version=template['template_version'],instructions='DEMONSTRATION ONLY',reviews=[r,second])


@pytest.mark.parametrize('case_index',range(20))
def test_draft_case_context_and_unicode_references(case_index):
    _,cases=load_dataset();c=cases[case_index];ctx=context_for(c)
    assert c.synthetic is True and c.review_status=='DRAFT' and c.human_reviewer is None
    assert c.reference.label_status=='DRAFT' and ctx.user_turns[0].turn_id==c.turns[-1].turn_id
    turns={t.turn_id:t.text for t in c.turns}
    for citation in c.reference.citations:
        assert turns[citation.turn_id][citation.start:citation.end]==citation.quote
    for f in (*c.confirmed_facts,*c.pending_facts):
        assert turns[f.citation.turn_id][f.citation.start:f.citation.end]==f.statement


def test_split_frozen_no_holdout_oracle_and_no_prompt_contamination():
    _,cases=load_dataset();dev={c.case_id for c in cases if c.split=='development'}
    hold={c.case_id for c in cases if c.split=='holdout'}
    assert len(dev)==12 and len(hold)==8 and dev.isdisjoint(hold)
    assert {e['case_id'] for e in bundle()['outputs']}==dev
    assert {e['case_id'] for e in bundle('adversarial')['outputs']}==dev
    prompt=(ROOT/'docs/evaluation/dynamic-mining-prompt-v1.txt').read_text(encoding='utf8')
    assert all(t.text not in prompt and str(t.turn_id) not in prompt for c in cases for t in c.turns)
    with pytest.raises(QualityInputError): evaluate(bundle(),split='holdout')


@pytest.mark.parametrize('field,value',[('review_status','APPROVED'),('human_reviewer','invented-reviewer'),('synthetic',False)])
def test_authored_draft_cannot_masquerade_as_human_gold(field,value):
    _,cases=load_dataset();data=cases[0].model_dump(mode='json');data[field]=value
    with pytest.raises(ValueError): Case.model_validate(data)


def test_two_question_partial_answer_and_correction_versions():
    _,cases=load_dataset();partial=context_for(cases[13]);corrected=context_for(cases[11])
    assert len(partial.questions)==2 and len(partial.user_turns[0].answered_questions)==1
    assert partial.questions[0].answered_turn_id==partial.input_turn_id and partial.questions[1].answered_turn_id is None
    assert corrected.questions[0].version==2 and corrected.questions[0].answered_version==1
    assert not corrected.questions[0].answer_matches_current_version
    assert corrected.facts[0].source_kind=='user_edit' and corrected.facts[0].status=='pending'


def test_oracle_is_tautological_draft_fit_not_model_quality():
    r=evaluate(bundle())
    assert r['metrics']['strict_schema']['numerator']==12
    assert r['metrics']['draft_candidate_recall']['ratio']==1
    assert r['metrics']['runtime_validation']['numerator']==11  # existing lexical limit, NOT weakened
    assert row_for(bundle(),'GQ03')['validation_code']=='runtime_validation_rejected'
    assert r['human_semantic_scores'] is None and r['real_model_holdout_quality'] is None
    assert r['tool_provider_requests']==0 and r['tool_cost_cny']=='0.000000'
    assert all(all(v is None for v in row['human_quality'].values()) for row in r['rows'])


def test_positive_and_boundary_recall_never_mixed():
    r=evaluate(bundle());metrics=r['metrics']
    assert metrics['draft_positive_recall']['denominator']>0
    assert metrics['draft_boundary_recall']['denominator']==1
    assert row_for(bundle(),'GQ09')['metrics']['draft_positive_recall']['ratio'] is None
    assert row_for(bundle(),'GQ09')['metrics']['draft_boundary_recall']['ratio']==1


@pytest.mark.parametrize('index',range(12))
def test_adversarial_results_do_not_pass_as_all_correct(index):
    row=evaluate(bundle('adversarial'))['rows'][index]
    assert row['human_review_status']=='unreviewed'
    assert (row['schema_valid'] is False or row['runtime_valid'] is False
        or row['metrics']['draft_candidate_recall']['ratio']==0 or row['metrics']['draft_stop_alignment']['ratio']==0)


def test_structurally_valid_stop_can_be_business_wrong():
    row=row_for(bundle('adversarial'),'GQ04')
    assert row['schema_valid'] and row['runtime_valid']
    assert row['metrics']['stop_structure']['ratio']==1
    assert row['metrics']['draft_stop_alignment']['ratio']==0
    assert row['metrics']['draft_candidate_precision']['ratio'] is None


def test_old_correction_is_literal_but_not_current_draft_fact():
    row=row_for(bundle('adversarial'),'GQ12')
    assert row['metrics']['literal_citations']['ratio']==1
    assert row['metrics']['draft_candidate_precision']['ratio']==0
    assert any(x['code']=='superseded_claim' for x in row['critical_rule_signals'])


def test_missing_empty_invalid_and_na_are_explicit_not_perfect():
    b=bundle();b['outputs']=b['outputs'][1:]
    r=evaluate(b)
    assert r['planned_outputs']==12 and r['missing_outputs']==1
    assert r['metrics']['strict_schema']['denominator']==12 and r['metrics']['strict_schema']['unscorable']==1
    missing=r['rows'][0]
    assert missing['metrics']['draft_candidate_recall']['ratio']==0
    assert missing['metrics']['draft_candidate_precision']['ratio'] is None
    empty=row_for(bundle(),'GQ02')
    assert empty['metrics']['draft_candidate_precision']['ratio'] is None
    assert empty['metrics']['draft_candidate_recall']['ratio'] is None


@pytest.mark.parametrize('fault',['invalid_json','wrong_type','missing_field','wrong_uuid','offset','duplicate','extra_confirmed'])
def test_common_contract_faults_counted_not_repaired(fault):
    b=bundle();e=b['outputs'][0];v=json.loads(e['content'])
    if fault=='invalid_json':e['content']='{'
    else:
        if fault=='wrong_type': v['candidates']={}
        elif fault=='missing_field':v.pop('questions')
        elif fault=='wrong_uuid':v['candidates'][0]['citation']['turn_id']=str(uuid4())
        elif fault=='offset':v['candidates'][0]['citation']['end']+=1
        elif fault=='duplicate':v['questions']*=2
        else:v['candidates'][0]['status']='user_confirmed'
        e['content']=canonical(v)
    row=evaluate(b)['rows'][0]
    assert not row['schema_valid'] or row['runtime_valid'] is False
    assert row['validation_code']!='runtime_valid'
    if fault=='wrong_type':assert row['raw_candidate_count'] is None
    if fault=='extra_confirmed':assert any(f['code']=='unrequested_confirmation' for f in row['critical_rule_signals'])


def test_exact_question_duplicates_include_skipped_history():
    b=bundle();_,cases=load_dataset();e=b['outputs'][0]
    c=cases[0];ctx=context_for(c)
    from app.mining_quality_evaluation import score_case
    # Existing development case gets a test-only skipped historical question.
    data=c.model_dump(mode='json');qid=str(uuid4())
    data['previous_questions']=[dict(question_id=qid,version=1,state='skipped',content='你本人做过什么？',answered_turn_id=None,answered_version=None)]
    c=Case.model_validate(data)
    v=json.loads(e['content']);v['questions'][0]['text']='你本人做过什么？';e['content']=canonical(v)
    from app.mining_quality_evaluation import SuppliedOutput
    row=score_case(c,SuppliedOutput.model_validate(e))
    assert row['duplicate_question_count']==1 and row['runtime_valid'] is False


def test_purpose_match_and_number_match_are_not_semantic_scores():
    row=row_for(bundle('adversarial'),'GQ06')
    assert row['metrics']['draft_question_purpose']['ratio']==1
    assert row['metrics']['supported_numeric_tokens']['ratio']==0
    assert row['human_quality']['question_effectiveness'] is None
    assert any(f['code']=='unsupported_numeric_token' for f in row['critical_rule_signals'])


@pytest.mark.parametrize('case_index',[14,15,16,17])
def test_holdout_stop_rules_have_separate_offline_checks(case_index):
    _,cases=load_dataset();case=cases[case_index]
    from app.mining_quality_evaluation import score_case,SuppliedOutput
    v=dict(schema_version=2,candidates=[],questions=[],stop=True,stop_reason='no_new_information')
    entry=SuppliedOutput(case_id=case.case_id,output_id='test-only-holdout-stop',content=canonical(v))
    good=score_case(case,entry)
    assert good['metrics']['draft_stop_alignment']['ratio']==1
    v.update(stop=False,stop_reason=None,questions=[dict(text='还有什么需要补充？',purpose='detail',source_turn_ids=[str(case.turns[-1].turn_id)])])
    bad=score_case(case,entry.model_copy(update={'content':canonical(v)}))
    assert bad['schema_valid'] and bad['metrics']['draft_stop_alignment']['ratio']==0


def test_unicode_index_not_utf16_or_bytes():
    _,cases=load_dataset();c=cases[19];ref=c.reference.citations[0]
    assert ref.end==len(ref.quote) and ref.end!=len(ref.quote.encode('utf-16-le'))//2
    raw=c.model_dump(mode='json');raw['reference']['citations'][0]['end']=len(ref.quote.encode('utf8'))
    with pytest.raises(ValueError):Case.model_validate(raw)


@pytest.mark.parametrize('field,value',[('generation_verified',True),('provider_generated',True),('prompt_file_sha','0'*64),('schema_sha','f'*64)])
def test_provenance_cannot_claim_verified_generation_or_wrong_prompt(field,value):
    b=bundle();b['provenance'][field]=value
    with pytest.raises(QualityInputError):evaluate(b)


def test_imported_generation_still_not_authenticated_real_quality():
    b=bundle();b['provenance'].update(output_origin='imported_model_unverified',provider_generated=True,provider='declared-provider',model='declared-model')
    r=evaluate(b)
    assert r['real_model_holdout_quality'] is None
    assert r['evidence_layers']['real_model_quality']=='NOT_MEASURED_OR_AUTHENTICATED'


def test_duplicate_missing_unknown_output_identity_rejected():
    b=bundle();b['outputs'].append(deepcopy(b['outputs'][0]))
    with pytest.raises(QualityInputError):evaluate(b)
    b=bundle();b['outputs'][0]['case_id']='GQ99'
    with pytest.raises(QualityInputError):evaluate(b)


def test_reports_deterministic_and_safe_even_with_unsafe_supplied_output():
    b=bundle();secret='sk-public-fake-sentinel-no-real-key'
    b['outputs'][0]['content']='Bearer '+secret
    r=evaluate(b);again=evaluate(deepcopy(b))
    assert canonical(r)==canonical(again) and markdown_report(r)==markdown_report(again)
    assert secret not in canonical(r)+markdown_report(r)+review_packet(r,b)
    assert r['rows'][0]['safety_redacted'] and r['rows'][0]['output_sha'] is None


def test_review_templates_have_no_scores_or_invented_reviewer():
    r=evaluate(bundle());t=templates(r)
    assert all(x['reviewer_ref'] is None and x['submission_status']=='draft' for x in t['reviews'])
    assert all(s['score'] is None and s['applicability']=='unreviewed' for x in t['reviews'] for s in x['ratings'].values())
    summary=summarize_reviews(r,bundle(),t)
    assert summary['human_reviews'] is None and summary['demonstration_reviews'] is None


def test_demo_scores_and_disagreements_never_become_human_results():
    b=bundle('adversarial');r=evaluate(b);records=demo_reviews(r,b)
    summary=summarize_reviews(r,b,records)
    assert summary['human_reviews'] is None
    demo=summary['demonstration_reviews']
    assert demo['severe_errors_block_acceptance'] and len(demo['critical_errors'])==2
    assert demo['dimensions']['stopping']['mean']==4
    assert demo['disagreements'][0]['dimension']=='faithfulness'
    assert demo['reviewer_agreement_rate'] is None and demo['acceptance_decision']=='NOT_ISSUED'
    assert 'DEMONSTRATION' in reviews_markdown(summary)


@pytest.mark.parametrize('fault',['output_sha','dataset_sha','evidence','missing_reason','missing_score','na_with_score','fake_reviewer_status','duplicate_reviewer'])
def test_invalid_manual_review_bindings_and_ratings_rejected(fault):
    b=bundle('adversarial');r=evaluate(b);t=demo_reviews(r,b);review=t['reviews'][0]
    if fault in ('output_sha','dataset_sha'): review[fault]='f'*64
    elif fault=='evidence':review['ratings']['faithfulness']['evidence'][0]['end']+=1
    elif fault=='missing_reason':review['ratings']['faithfulness']['reason']=None
    elif fault=='missing_score':review['ratings']['faithfulness']['score']=None
    elif fault=='na_with_score':review['ratings']['faithfulness']['applicability']='not_applicable'
    elif fault=='fake_reviewer_status':review['reviewer_status']='verified_human'
    else:t['reviews'].append(deepcopy(review))
    with pytest.raises(QualityInputError):summarize_reviews(r,b,t)


def test_review_packet_includes_context_links_facts_but_not_reference_answers():
    r=evaluate(bundle());packet=review_packet(r,bundle())
    assert '显式回答关联' in packet and 'user_edit' in packet and 'pending' in packet
    assert 'DRAFT' in packet and '不显示Codex参考答案' in packet
    assert 'draft_candidate_recall' not in packet


def test_rubric_every_dimension_has_anchors_na_and_examples():
    rubric=read_json(DATA_DIR/'rubric.json')
    assert rubric['status']=='DRAFT' and set(rubric['dimensions'])==set(DIMENSIONS)
    for d in rubric['dimensions'].values():
        assert set(d['anchors'])=={'0','1','2','3','4'}
        assert d['not_applicable'] and d['positive_example'] and d['negative_example']


def test_cli_offline_and_refuses_overwriting_evidence(tmp_path,monkeypatch,capsys):
    spec=importlib.util.spec_from_file_location('quality_cli',ROOT/'scripts/evaluate_mining_quality.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    target=tmp_path/'new-report'
    monkeypatch.setattr('sys.argv',['quality','--outputs',str(DATA_DIR/'oracle.outputs.json'),'--output-dir',str(target)])
    module.main()
    assert 'provider_requests=0' in capsys.readouterr().out
    first=(target/'metrics.json').read_bytes()
    with pytest.raises(ValueError): module.main()
    assert (target/'metrics.json').read_bytes()==first


def test_unknown_exception_and_json_input_never_echo_details(tmp_path):
    p=tmp_path/'invalid.json';p.write_text('{secret_private_marker',encoding='utf8')
    with pytest.raises(QualityInputError,match='^quality_input_invalid$'): read_json(p)


def test_all_missing_outputs_remain_in_denominators():
    b=bundle();b['outputs']=[];r=evaluate(b)
    assert r['missing_outputs']==12 and r['citation_unscorable_outputs']==12
    assert r['metrics']['strict_schema']['ratio']==0 and r['metrics']['strict_schema']['unscorable']==12
    assert r['metrics']['draft_candidate_precision']['ratio'] is None
    assert r['human_semantic_scores'] is None


@pytest.mark.parametrize('citation',[None,{'turn_id':[],'quote':'7','start':0,'end':1},
    {'turn_id':'bad','quote':7,'start':True,'end':'x'}])
def test_malformed_candidate_types_are_counted_not_crashes(citation):
    b=changed('GQ01',lambda v:v.update(candidates=[dict(citation=citation)]))
    row=evaluate(b)['rows'][0]
    assert not row['schema_valid'] and row['metrics']['draft_candidate_precision']['numerator']==0


def test_review_cannot_switch_supplied_bundle_after_report():
    b=bundle('adversarial');r=evaluate(b);t=demo_reviews(r,b)
    other=deepcopy(b);other['outputs'][0]['content']='{}'
    with pytest.raises(QualityInputError):summarize_reviews(r,other,t)


def test_na_is_distinct_from_unreviewed_and_zero():
    b=bundle('adversarial');r=evaluate(b);t=demo_reviews(r,b)
    rating=t['reviews'][0]['ratings']['context_and_non_repetition']
    rating.update(score=None,applicability='not_applicable',reason='仅演示N/A分母，不计为零分。')
    s=summarize_reviews(r,b,t)['demonstration_reviews']['dimensions']['context_and_non_repetition']
    assert s['scored']==1 and s['not_applicable']==1 and s['mean']==4


@pytest.mark.parametrize('score',[-1,5,True,'4'])
def test_manual_scores_strictly_zero_to_four(score):
    b=bundle('adversarial');r=evaluate(b);t=demo_reviews(r,b)
    t['reviews'][0]['ratings']['faithfulness']['score']=score
    with pytest.raises(QualityInputError):summarize_reviews(r,b,t)


def test_teacher_forced_inputs_never_contain_reference_labels():
    _,cases=load_dataset()
    for c in cases:
        payload=context_for(c).payload()
        assert not set(payload)&{'reference','question_goals','must_not_infer','label_status','suggested_question'}


def test_committed_examples_are_reproducible_and_not_human_results():
    for name in ('oracle','adversarial'):
        r=evaluate(bundle(name))
        assert read_json(DATA_DIR/'examples'/(name+'.report.json'))==r
        assert (DATA_DIR/'examples'/(name+'.report.md')).read_text(encoding='utf8')==markdown_report(r)
    b=bundle('adversarial');r=evaluate(b);demo=read_json(DATA_DIR/'demo-review-records.json')
    summary=summarize_reviews(r,b,demo)
    assert summary==read_json(DATA_DIR/'examples/demo-reviews.report.json')
    assert summary['human_reviews'] is None
