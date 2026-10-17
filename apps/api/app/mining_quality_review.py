"""Manual review templates and disagreement exports; never invent reviewers."""
from html import escape
import json
from typing import Literal
from pydantic import Field,model_validator
from app.mining_quality_data import Strict,DIMENSIONS,load_dataset,QualityInputError,digest
from app.mining_quality_evaluation import OutputBundle,text_sha,SECRET
from app.mining_context import PRIVATE

RUBRIC_VERSION='grad-mining-quality-rubric-v1-draft'
CRITICAL=('fabricated_metric','team_as_personal','unsupported_confirmation','sensitive_disclosure',
    'fabricated_technology','invented_evidence','ignores_stop','other')


class Evidence(Strict):
    source: Literal['user_turn','output']
    source_id: str
    quote: str=Field(min_length=1)
    start: int=Field(strict=True,ge=0)
    end: int=Field(strict=True,gt=0)


class Rating(Strict):
    score: int|None=Field(default=None,strict=True,ge=0,le=4)
    applicability: Literal['unreviewed','applicable','not_applicable']='unreviewed'
    reason: str|None=None
    evidence: tuple[Evidence,...]=()

    @model_validator(mode='after')
    def valid(self):
        if self.applicability=='applicable' and (self.score is None or not self.reason or not self.evidence): raise ValueError()
        if self.applicability!='applicable' and self.score is not None: raise ValueError()
        if self.applicability=='not_applicable' and (not self.reason or not self.evidence): raise ValueError()
        return self


class SevereError(Strict):
    code: Literal['fabricated_metric','team_as_personal','unsupported_confirmation','sensitive_disclosure',
        'fabricated_technology','invented_evidence','ignores_stop','other']
    reason: str=Field(min_length=1)
    evidence: tuple[Evidence,...]=Field(min_length=1)


class Review(Strict):
    dataset_sha: str=Field(pattern=r'^[a-f0-9]{64}$')
    output_sha: str=Field(pattern=r'^[a-f0-9]{64}$')
    output_id: str
    case_id: str
    rubric_version: Literal['grad-mining-quality-rubric-v1-draft']=RUBRIC_VERSION
    demonstration: bool=Field(strict=True,default=False)
    reviewer_ref: str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{1,64}$')
    reviewer_status: Literal['unreviewed','demonstration','operator_submitted_unverified']='unreviewed'
    submission_status: Literal['draft','submitted']='draft'
    ratings: dict[str,Rating]
    severe_errors: tuple[SevereError,...]=()
    needs_second_review: bool|None=None

    @model_validator(mode='after')
    def valid(self):
        if set(self.ratings)!=set(DIMENSIONS): raise ValueError()
        if self.submission_status=='submitted':
            if not self.reviewer_ref or self.needs_second_review is None: raise ValueError()
            if self.reviewer_status!=('demonstration' if self.demonstration else 'operator_submitted_unverified'): raise ValueError()
            if any(r.applicability=='unreviewed' for r in self.ratings.values()): raise ValueError()
        elif any(r.score is not None or r.applicability!='unreviewed' for r in self.ratings.values()): raise ValueError()
        return self


def templates(report):
    return dict(template_version='quality-review-template-v1',
        instructions='Fill reviewer status, evidence and reasons. Scores remain null until actual review. Demo records must stay demonstration=true.',
        reviews=[Review(dataset_sha=report['dataset_sha'],output_sha=r['output_sha'],output_id=r['output_id'],
            case_id=r['case_id'],ratings={d:Rating() for d in DIMENSIONS}).model_dump(mode='json') for r in report['rows'] if r['output_sha'] is not None])


def review_packet(report,bundle_data):
    _,cases=load_dataset();by_id={c.case_id:c for c in cases};bundle=OutputBundle.model_validate(bundle_data)
    entries={e.case_id:e for e in bundle.outputs}
    lines=['# 人工评审材料（未评分）','','先独立阅读上下文与输出，再参考DRAFT标签；本材料不显示Codex参考答案。',
        '按 rubric.json 六维评分，每个0–4或N/A都写理由。缺失输出不评分，不伪造评审人。',
        'case/output SHA 必须与同次报告绑定；严重错误单独记录，不能用平均分冲抵。','']
    for r in report['rows']:
        c=by_id[r['case_id']];e=entries.get(c.case_id)
        lines+=[f'## {c.case_id} — {escape(c.title)}',f'划分 {c.split}；背景：{escape(c.background)}。',
            f"输出ID {r['output_id']}；输出SHA {r['output_sha']}；标签审核状态DRAFT。",'','用户原话（全部虚构）：']
        for t in c.turns:
            lines.append(f'- {t.turn_id}: {escape(t.text)}；显式回答关联：{escape(json.dumps([a.model_dump(mode="json") for a in t.answered_questions],ensure_ascii=False))}')
        lines+=['','已有问题及版本：']
        for q in c.previous_questions:
            text='[正文已隐藏/删除]' if q.state in ('hidden','deleted') else q.content or '[无正文]'
            lines.append(f'- {q.question_id} v{q.version} {q.state}: {escape(text)}；回答版本 {q.answered_version}。')
        lines+=['','当前事实（确认状态由合成案例提供，不由模型决定）：']
        for f in (*c.confirmed_facts,*c.pending_facts):
            lines.append(f'- {f.status} / {f.source_kind} v{f.version}: {escape(f.statement)}；来源 {f.citation.turn_id}[{f.citation.start},{f.citation.end})。')
        lines+=['',f'停止上下文：{escape(json.dumps(c.stop_context,ensure_ascii=False))}','',
            '待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：']
        content='[MISSING_OUTPUT]' if e is None else '[OUTPUT_REDACTED_BY_SAFETY_CHECK]' if r['safety_redacted'] else e.content
        # Indentation + HTML escaping prevents model-supplied Markdown/HTML from
        # becoming active review-page markup. No raw provider envelope or key.
        lines+=['']+['    '+escape(s,quote=False) for s in content.splitlines()]+['','评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。','']
    return '\n'.join(lines).rstrip()+'\n'


