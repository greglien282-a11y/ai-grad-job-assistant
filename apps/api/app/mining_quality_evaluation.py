"""Pure offline scoring of supplied fictional outputs, NOT model evaluation.

No environment, engine, Provider, HTTP, secret, retry or paid control interface.
Mechanical checks and DRAFT reference matches never become semantic ratings.
"""
import hashlib
import json
import re
from html import escape
from typing import Literal
from pydantic import Field,model_validator
from app.model_adapter import parse_output,unique_pairs,OutputJSONError
from app.mining_validation import validate_context_v2,question_key
from app.mining_context import PRIVATE,question_fingerprint
from app.cost_ledger import canonical
from app.mining_quality_data import (Strict,QualityInputError,DATA_DIR,ROOT,DIMENSIONS,
    context_for,digest,load_dataset)

NUMBER=re.compile(r'\d+(?:\.\d+)?')
SECRET=re.compile(r'\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}|(?:api[_ -]?key|password|authorization)\s*[:=]\s*\S+',re.I)


def text_sha(text): return hashlib.sha256(text.encode('utf8')).hexdigest()


class Provenance(Strict):
    output_origin: Literal['authored_oracle','authored_counterexample','mock','imported_model_unverified']
    provider_generated: bool=Field(strict=True)
    provider: str|None=Field(max_length=100)
    model: str=Field(min_length=1,max_length=128)
    prompt_version: Literal['dynamic-mining-prompt-v1-offline']
    prompt_file_sha: str=Field(pattern=r'^[a-f0-9]{64}$')
    schema_sha: str=Field(pattern=r'^[a-f0-9]{64}$')
    generation_verified: Literal[False]

    @model_validator(mode='after')
    def consistent(self):
        if self.provider_generated!=(self.output_origin=='imported_model_unverified'): raise ValueError()
        if self.provider_generated and not self.provider: raise ValueError()
        if not self.provider_generated and self.provider is not None: raise ValueError()
        if any(PRIVATE.search(s) or SECRET.search(s) for s in (self.model,self.provider or '')): raise ValueError()
        return self


class SuppliedOutput(Strict):
    case_id: str
    output_id: str=Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    content: str=Field(max_length=64000,repr=False)

    @model_validator(mode='after')
    def safe_id(self):
        if SECRET.search(self.output_id): raise ValueError()
        return self


class OutputBundle(Strict):
    dataset_version: str
    provenance: Provenance
    outputs: tuple[SuppliedOutput,...]=Field(max_length=20)


