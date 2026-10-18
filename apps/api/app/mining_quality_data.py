"""Fixed, fictional, DRAFT quality dataset. No provider, DB or env access."""
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID,uuid5,NAMESPACE_URL
from pydantic import BaseModel,ConfigDict,Field,model_validator
from app.cost_ledger import canonical
from app.mining_context import MiningContext,PRIVATE,question_fingerprint,within_budget
from app.mining_provider import AtomicCitation

ROOT=Path(__file__).resolve().parents[3]
DATA_DIR=ROOT/'docs/evaluation/quality-v1'
DATASET_SHA='e0af925ad6b431ff5d50eb7f59aaa42bd3b2598c2d51edfc878b6bdf59bb6fd7'
PURPOSE=Literal['contribution','detail','uncertainty','verification','correction']
DIMENSIONS=('faithfulness','individual_contribution','question_effectiveness',
    'context_and_non_repetition','uncertainty_and_autonomy','stopping')


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


class QualityInputError(ValueError):
    def __init__(self): super().__init__('quality_input_invalid')


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)


class Answer(Strict):
    question_id: UUID
    question_version: int=Field(strict=True,gt=0)


class Turn(Strict):
    turn_id: UUID
    text: str=Field(min_length=1,max_length=10000)
    answered_questions: tuple[Answer,...]


class ReferenceCitation(AtomicCitation):
    kind: Literal['positive','boundary']


class Fact(Strict):
    fact_id: UUID
    version: int=Field(strict=True,gt=0)
    status: Literal['pending','user_confirmed']
    statement: str
    memory_state: Literal['certain','approximate','needs_check','unspecified']
    source_kind: Literal['conversation_turns','user_edit']
    citation: AtomicCitation


class Question(Strict):
    question_id: UUID
    version: int=Field(strict=True,gt=0)
    state: Literal['active','corrected','skipped','hidden','deleted']
    content: str|None
    answered_turn_id: UUID|None
    answered_version: int|None


class ForbiddenClaim(Strict):
    text: str=Field(min_length=1)
    kind: str=Field(min_length=1)


class Reference(Strict):
    label_status: Literal['DRAFT']
    citations: tuple[ReferenceCitation,...]
    question_goals: tuple[PURPOSE,...]
    question_goal_notes: tuple[str,...]
    must_not_infer: tuple[str,...]
    suggested_question: str|None
    forbidden_claims: tuple[ForbiddenClaim,...]
    misleading_questions: tuple[str,...]
    stop_expectation: Literal['continue','stop','either','not_applicable']
    allowed_stop_reasons: tuple[Literal['enough_information','user_uncertain','no_new_information'],...]
    stop_notes: str


class GateRound(Strict):
    input_turn_id: UUID
    state: Literal['completed']
    added_facts: int=Field(strict=True,ge=0)