def summarize_reviews(report,bundle_data,review_data):
    try:
        if (set(review_data)!={'template_version','instructions','reviews'} or review_data['template_version']!='quality-review-template-v1'
            or not isinstance(review_data['reviews'],list) or len(review_data['reviews'])>100): raise ValueError()
        if SECRET.search(json.dumps(review_data,ensure_ascii=False)) or PRIVATE.search(json.dumps(review_data,ensure_ascii=False)): raise ValueError()
        reviews=[Review.model_validate(r) for r in review_data['reviews']]
        rows={r['output_id']:r for r in report['rows'] if r['output_id'] is not None}
        _,cases=load_dataset();contexts={c.case_id:c for c in cases}
        bundle=OutputBundle.model_validate(bundle_data);outputs={e.output_id:e for e in bundle.outputs}
        if digest(bundle.model_dump(mode='json'))!=report['output_bundle_sha']: raise ValueError()
        unique=set()
        for r in reviews:
            row=rows.get(r.output_id)
            if (row is None or r.dataset_sha!=report['dataset_sha'] or r.case_id!=row['case_id'] or r.output_sha!=row['output_sha']): raise ValueError()
            key=(r.output_id,r.reviewer_ref,r.demonstration)
            if key in unique: raise ValueError()
            unique.add(key)
            sources={str(t.turn_id):t.text for t in contexts[r.case_id].turns}
            evidence=[e for score in r.ratings.values() for e in score.evidence]+[e for error in r.severe_errors for e in error.evidence]
            for e in evidence:
                source=sources.get(e.source_id) if e.source=='user_turn' else outputs[r.output_id].content if e.source_id==r.output_id else None
                if source is None or not 0<=e.start<e.end<=len(source) or source[e.start:e.end]!=e.quote: raise ValueError()
        def group(demo):
            submitted=[r for r in reviews if r.demonstration==demo and r.submission_status=='submitted']
            if not submitted: return None
            dims={}
            for d in DIMENSIONS:
                values=[r.ratings[d].score for r in submitted if r.ratings[d].score is not None]
                dims[d]=dict(mean=sum(values)/len(values) if values else None,scored=len(values),
                    not_applicable=sum(r.ratings[d].applicability=='not_applicable' for r in submitted))
            disagreements=[]
            for oid in sorted({r.output_id for r in submitted}):
                subset=[r for r in submitted if r.output_id==oid]
                for d in DIMENSIONS:
                    if len({(r.ratings[d].applicability,r.ratings[d].score) for r in subset})>1:
                        disagreements.append(dict(output_id=oid,dimension=d,ratings=[dict(reviewer_ref=r.reviewer_ref,
                            applicability=r.ratings[d].applicability,score=r.ratings[d].score) for r in subset]))
            critical=[dict(case_id=r.case_id,output_id=r.output_id,reviewer_ref=r.reviewer_ref,**e.model_dump(mode='json')) for r in submitted for e in r.severe_errors]
            return dict(status='DEMONSTRATION_NOT_HUMAN_RESULTS' if demo else 'OPERATOR_SUBMITTED_NOT_AUTHENTICATED',
                submitted_reviews=len(submitted),dimensions=dims,critical_errors=critical,
                severe_errors_block_acceptance=bool(critical),disagreements=disagreements,
                second_review_requested=sum(r.needs_second_review is True for r in submitted),
                acceptance_decision='NOT_ISSUED',reviewer_agreement_rate=None)
        return dict(report_version='quality-manual-review-summary-v1',rubric_version=RUBRIC_VERSION,
            dataset_sha=report['dataset_sha'],output_bundle_sha=report['output_bundle_sha'],
            generation_provenance=report['provenance'],
            human_reviews=group(False),demonstration_reviews=group(True),
            draft_reviews=sum(r.submission_status=='draft' for r in reviews),
            validated_records=[r.model_dump(mode='json') for r in reviews],real_model_quality=None,
            limitations=['No reviewer authentication or signatures; never synthesize agreement statistics.',
                'Demonstrations never enter human scores; serious errors are not averaged away.'])
    except Exception: raise QualityInputError() from None


def reviews_markdown(summary):
    lines=['# 人工评审/分歧导出','','演示与正式提交分开；未验证评审人身份，不签发质量达标结论。']
    for key in ('human_reviews','demonstration_reviews'):
        g=summary[key];lines+=['',f'## {key}']
        if g is None: lines+=['null：没有已提交记录。'];continue
        lines+=[g['status'],f"严重错误 {len(g['critical_errors'])}；阻断接受 {g['severe_errors_block_acceptance']}；分歧 {len(g['disagreements'])}。"]
        for d,s in g['dimensions'].items(): lines.append(f"- {d}: mean={s['mean']}；评分数={s['scored']}；N/A={s['not_applicable']}。")
        for d in g['disagreements']: lines.append(f"- 需复核：{d['output_id']} / {d['dimension']}。")
    return '\n'.join(lines)+'\n'
