"""Synthetic-only, unconnected language experiment; NEVER a writer admission.

No I/O, model, history, identity or trust inference. Eligibility means only that
an explicit declaration matches a finite template and the supplied text slices.
It cannot prove the supplied text is a saved, complete, authorized user Turn.
"""
from dataclasses import dataclass
import re

CONTRACT = 'typed-semantic-spike-v1'
TRANSACTION_REVIEW = (
    'saved_turn_identity_and_full_context', 'authorization_and_session_ownership',
    'rejected_history_and_semantic_reassertion', 'source_reuse_and_independence',
    'versions_relationships_and_classification_basis', 'atomicity_keys_and_receipt_contract',
    'restricted_runtime_and_database_constraints',
)
_PAIRS = frozenset({('personal_action','completed'),('personal_action','in_progress'),
    ('plan','planned'),('plan','in_progress'),('background','not_applicable'),
    ('boundary','not_applicable'),('legacy_unspecified','legacy_unknown')})
_CONTRACTS = frozenset({'legacy-v0','unclassified-v1','explicit-typed-v1'})
_SPACE = ' \t\r\n'
_END = re.compile('[。！？!?]')
_HAZARD = re.compile('如果|假如|可能|应该|大概|不确定|记不清|并|而且|以及|但是|提升|%|％|[“”「」"<>]')
# Exact action/object pairs, not an open object/verb wildcard. In particular,
# modifiers, attribution, negation and measurements cannot hide in a tail.
_ACTION_OBJECT = (
    r'编写(?:借阅状态组件|清洗脚本|脚本|冲突提示|输入校验)',
    r'测试(?:导出按钮|登记表单的空值提示|报名页面|空列表|[1-9][0-9]{0,3}个导出按钮|三个导出按钮)',
    r'验证(?:演示路径|[1-9][0-9]{0,3}个导出按钮)',
    r'部署(?:服务|推荐服务)', r'实现推荐系统', r'优化导入页面',
    r'制作(?:结果图|提示图|项目讲解图|站点说明图|🧪原型图|e\u0301原型图|é原型图|👩‍💻原型图)',
    r'整理[1-9][0-9]{0,3}条缺失记录',
)
# Build variants from literal verbs and their finite object expressions.
_CLAIMS = []
for _entry in _ACTION_OBJECT:
    _verb, _object = _entry[:2], _entry[2:]
    _CLAIMS.append((_verb, _object))
_BASE = '(?:' + '|'.join(v+o for v,o in _CLAIMS) + ')'
_DONE = '(?:' + '|'.join(v+'了'+o for v,o in _CLAIMS) + ')'
_DENIED = '(?:' + '|'.join(v+'(?:过)?'+o for v,o in _CLAIMS) + ')'
_PATTERNS = (
    (('personal_action','completed'), re.compile('我'+_DONE+'。')),
    (('personal_action','in_progress'), re.compile('我正在'+_BASE+'。')),
    (('plan','planned'), re.compile('我计划'+_BASE+'。')),
    (('plan','in_progress'), re.compile('我正在准备'+_BASE+'。')),
    (('background','not_applicable'), re.compile('(?:我们|团队)'+_DONE+'。')),
    (('boundary','not_applicable'), re.compile('我没有'+_DENIED+'。')),
)
_EXACT = {
    '我计划把服务部署到学校服务器，还没有开始。': ('plan','planned'),
    '这是一个课程项目。': ('background','not_applicable'),
    '课程作业是一个借阅页。': ('background','not_applicable'),
    '我不知道。': ('boundary','not_applicable'),
    '我记不清。': ('boundary','not_applicable'),
    '我不确定。': ('boundary','not_applicable'),
    '这部分我不想回答，可以跳过。': ('boundary','not_applicable'),
}


@dataclass(frozen=True)
class Decision:
    status: str
    code: str
    structure_valid: bool
    citations_valid: bool | None
    item_index: int | None = None
    validation_contract: str = CONTRACT
    transaction_review_required: tuple[str, ...] = TRANSACTION_REVIEW
    truth_verified: bool = False
    persistence_authorized: bool = False


