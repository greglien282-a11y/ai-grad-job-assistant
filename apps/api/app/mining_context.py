"""Ephemeral, bounded provider context; never persisted or logged."""
import json
import hashlib
import re
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select

from app.models import AnswerQuestion, ConversationTurn, ExperienceFact, ExperienceProject, FactChange, MiningQuestion, MiningRun

MAX_CHARS = 16000
MAX_BYTES = 64000
MAX_TURNS = 8
MAX_FACTS = 32
MAX_QUESTIONS = 24
# Baseline minimization, NOT a guarantee of anonymization. Mask in code points so
# source offsets survive. Names/free-form private details still require consent.
PRIVATE = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://\S+|(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\w)')


def redact(text):
    return PRIVATE.sub(lambda match: '█' * len(match.group()), text)


def question_fingerprint(text):
    normalized = unicodedata.normalize('NFKC', text).casefold()
    key = ''.join(c for c in normalized if not c.isspace() and not unicodedata.category(c).startswith('P'))
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


class Frozen(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class AnswerRef(Frozen):
    question_id: UUID
    question_version: int = Field(strict=True, gt=0)


class UserContext(Frozen):
    turn_id: UUID
    content: str = Field(min_length=1, max_length=10000)
    answered_questions: tuple[AnswerRef, ...] = ()


class QuestionContext(Frozen):
    question_id: UUID
    version: int = Field(strict=True, gt=0)
    state: Literal['active', 'corrected', 'skipped', 'hidden', 'deleted']
    content: str | None = Field(max_length=500)
    dedup_fingerprint: str | None
    answered_turn_id: UUID | None
    answered_version: int | None
    # False means an old answer must not be interpreted as answering new wording.
    answer_matches_current_version: bool


class FactContext(Frozen):
    fact_id: UUID
    version: int = Field(strict=True, gt=0)
    status: Literal['pending', 'user_confirmed', 'evidence_supported', 'rejected']
    statement: str | None = Field(max_length=10000)
    memory_state: Literal['unspecified', 'certain', 'approximate', 'needs_check']
    source_kind: Literal['conversation_turns', 'user_edit']


class StopContext(Frozen):
    round_count: int
    maximum_rounds: Literal[6] = 6
    consecutive_empty_rounds: int
    user_stopped: bool
    session_ended: bool


class MiningContext(Frozen):
    schema_version: Literal[2] = 2
    project_id: UUID
    context_revision: int = Field(strict=True, gt=0)
    input_turn_id: UUID
    user_turns: tuple[UserContext, ...] = Field(min_length=1, max_length=MAX_TURNS)
    questions: tuple[QuestionContext, ...] = Field(max_length=MAX_QUESTIONS)
    facts: tuple[FactContext, ...] = Field(max_length=MAX_FACTS)
    stop: StopContext
    omitted_turns: int = 0
    omitted_facts: int = 0
    omitted_questions: int = 0
    untrusted_user_data: Literal[True] = True

    def payload(self):
        # Sole future adapter payload: no legacy raw input, Bearer or operations.
        return self.model_dump(mode='json')


def within_budget(context):
    texts = [t.content for t in context.user_turns] + [q.content or '' for q in context.questions] + [f.statement or '' for f in context.facts]
    wire = json.dumps(context.payload(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return sum(map(len, texts)) <= MAX_CHARS and len(wire) <= MAX_BYTES


def build_context(db, run, session):
    if session.id != run.session_id or session.context_revision != run.reserved_revision:
        raise ValueError('Context revision mismatch')
    project = db.get(ExperienceProject, run.project_id)
    if project is None or project.session_id != run.session_id:
        raise ValueError('Context project mismatch')
    from app.fact_classification import require_legacy
    require_legacy(db, session.id)
    current = db.get(ConversationTurn, run.input_turn_id)
    if current is None or current.session_id != run.session_id or current.role != 'user':
        raise ValueError('Invalid context source')

    def user(turn):
        links = db.scalars(select(AnswerQuestion).where(AnswerQuestion.turn_id == turn.id).order_by(AnswerQuestion.slot)).all()
        return UserContext(turn_id=turn.id, content=redact(turn.content),
            answered_questions=tuple(AnswerRef(question_id=l.question_id, question_version=l.question_version) for l in links))

    rounds = db.scalar(select(func.count(func.distinct(MiningRun.input_turn_id))).where(MiningRun.session_id == run.session_id))
    empty = 0
    for previous in db.scalars(select(MiningRun).where(MiningRun.session_id == run.session_id, MiningRun.state == 'completed').order_by(MiningRun.created_at.desc(), MiningRun.id.desc()).limit(2)):
        if db.scalar(select(ExperienceFact.id).where(ExperienceFact.ai_run_id == previous.id).limit(1)):
            break
        empty += 1
    total_turns = db.scalar(select(func.count()).select_from(ConversationTurn).where(ConversationTurn.session_id == run.session_id, ConversationTurn.role == 'user'))
    total_facts = db.scalar(select(func.count()).select_from(ExperienceFact).where(ExperienceFact.project_id == run.project_id))
    total_questions = db.scalar(select(func.count()).select_from(MiningQuestion).where(MiningQuestion.session_id == run.session_id))
    context = MiningContext(project_id=run.project_id, context_revision=run.reserved_revision, input_turn_id=run.input_turn_id,
        user_turns=(user(current),), questions=(), facts=(),
        stop=StopContext(round_count=rounds, consecutive_empty_rounds=empty, user_stopped=session.mining_status == 'stopped', session_ended=session.status == 'ended'))
    if not within_budget(context):
        # Never cut the current answer mid-sentence or silently drop it.
        raise ValueError('Current answer exceeds context budget')

    def add(field, item):
        nonlocal context
        proposed = context.model_copy(update={field: getattr(context, field) + (item,)})
        if within_budget(proposed):
            context = proposed
            return True
        return False

    # Current question/version/link metadata precede text and historical material.
    qs = db.scalars(select(MiningQuestion).where(MiningQuestion.session_id == run.session_id).order_by(MiningQuestion.created_at.desc(), MiningQuestion.id.desc()).limit(MAX_QUESTIONS)).all()
    for q in qs:
        link = db.scalar(select(AnswerQuestion).where(AnswerQuestion.question_id == q.id))
        add('questions', QuestionContext(question_id=q.id, version=q.version, state=q.state, content=None,
            dedup_fingerprint=question_fingerprint(q.content) if q.content else None,
            answered_turn_id=link.turn_id if link else None, answered_version=link.question_version if link else None,
            answer_matches_current_version=bool(link and link.question_version == q.version)))
    for q in qs:
        if q.state in ('hidden', 'deleted'):
            continue
        proposed = context.model_copy(update={'questions': tuple(item.model_copy(update={'content': redact(q.content)}) if item.question_id == q.id else item for item in context.questions)})
        if within_budget(proposed): context = proposed

    # Prefer current confirmed facts; never send old FactChange statements/materials.
    rows = db.scalars(select(ExperienceFact).where(ExperienceFact.project_id == run.project_id).order_by(case((ExperienceFact.status.in_(('user_confirmed', 'evidence_supported')), 0), else_=1), ExperienceFact.created_at.desc(), ExperienceFact.id.desc()).limit(MAX_FACTS)).all()
    for f in rows:
        edited = db.scalar(select(FactChange.id).where(FactChange.fact_id == f.id, FactChange.action == 'edited').limit(1))
        add('facts', FactContext(fact_id=f.id, version=f.version, status=f.status,
            statement=None if f.status == 'rejected' else redact(f.statement), memory_state=f.memory_state,
            source_kind='user_edit' if edited else 'conversation_turns'))
    history = db.scalars(select(ConversationTurn).where(ConversationTurn.session_id == run.session_id, ConversationTurn.role == 'user', ConversationTurn.id != current.id).order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc()).limit(MAX_TURNS - 1)).all()
    for turn in history: add('user_turns', user(turn))
    # Count metadata itself in the final budget; worst case fails closed.
    context = context.model_copy(update={'omitted_turns': total_turns-len(context.user_turns),
        'omitted_facts': total_facts-len(context.facts), 'omitted_questions': total_questions-len(context.questions)})
    if not within_budget(context): raise ValueError('Context budget exceeded')
    return context
