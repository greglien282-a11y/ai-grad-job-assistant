"""Synthetic-only HTTP contracts; no transaction spans a provider call."""
import os
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import select
from app import facts, mining, schemas
from app.experience_api import Token, configured_factory, operation_key, fact_view
from app.mining_provider import ScriptedProvider
from app.models import ExperienceFact, ExperienceProject, MiningQuestion

router = APIRouter(prefix='/api/v1/experience', tags=['synthetic mining'])

def get_mining_factory():
    return configured_factory()

def get_provider():
    if os.getenv('AI_ENABLED', 'false').lower() != 'true':
        return None
    if os.getenv('AI_PROVIDER') != 'scripted':
        raise mining.MiningError(503, 'ai_provider_unapproved')
    return ScriptedProvider()

Factory = Annotated[object, Depends(get_mining_factory)]
Provider = Annotated[object, Depends(get_provider)]

class Start(schemas.Input):
    project_id: UUID
    base_revision: schemas.Version
    content: schemas.TextInput | None = None
    input_turn_id: UUID | None = None
    retry_of: UUID | None = None
    confirm_retry: bool = Field(strict=True, default=False)
    answered_question_ids: list[UUID] | None = Field(default=None, max_length=2)

    @model_validator(mode='after')
    def one_input(self):
        if sum(item is not None for item in (self.content, self.input_turn_id, self.retry_of)) != 1:
            raise ValueError('Exactly one input required')
        if self.confirm_retry != (self.retry_of is not None):
            raise ValueError('Retry requires explicit confirmation')
        if self.answered_question_ids and len(set(self.answered_question_ids)) != len(self.answered_question_ids):
            raise ValueError('Question IDs must be distinct')
        return self

class ContextAction(schemas.Input):
    base_revision: schemas.Version

class QuestionAction(ContextAction):
    expected_version: schemas.Version
    action: Literal['skip','correct','hide','delete']
    content: Annotated[str, Field(min_length=1, max_length=500)] | None = None

    @model_validator(mode='after')
    def correction_only(self):
        if (self.action == 'correct') != (self.content is not None):
            raise ValueError('Only corrections accept content')
        return self

@router.post('/sessions/{sid}/mining-runs', response_model=schemas.MiningRunView)
async def start(sid: UUID, body: Start, token: Token, request: Request, response: Response, factory: Factory, provider: Provider):
    mining.safe_provider(provider)
    key, _ = operation_key(request, 'mining_run', f'session:{sid}', token, required=True)
    rid, fresh = mining.reserve(factory, sid, token, key, body)
    if fresh:
        await mining.execute(factory, provider, sid, token, rid)
    else:
        response.headers['Idempotency-Replayed'] = 'true'
    with factory() as db, db.begin():
        result = mining.view(db, mining.get_run(db, sid, token, rid))
    response.status_code = 202 if result['state'] in mining.ACTIVE else (201 if fresh else 200)
    return result

@router.get('/sessions/{sid}/mining-runs/recovery', response_model=schemas.MiningRunView)
def recovery(sid: UUID, token: Token, request: Request, factory: Factory):
    key, _ = operation_key(request, 'mining_run', f'session:{sid}', token, required=True)
    with factory() as db, db.begin():
        return mining.recover(db, sid, token, key)

@router.get('/sessions/{sid}/mining-runs/{rid}', response_model=schemas.MiningRunView)
def read_run(sid: UUID, rid: UUID, token: Token, factory: Factory):
    with factory() as db, db.begin():
        return mining.view(db, mining.get_run(db, sid, token, rid, lock=False))

@router.post('/sessions/{sid}/mining-stop')
def stop(sid: UUID, body: ContextAction, token: Token, factory: Factory):
    with factory() as db, db.begin():
        session = facts.authorize(db, sid, token, write=True)
        if session.context_revision != body.base_revision:
            raise mining.MiningError(409, 'context_conflict')
        session.mining_status = 'stopped'; db.flush(); db.refresh(session)
        return dict(mining_status=session.mining_status, context_revision=session.context_revision)

@router.patch('/sessions/{sid}/mining-questions/{qid}')
def question(sid: UUID, qid: UUID, body: QuestionAction, token: Token, factory: Factory):
    with factory() as db, db.begin():
        session = facts.authorize(db, sid, token, write=True)
        q = db.get(MiningQuestion, qid)
        if q is None or q.session_id != sid:
            raise PermissionError('Resource unavailable')
        if session.context_revision != body.base_revision or q.version != body.expected_version:
            raise mining.MiningError(409, 'context_conflict')
        if q.state == 'deleted':
            raise mining.MiningError(410, 'mining_question_deleted')
        q.state = {'skip':'skipped','correct':'corrected','hide':'hidden','delete':'deleted'}[body.action]
        if body.action == 'correct': q.content = body.content
        if body.action == 'delete': q.content = None
        q.version += 1; db.flush(); db.refresh(session)
        return dict(id=q.id, state=q.state, content=q.content, version=q.version, context_revision=session.context_revision)

@router.get('/projects/{pid}/experience-summary', response_model=schemas.ExperienceSummary)
def summary(pid: UUID, token: Token, factory: Factory):
    with factory() as db, db.begin():
        project = db.get(ExperienceProject, pid)
        if project is None: raise PermissionError('Resource unavailable')
        session = facts.authorize(db, project.session_id, token, lock=True)
        rows = db.scalars(select(ExperienceFact).where(ExperienceFact.project_id == pid).order_by(ExperienceFact.created_at, ExperienceFact.id)).all()
        confirmed = [f for f in rows if f.status in ('user_confirmed','evidence_supported')]
        return dict(project_id=pid, context_revision=session.context_revision,
            confirmed=[fact_view(db, f).model_dump(mode='json') for f in confirmed],
            pending=[fact_view(db, f).model_dump(mode='json') for f in rows if f.status == 'pending'],
            text='\n'.join(f.statement for f in confirmed), incomplete=not bool(confirmed))