def validate_candidate(payload: object) -> Decision:
    """Strict JSON-shaped synthetic envelope. Never rewrites or returns facts.

    All items must cover all non-ASCII-whitespace text as complete sentences.
    Unknown text is unsupported, not classified by a substring or a default.
    No accepted-items projection is returned for a partly invalid batch.
    """
    def result(status,code,structure=False,citations=None,index=None):
        return Decision(status,code,structure,citations,index)
    if (type(payload) is not dict or any(type(k) is not str for k in payload)
            or set(payload)!={'validation_contract','synthetic','raw_text','items'}):
        return result('rejected','envelope_invalid')
    if type(payload['validation_contract']) is not str or payload['validation_contract']!=CONTRACT:
        return result('unsupported','validation_contract_unsupported')
    if payload['synthetic'] is not True:
        return result('rejected','synthetic_input_required')
    raw,items=payload['raw_text'],payload['items']
    if type(raw) is not str or not 1<=len(raw)<=10000 or '\x00' in raw:
        return result('rejected','raw_text_invalid')
    try:raw.encode('utf-8')
    except UnicodeEncodeError:return result('rejected','raw_text_invalid')
    if type(items) is not list or not 1<=len(items)<=5:
        return result('rejected','items_invalid')
    fields={'fact_kind','progress_stage','classification_contract','quote','start','end'}
    for i,item in enumerate(items):
        if type(item) is not dict or any(type(k) is not str for k in item) or set(item)!=fields:
            return result('rejected','item_structure_invalid',index=i)
        if any(type(item[k]) is not str for k in fields-{'start','end'}):
            return result('rejected','item_structure_invalid',index=i)
        pair=(item['fact_kind'],item['progress_stage']);cc=item['classification_contract']
        if (pair not in _PAIRS or cc not in _CONTRACTS
                or ((pair[0]=='legacy_unspecified') != (cc in ('legacy-v0','unclassified-v1')))):
            return result('rejected','classification_combination_invalid',index=i)
        if type(item['start']) is not int or type(item['end']) is not int or not 1<=len(item['quote'])<=500:
            return result('rejected','item_structure_invalid',index=i)
    # Scan the entire supplied text, not only quotes: a prefix, trailing
    # qualifier or extra sentence cannot be silently omitted by the caller.
    sentences=[];cursor=0
    while cursor<len(raw):
        while cursor<len(raw) and raw[cursor] in _SPACE:cursor+=1
        if cursor==len(raw):break
        end=_END.search(raw,cursor)
        if end is None:return result('rejected','sentence_boundary_invalid',True,False)
        sentences.append((cursor,end.end()));cursor=end.end()
    ranges=[]
    for i,item in enumerate(items):
        start,end=item['start'],item['end']
        if not 0<=start<end<=len(raw) or raw[start:end]!=item['quote']:
            return result('rejected','quote_mismatch',True,False,i)
        ranges.append((start,end))
    if ranges!=sentences:
        return result('rejected','full_text_sentence_coverage_required',True,False)
    if len({item['quote'] for item in items})!=len(items):
        return result('rejected','duplicate_quote',True,True)
    if any(item['fact_kind']=='legacy_unspecified' for item in items):
        return result('unsupported','legacy_not_classified',True,True)
    if len(items)>1 and any(item['fact_kind']!='personal_action' for item in items):
        return result('unsupported','non_personal_batch_unsupported',True,True)
    for i,item in enumerate(items):
        quote=item['quote'];declared=(item['fact_kind'],item['progress_stage'])
        matches={pair for pair,pattern in _PATTERNS if pattern.fullmatch(quote)}
        if quote in _EXACT:matches.add(_EXACT[quote])
        if declared in matches:continue
        if matches:return result('requires_clarification','declaration_conflict',True,True,i)
        if _HAZARD.search(quote):
            return result('requires_clarification','language_requires_clarification',True,True,i)
        return result('unsupported','language_not_supported',True,True,i)
    return result('eligible_candidate','finite_rule_match',True,True)
