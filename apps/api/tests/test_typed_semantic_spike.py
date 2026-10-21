"""Synthetic semantic spike only; frozen quality cases stay unmodified."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import re

import pytest

from app.typed_semantic_spike import CONTRACT, validate_candidate

ROOT=Path(__file__).parents[3]
DATASET=ROOT/'docs/evaluation/quality-v1/dataset.json'


def candidate(raw,kind='personal_action',stage='completed',*,quotes=None,cc='explicit-typed-v1'):
    quotes=quotes if quotes is not None else [raw]
    items=[];cursor=0
    for q in quotes:
        start=raw.index(q,cursor);cursor=start+len(q)
        items.append(dict(fact_kind=kind,progress_stage=stage,classification_contract=cc,
                          quote=q,start=start,end=cursor))
    return dict(validation_contract=CONTRACT,synthetic=True,raw_text=raw,items=items)


@pytest.mark.parametrize('text,kind,stage',[
    ('我整理了27条缺失记录。','personal_action','completed'),
    ('我编写了清洗脚本。','personal_action','completed'),
    ('我部署了服务。','personal_action','completed'),
    ('我正在部署服务。','personal_action','in_progress'),
    ('我计划部署服务。','plan','planned'),
    ('我正在准备部署服务。','plan','in_progress'),
    ('我计划把服务部署到学校服务器，还没有开始。','plan','planned'),
    ('我们部署了服务。','background','not_applicable'),
    ('团队整理了27条缺失记录。','background','not_applicable'),
    ('这是一个课程项目。','background','not_applicable'),
    ('我没有部署服务。','boundary','not_applicable'),
    ('我没有部署过推荐服务。','boundary','not_applicable'),
    ('我不知道。','boundary','not_applicable'),
    ('我不确定。','boundary','not_applicable'),
])
def test_finite_positive_rules_do_not_authorize_persistence_or_truth(text,kind,stage):
    r=validate_candidate(candidate(text,kind,stage))
    assert r.status=='eligible_candidate' and r.structure_valid and r.citations_valid
    assert not r.truth_verified and not r.persistence_authorized
    assert 'rejected_history_and_semantic_reassertion' in r.transaction_review_required
    assert 'saved_turn_identity_and_full_context' in r.transaction_review_required


@pytest.mark.parametrize('kind,stage',[
    ('personal_action','planned'),('personal_action','not_applicable'),
    ('plan','completed'),('plan','not_applicable'),('background','completed'),
    ('boundary','in_progress'),('legacy_unspecified','completed'),
    ('unknown','completed'),('personal_action','unknown')])
def test_invalid_structural_combinations(kind,stage):
    r=validate_candidate(candidate('我部署了服务。',kind,stage))
    assert (r.status,r.code,r.structure_valid,r.citations_valid)==('rejected','classification_combination_invalid',False,None)


@pytest.mark.parametrize('cc',['legacy-v0','unclassified-v1','explicit-typed-v1','future-v2'])
@pytest.mark.parametrize('legacy',[False,True])
def test_classification_contract_pairs_and_no_legacy_inference(cc,legacy):
    p=candidate('我部署了服务。','legacy_unspecified' if legacy else 'personal_action',
                'legacy_unknown' if legacy else 'completed',cc=cc)
    r=validate_candidate(p)
    valid=(legacy and cc in ('legacy-v0','unclassified-v1')) or (not legacy and cc=='explicit-typed-v1')
    assert r.structure_valid==valid
    if valid and legacy:assert r.status=='unsupported' and r.code=='legacy_not_classified'
    elif valid:assert r.status=='eligible_candidate'
    else:assert r.code=='classification_combination_invalid'


@pytest.mark.parametrize('text',[
    '我计划部署服务。','我正在部署服务。','我们部署了服务。','团队部署了服务。',
    '我没有部署服务。','如果我部署服务。','如果我部署了服务。',
    '我可能部署过服务。','我应该部署过服务。','我大概部署了服务。',
    '我编写并测试了系统。','我部署了服务，但是没有上线。',
    '我部署了服务，提升了80%。','我整理了27条缺失记录，提升了80%。',
    '据说我部署了服务。','我听说团队部署了服务。','“我部署了服务。”',
    '他说我部署了服务。','我部署了团队完成的服务。','我部署了没有测试的服务。',
    '我并非没有部署服务。','我正在计划部署服务。','我负责部署服务。',
    '我测试了同学负责的导出按钮。','我只测试了导出按钮。',
])
def test_cannot_promote_qualifiers_or_unknown_scope_into_completed(text):
    r=validate_candidate(candidate(text))
    assert r.status in ('rejected','unsupported','requires_clarification')
    assert not r.persistence_authorized and not r.truth_verified


@pytest.mark.parametrize('text,kind,stage',[
    ('我部署了服务。','plan','planned'),('我正在部署服务。','plan','in_progress'),
    ('我计划部署服务。','background','not_applicable'),('我们部署了服务。','personal_action','in_progress'),
    ('我没有部署服务。','personal_action','completed'),('我计划部署服务。','personal_action','completed')])
def test_explicit_declaration_cannot_override_a_known_conflicting_template(text,kind,stage):
    r=validate_candidate(candidate(text,kind,stage))
    assert r.code=='declaration_conflict' and r.status=='requires_clarification'
    assert r.structure_valid and r.citations_valid


@pytest.mark.parametrize('attack',['digit','metric','prefix','tail','punctuation','overlap','reorder','duplicate','whitespace','unterminated'])
def test_full_source_and_sentence_coverage_refuse_truncation_or_invention(attack):
    raw='我整理了27条缺失记录。';p=candidate(raw)
    if attack=='digit':p['items'][0]['quote']=raw.replace('27','28')
    elif attack=='metric':p['items'][0]['quote']=raw[:-1]+'，提升80%。'
    elif attack=='prefix':p=candidate('如果'+raw,quotes=[raw])
    elif attack=='tail':p=candidate(raw+'其实没有开始。',quotes=[raw])
    elif attack=='punctuation':p=candidate(raw,quotes=[raw[:-1]])
    elif attack=='whitespace':p=candidate(raw+'\u200b')
    elif attack=='unterminated':p=candidate(raw[:-1])
    else:
        other='我测试了导出按钮。';p=candidate(raw+other,quotes=[raw,other])
        if attack=='overlap':p['items'][1]['start']=0
        elif attack=='reorder':p['items'].reverse()
        else:p=candidate(raw+raw,quotes=[raw,raw])
    r=validate_candidate(p)
    assert r.status=='rejected' and r.structure_valid
    assert r.code in ('quote_mismatch','full_text_sentence_coverage_required','duplicate_quote','sentence_boundary_invalid')


@pytest.mark.parametrize('artifact',['🧪','e\u0301','é','👩‍💻'])
def test_unicode_code_points_and_crlf_are_preserved(artifact):
    q='我制作了'+artifact+'原型图。';raw=' \r\n'+q+'\r\n我测试了导出按钮。\t'
    p=candidate(raw,quotes=[q,'我测试了导出按钮。']);before=deepcopy(p)
    assert p['items'][0]['start']==3 and p['items'][0]['end']==3+len(q)
    assert validate_candidate(p).status=='eligible_candidate' and p==before
    if artifact in ('🧪','👩‍💻'):
        p['items'][0]['end']=3+len(q.encode('utf-16-le'))//2
        assert validate_candidate(p).code=='quote_mismatch'


def test_no_unicode_normalization_and_no_surrogate_or_nul():
    p=candidate('我制作了e\u0301原型图。');p['items'][0]['quote']='我制作了é原型图。'
    assert validate_candidate(p).code=='quote_mismatch'
    for text in ('我制作了\ud800原型图。','我部署了\x00服务。'):
        assert validate_candidate(candidate(text)).code=='raw_text_invalid'


@pytest.mark.parametrize('fault',['missing_version','version','version_bool','synthetic','extra',
    'no_items','too_many','kind_type','stage_type','quote_type','bool_start','float_end',
    'negative_start','end_outside','memory_state','related_plan','session_id','classification_missing'])
def test_strict_envelope_no_context_or_memory_escape_hatches(fault):
    p=candidate('我部署了服务。')
    if fault=='missing_version':del p['validation_contract']
    elif fault=='version':p['validation_contract']='CO-v3'
    elif fault=='version_bool':p['validation_contract']=True
    elif fault=='synthetic':p['synthetic']=1
    elif fault=='extra':p['force']=True
    elif fault=='no_items':p['items']=[]
    elif fault=='too_many':p['items']*=6
    elif fault in ('memory_state','related_plan','session_id'):p['items'][0][fault]='certain'
    elif fault=='classification_missing':del p['items'][0]['classification_contract']
    else:
        k,v={'kind_type':('fact_kind',None),'stage_type':('progress_stage',1),
             'quote_type':('quote',[]),'bool_start':('start',False),'float_end':('end',7.0),
             'negative_start':('start',-1),'end_outside':('end',999)}[fault]
        p['items'][0][k]=v
    assert validate_candidate(p).status in ('rejected','unsupported')


@pytest.mark.parametrize('value',[None,True,1,1.0,'text',[],{},[{}]])
def test_malformed_json_values_return_decisions(value):
    assert validate_candidate(value).status=='rejected'


def test_gq08_two_independent_sources_no_plan_update_or_inherited_details():
    old='我计划把服务部署到学校服务器，还没有开始。';new='我部署了服务。'
    p=candidate(old,'plan','planned');before=deepcopy(p)
    assert validate_candidate(p).status=='eligible_candidate'
    assert validate_candidate(candidate(new)).status=='eligible_candidate'
    assert p==before and '学校服务器' not in new
    bad=candidate(new);bad['items'][0]['quote']='我部署了学校服务器上的服务。'
    assert validate_candidate(bad).code=='quote_mismatch'
    # Combined history is deliberately outside the single-source experiment.
    mixed=candidate(old+new,quotes=[old,new]);mixed['items'][0].update(fact_kind='plan',progress_stage='planned')
    assert validate_candidate(mixed).code=='non_personal_batch_unsupported'


def test_gq11_independent_complete_sentences_and_no_partial_acceptance():
    qs=['我编写了清洗脚本。','我测试了导出按钮。','我制作了结果图。']
    assert validate_candidate(candidate(''.join(qs),quotes=qs)).status=='eligible_candidate'
    qs[1]='我编写并测试了系统。'
    r=validate_candidate(candidate(''.join(qs),quotes=qs))
    assert r.status=='requires_clarification' and r.item_index==1
    assert not hasattr(r,'accepted_items')


def test_R03_history_and_synonyms_are_not_decided_by_this_function():
    for text in ('我测试了3个导出按钮。','我测试了三个导出按钮。','我验证了3个导出按钮。'):
        r=validate_candidate(candidate(text))
        assert r.status=='eligible_candidate'
        assert 'rejected_history_and_semantic_reassertion' in r.transaction_review_required
        assert not r.persistence_authorized
    # A new Turn is neither an input accepted by this function nor a proof of
    # independence. No fake historical verdict is returned.
    p=candidate('我测试了3个导出按钮。');p['turn_id']='new-turn'
    assert validate_candidate(p).code=='envelope_invalid'


def test_caller_supplied_raw_text_is_not_a_saved_turn_or_numeric_truth_proof():
    for n in ('27','28'):
        r=validate_candidate(candidate(f'我整理了{n}条缺失记录。'))
        assert r.status=='eligible_candidate'
        assert 'saved_turn_identity_and_full_context' in r.transaction_review_required
        assert not r.truth_verified and not r.persistence_authorized


GQ_EXPECTATIONS=[
    ('GQ01',1,'personal_action','completed','eligible_candidate'),
    ('GQ02',0,'background','not_applicable','unsupported'),
    ('GQ03',0,'personal_action','completed','eligible_candidate'),
    ('GQ04',0,'personal_action','completed','eligible_candidate'),
    ('GQ05',0,'background','not_applicable','eligible_candidate'),
    ('GQ06',0,'personal_action','completed','eligible_candidate'),
    ('GQ07',0,'boundary','not_applicable','requires_clarification'),
    ('GQ08',0,'plan','planned','eligible_candidate'),
    ('GQ09',0,'boundary','not_applicable','eligible_candidate'),
    ('GQ10',0,'background','not_applicable','unsupported'),
    ('GQ11',0,'personal_action','completed','eligible_candidate'),
    ('GQ12',1,'personal_action','completed','unsupported'),
    ('GQ13',1,'boundary','not_applicable','eligible_candidate'),
    ('GQ14',1,'personal_action','completed','eligible_candidate'),
    ('GQ15',1,'boundary','not_applicable','unsupported'),
    ('GQ16',5,'personal_action','completed','eligible_candidate'),
    ('GQ17',1,'boundary','not_applicable','unsupported'),
    ('GQ18',1,'boundary','not_applicable','unsupported'),
    ('GQ19',0,'personal_action','in_progress','unsupported'),
    ('GQ20',0,'personal_action','completed','eligible_candidate'),
]


@pytest.mark.parametrize('cid,turn,kind,stage,status',GQ_EXPECTATIONS)
def test_frozen_GQ_inputs_with_separate_spike_expectations(cid,turn,kind,stage,status):
    cases=json.loads(DATASET.read_text(encoding='utf-8'))['cases']
    c=next(c for c in cases if c['case_id']==cid);raw=c['turns'][turn]['text']
    qs=[m.group() for m in re.finditer('[^。]+。',raw)]
    assert validate_candidate(candidate(raw,kind,stage,quotes=qs)).status==status


def test_pure_repeatable_input_immutable_result_and_no_runtime_import():
    p=candidate('我整理了27条缺失记录。');before=deepcopy(p);r=validate_candidate(p)
    assert validate_candidate(p)==r and p==before
    with pytest.raises(FrozenInstanceError):r.status='verified'
    module=ROOT/'apps/api/app/typed_semantic_spike.py'
    tree=ast.parse(module.read_text(encoding='utf-8'))
    imports={n.module if isinstance(n,ast.ImportFrom) else a.name
             for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))
             for a in (n.names if isinstance(n,ast.Import) else [None])}
    assert imports=={'dataclasses','re'}
    for source in (ROOT/'apps/api/app').rglob('*.py'):
        if source==module:continue
        assert 'typed_semantic_spike' not in source.read_text(encoding='utf-8')