def read_json(path,max_bytes=2_000_000):
    try:
        with open(path,'rb') as stream: data=stream.read(max_bytes+1)
        if len(data)>max_bytes: raise ValueError()
        return json.loads(data,object_pairs_hook=unique_pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Exception: raise QualityInputError() from None


def rate(n,d,u=0,na=0,*,unit):
    assert 0<=n<=d and 0<=u<=d
    return dict(numerator=n,denominator=d,unscorable=u,not_applicable=na,
        ratio=n/d if d else None,unit=unit,denominator_includes_unscorable=True)


def citation_key(c):
    return (str(c['turn_id']),c['start'],c['end'],c['quote'])


def literal_match(c,turns):
    return (isinstance(c,dict) and set(c)=={'turn_id','start','end','quote'}
        and isinstance(c['turn_id'],str) and c['turn_id'] in turns
        and type(c['start']) is int and type(c['end']) is int and type(c['quote']) is str
        and 0<=c['start']<c['end']<=len(turns[c['turn_id']])
        and turns[c['turn_id']][c['start']:c['end']]==c['quote'])


def score_case(case,entry):
    context=context_for(case);turns={str(t.turn_id):t.content for t in context.user_turns}
    present=entry is not None
    unsafe=bool(present and (SECRET.search(entry.content) or PRIVATE.search(entry.content)))
    raw=None;parsed=None;schema=False;runtime=None;code='missing_output'
    if present and not unsafe:
        try:
            parsed=parse_output(entry.content);schema=True;code='schema_valid'
        except OutputJSONError: code='output_json_invalid'
        except (ValueError,TypeError,UnicodeError): code='output_schema_invalid'
        try: raw=json.loads(entry.content,object_pairs_hook=unique_pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError,TypeError,UnicodeError): pass
        if schema:
            try: validate_context_v2(context,parsed);runtime=True;code='runtime_valid'
            except ValueError: runtime=False;code='runtime_validation_rejected'
    elif unsafe: code='output_safety_redacted'
    raw_candidates=raw.get('candidates') if isinstance(raw,dict) else None
    candidates=raw_candidates if isinstance(raw_candidates,list) else []
    raw_questions=raw.get('questions') if isinstance(raw,dict) else None
    questions=raw_questions if isinstance(raw_questions,list) else []
    literals=0;malformed=0;predicted=set();flags=[];supported=0;numeric_total=0
    forbidden={f.text:f.kind for f in case.reference.forbidden_claims}
    def numbers(text,sources):
        nonlocal numeric_total,supported
        tokens=NUMBER.findall(text);allowed=set(NUMBER.findall(' '.join(turns.get(s,'') for s in sources if isinstance(s,str))))
        numeric_total+=len(tokens);supported+=sum(t in allowed for t in tokens)
    if unsafe: flags.append(dict(code='sensitive_pattern_redacted',origin='mechanical_rule',human_confirmed=False))
    for candidate in candidates:
        c=candidate.get('citation') if isinstance(candidate,dict) else None
        match=literal_match(c,turns)
        literals+=int(match)
        malformed+=int(not isinstance(c,dict) or not {'turn_id','quote','start','end'}<=set(c))
        if schema and match: predicted.add(citation_key(c))
        if isinstance(c,dict) and type(c.get('quote')) is str:
            numbers(c['quote'],[c.get('turn_id')])
            if c['quote'] in forbidden:
                flags.append(dict(code=forbidden[c['quote']],origin='DRAFT_reference_exact_claim',human_confirmed=False))
        if isinstance(candidate,dict) and (candidate.get('status') in ('user_confirmed','evidence_supported') or candidate.get('confirmed') is True):
            flags.append(dict(code='unrequested_confirmation',origin='mechanical_rule',human_confirmed=False))
    if isinstance(raw,dict) and (raw.get('status') in ('user_confirmed','evidence_supported') or raw.get('confirmed') is True):
        flags.append(dict(code='unrequested_confirmation',origin='mechanical_rule',human_confirmed=False))
    seen={q.dedup_fingerprint for q in context.questions if q.dedup_fingerprint}
    duplicates=0;purpose_matches=0;purposes=set();unknown_questions=0
    for q in questions:
        if not isinstance(q,dict) or not isinstance(q.get('text'),str): unknown_questions+=1;continue
        key=question_fingerprint(q['text'])
        duplicates+=int(key in seen);seen.add(key)
        ids=q.get('source_turn_ids',[])
        numbers(q['text'],ids if isinstance(ids,list) and all(isinstance(x,str) for x in ids) else [])
        if schema:
            purposes.add(q['purpose']);purpose_matches+=int(q['purpose'] in case.reference.question_goals)
    if supported<numeric_total:
        flags.append(dict(code='unsupported_numeric_token',origin='mechanical_rule_not_numeric_semantics',human_confirmed=False))
    by_kind={kind:{citation_key(x.model_dump(mode='json',exclude={'kind'})) for x in case.reference.citations if x.kind==kind} for kind in ('positive','boundary')}
    reference=by_kind['positive']|by_kind['boundary'];hits=predicted & reference
    stop_ok=None
    if schema:
        expectation=case.reference.stop_expectation
        stop_ok=(expectation=='either' or parsed.stop==(expectation=='stop'))
        if parsed.stop: stop_ok=stop_ok and parsed.stop_reason in case.reference.allowed_stop_reasons
    goals=set(case.reference.question_goals)
    metrics=dict(
        strict_schema=rate(int(schema),1,int(not present or unsafe),unit='planned_outputs'),
        runtime_validation=rate(int(runtime is True),1,int(not schema),unit='planned_outputs'),
        literal_citations=rate(literals,len(candidates),malformed,int(raw_candidates==[]),unit='raw_candidates'),
        draft_candidate_precision=rate(len(hits),len(candidates),len(candidates) if not schema else 0,int(raw_candidates==[]),unit='raw_candidates'),
        draft_candidate_recall=rate(len(hits),len(reference),len(reference) if not schema else 0,int(not reference),unit='draft_reference_facts'),
        draft_positive_recall=rate(len(predicted & by_kind['positive']),len(by_kind['positive']),len(by_kind['positive']) if not schema else 0,int(not by_kind['positive']),unit='draft_positive_facts'),
        draft_boundary_recall=rate(len(predicted & by_kind['boundary']),len(by_kind['boundary']),len(by_kind['boundary']) if not schema else 0,int(not by_kind['boundary']),unit='draft_boundary_facts'),
        draft_runtime_accepted_recall=rate(len(hits) if runtime else 0,len(reference),len(reference) if not schema else 0,int(not reference),unit='draft_reference_facts'),
        stop_structure=rate(int(schema),1,int(not present or unsafe),unit='planned_outputs'),
        draft_stop_alignment=rate(int(stop_ok is True),1,int(not schema),unit='planned_outputs'),
        draft_question_purpose=rate(purpose_matches,len(questions),len(questions) if not schema else 0,int(raw_questions==[]),unit='raw_questions'),
        draft_goal_coverage=rate(len(purposes & goals),len(goals),len(goals) if not schema else 0,int(not goals),unit='draft_question_goals'),
        exact_nonduplicate_questions=rate(len(questions)-duplicates-unknown_questions,len(questions),unknown_questions,int(raw_questions==[]),unit='raw_questions'),
        supported_numeric_tokens=rate(supported,numeric_total,0,int(numeric_total==0),unit='numeric_tokens'))
    return dict(case_id=case.case_id,split=case.split,category=case.category,output_id=entry.output_id if entry else None,
        output_sha=text_sha(entry.content) if present and not unsafe else None,present=present,safety_redacted=unsafe,
        validation_code=code,schema_valid=schema,runtime_valid=runtime,
        raw_candidate_count=len(candidates) if isinstance(raw_candidates,list) else None,
        duplicate_question_count=duplicates,reference_label_status='DRAFT',
        metrics=metrics,critical_rule_signals=flags,safety_review_required=bool(flags),
        human_quality={d:None for d in DIMENSIONS},human_review_status='unreviewed')


def evaluate(bundle_data,*,split='development'):
    try:
        data,cases=load_dataset();bundle=OutputBundle.model_validate(bundle_data)
        if split not in ('development','holdout') or bundle.dataset_version!=data['dataset_version']: raise ValueError()
        p=bundle.provenance
        if p.prompt_file_sha!=hashlib.sha256((ROOT/'docs/evaluation/dynamic-mining-prompt-v1.txt').read_bytes()).hexdigest(): raise ValueError()
        if p.schema_sha!=digest(json.loads((ROOT/'docs/evaluation/provider-wire-output.schema.json').read_text(encoding='utf8'))): raise ValueError()
        selected=[c for c in cases if c.split==split];ids={c.case_id for c in selected}
        if (len({e.case_id for e in bundle.outputs})!=len(bundle.outputs)
            or len({e.output_id for e in bundle.outputs})!=len(bundle.outputs)
            or any(e.case_id not in ids for e in bundle.outputs)): raise ValueError()
        if split=='holdout' and p.output_origin in ('authored_oracle','authored_counterexample'): raise ValueError()
        entries={e.case_id:e for e in bundle.outputs}
        rows=[score_case(c,entries.get(c.case_id)) for c in selected]
        metrics={}
        for name in rows[0]['metrics']:
            values=[r['metrics'][name] for r in rows]
            metrics[name]=rate(sum(v['numerator'] for v in values),sum(v['denominator'] for v in values),
                sum(v['unscorable'] for v in values),sum(v['not_applicable'] for v in values),unit=values[0]['unit'])
        return dict(report_version='mining-quality-report-v1',dataset_version=data['dataset_version'],dataset_sha=digest(data),
            split=split,reference_labels='DRAFT_NOT_HUMAN_GOLD',provenance=p.model_dump(),
            output_bundle_sha=digest(bundle.model_dump(mode='json')),planned_outputs=len(rows),
            provided_outputs=len(entries),missing_outputs=sum(not r['present'] for r in rows),
            citation_unscorable_outputs=sum(r['raw_candidate_count'] is None for r in rows),
            empty_candidate_outputs=sum(r['raw_candidate_count']==0 for r in rows),
            metrics=metrics,rows=rows,critical_rule_signal_count=sum(len(r['critical_rule_signals']) for r in rows),
            safety_review_required=any(r['safety_review_required'] for r in rows),
            semantic_quality_status='UNREVIEWED_NO_RELEASE_DECISION',human_semantic_scores=None,real_model_holdout_quality=None,
            evidence_layers=dict(engineering='MECHANICAL_CHECKS_ONLY',oracle='DRAFT_REFERENCE_FIT_NOT_GENERALIZATION' if p.output_origin=='authored_oracle' else 'NOT_ORACLE',
                human_semantics='UNREVIEWED',real_model_quality='NOT_MEASURED_OR_AUTHENTICATED'),
            tool_provider_requests=0,tool_cost_cny='0.000000',actual_model_tokens=None,provider_latency_ms=None,
            limitations=['Exact reference matching uses Codex DRAFT labels, not human truth/quality.',
                'Runtime atomicity is a conservative lexical guard; mismatches are reported, not fixed.',
                'Purpose/numeric-token/exact-duplicate checks do not score semantic question usefulness.',
                'Missing outputs stay in planned-output denominators; unknown candidate counts are separate.',
                'Empty/no-reference denominators yield null, never perfect accuracy.',
                'All generation provenance is supplied, not independently authenticated; no real quality claims.',
                'Public DRAFT holdout is frozen and excluded from examples; not a secret/blind benchmark.'])
    except Exception: raise QualityInputError() from None


def markdown_report(report):
    lines=['# Pathwise 经历挖掘离线检查 V1','',
        '仅工程检查与 DRAFT 标签匹配；不是人工语义评分或真实模型成绩。',
        f"划分：{report['split']}；来源：{report['provenance']['output_origin']}；模型标签：{escape(report['provenance']['model'])}。",
        f"计划 {report['planned_outputs']}，提供 {report['provided_outputs']}，缺失 {report['missing_outputs']}。",
        f"严重风险规则信号 {report['critical_rule_signal_count']}；人工语义分数 null；真实模型质量 null。",'']
    for name,value in report['metrics'].items():
        ratio='N/A' if value['ratio'] is None else f"{value['ratio']:.4f}"
        lines.append(f"- {name}: {value['numerator']}/{value['denominator']} = {ratio}；不可评分 {value['unscorable']}；不适用 {value['not_applicable']}；单位 {value['unit']}。")
    lines+=['','## 逐例结果']
    for row in report['rows']:
        codes=', '.join(x['code'] for x in row['critical_rule_signals']) or '未触发已实现规则（不证明无语义错误）'
        lines.append(f"- {row['case_id']}: {row['validation_code']}；风险：{codes}；human_review=unreviewed。")
    lines+=['','## 局限']+['- '+s for s in report['limitations']]
    return '\n'.join(lines)+'\n'