class Case(Strict):
    case_id: str=Field(pattern=r'^GQ\d{2}$')
    title: str
    category: str
    complexity: Literal['single_turn','multi_turn']
    synthetic: Literal[True]
    split: Literal['development','holdout']
    evaluation_kind: Literal['model_output','business_gate']
    gate_history: tuple[GateRound,...]=()
    background: str
    turns: tuple[Turn,...]=Field(min_length=1,max_length=8)
    confirmed_facts: tuple[Fact,...]
    pending_facts: tuple[Fact,...]
    previous_questions: tuple[Question,...]
    stop_context: dict
    reference: Reference
    evaluation_notes: str
    review_status: Literal['DRAFT']
    human_reviewer: None

    @model_validator(mode='after')
    def consistent(self):
        turns={t.turn_id:t for t in self.turns}
        questions={q.question_id:q for q in self.previous_questions}
        if len(turns)!=len(self.turns) or len(questions)!=len(self.previous_questions): raise ValueError()
        keys=set()
        for c in self.reference.citations:
            if (c.turn_id not in turns or not 0<=c.start<c.end<=len(turns[c.turn_id].text)
                or turns[c.turn_id].text[c.start:c.end]!=c.quote): raise ValueError()
            key=(c.turn_id,c.start,c.end)
            if key in keys: raise ValueError()
            keys.add(key)
        for t in self.turns:
            for link in t.answered_questions:
                q=questions.get(link.question_id)
                if q is None or q.answered_turn_id!=t.turn_id or q.answered_version!=link.question_version: raise ValueError()
        for f in (*self.confirmed_facts,*self.pending_facts):
            c=f.citation
            if (c.turn_id not in turns or not 0<=c.start<c.end<=len(turns[c.turn_id].text)
                or turns[c.turn_id].text[c.start:c.end]!=c.quote or f.statement!=c.quote): raise ValueError()
        if any(f.status!='user_confirmed' for f in self.confirmed_facts): raise ValueError()
        if any(f.status!='pending' for f in self.pending_facts): raise ValueError()
        if any(PRIVATE.search(t.text) for t in self.turns): raise ValueError()
        if self.evaluation_kind=='business_gate':
            # These snapshots are already stopped, NOT inputs for a model to
            # decide whether to stop. Reference model-output targets are N/A.
            if not self.stop_context.get('user_stopped') or self.reference.stop_expectation!='not_applicable': raise ValueError()
            if self.reference.citations or self.reference.question_goals or self.reference.allowed_stop_reasons: raise ValueError()
        elif self.reference.stop_expectation=='not_applicable': raise ValueError()
        if self.gate_history:
            if self.evaluation_kind!='business_gate' or any(r.input_turn_id not in turns for r in self.gate_history): raise ValueError()
            # build_context counts distinct input IDs, then scans the latest
            # two completed runs for facts. Fixtures are chronological.
            rounds=len({r.input_turn_id for r in self.gate_history})
            empty=0
            for r in reversed(self.gate_history[-2:]):
                if r.added_facts: break
                empty+=1
            if self.stop_context['round_count']!=rounds or self.stop_context['consecutive_empty_rounds']!=empty: raise ValueError()
        return self


def context_for(case):
    # Evaluation-only teacher-forced snapshot, not the server DB context builder.
    turns=list(reversed(case.turns))
    return MiningContext.model_validate(dict(project_id=uuid5(NAMESPACE_URL,'quality-project:'+case.case_id),
        context_revision=len(turns),input_turn_id=turns[0].turn_id,
        user_turns=[dict(turn_id=t.turn_id,content=t.text,answered_questions=[x.model_dump() for x in t.answered_questions]) for t in turns],
        facts=[f.model_dump(exclude={'citation'}) for f in (*case.confirmed_facts,*case.pending_facts)],
        questions=[dict(question_id=q.question_id,version=q.version,state=q.state,
            content=None if q.state in ('hidden','deleted') else q.content,
            dedup_fingerprint=question_fingerprint(q.content) if q.content and q.state!='deleted' else None,
            answered_turn_id=q.answered_turn_id,answered_version=q.answered_version,
            answer_matches_current_version=q.answered_version==q.version if q.answered_version else False) for q in case.previous_questions],
        stop=case.stop_context))


def load_dataset():
    try:
        data=json.loads((DATA_DIR/'dataset.json').read_text(encoding='utf8'))
        manifest=json.loads((DATA_DIR/'split-manifest.json').read_text(encoding='utf8'))
        if (set(data)!={'dataset_version','synthetic','label_status','authorship','cases'} or data['synthetic'] is not True
            or data['label_status']!='DRAFT' or manifest['dataset_sha']!=digest(data) or digest(data)!=DATASET_SHA
            or manifest['dataset_version']!=data['dataset_version']): raise ValueError()
        cases=tuple(Case.model_validate(c) for c in data['cases'])
        ids=[c.case_id for c in cases]
        if len(cases)!=20 or len(set(ids))!=20: raise ValueError()
        if set(manifest['development']) & set(manifest['holdout']): raise ValueError()
        if (len(manifest['development']),len(manifest['holdout']))!=(12,8): raise ValueError()
        for split in ('development','holdout'):
            if manifest[split]!=[c.case_id for c in cases if c.split==split]: raise ValueError()
        if manifest['development']!=[f'GQ{i:02}' for i in range(1,13)] or manifest['holdout']!=[f'GQ{i:02}' for i in range(13,21)]: raise ValueError()
        if manifest['case_shas']!={c.case_id:digest(c.model_dump(mode='json')) for c in cases}: raise ValueError()
        if any(not within_budget(context_for(c)) for c in cases): raise ValueError()
        return data,cases
    except Exception: raise QualityInputError() from None
