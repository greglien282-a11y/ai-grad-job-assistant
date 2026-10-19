"""Authenticated HTTP boundary; each request has an explicit DB transaction."""
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import facts, schemas
from app import idempotency as idem
from app.db import build_engine, session_factory
from app.models import ConversationTurn, ExperienceFact, ExperienceProject, ExperienceSession, FactChange, FactEvidence, FactStatus, utcnow

router = APIRouter(prefix="/api/v1/experience", tags=["experience"])
bearer = HTTPBearer(auto_error=False)


@lru_cache
def configured_factory():
    return session_factory(build_engine())


def get_db():
    # Lazy setup preserves health checks when no DATABASE_URL is configured.
    try:
        factory = configured_factory()
    except (RuntimeError, ValueError):
        raise HTTPException(503, "Database unavailable") from None
    with factory() as db, db.begin():
        yield db


def require_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if credentials is None or not 32 <= len(credentials.credentials) <= 256:
        raise HTTPException(401, "Bearer credential required", headers={"WWW-Authenticate": "Bearer"})
    return credentials.credentials


Database = Annotated[Session, Depends(get_db, scope="function")]
Token = Annotated[str, Depends(require_token)]


def fact_view(db: Session, fact: ExperienceFact) -> schemas.FactView:
    from app.maintenance_provenance import provenance
    snapshot = facts.snapshot(db, fact)
    return schemas.FactView(id=fact.id, project_id=fact.project_id, session_id=fact.session_id,
                            created_at=fact.created_at, updated_at=fact.updated_at,
                            **snapshot, **provenance(db, fact, snapshot))


def turn_view(db: Session, turn: ConversationTurn) -> schemas.TurnView:
    from app.mining import answer_links
    return schemas.TurnView(id=turn.id, session_id=turn.session_id, role=turn.role, content=turn.content,
                            created_at=turn.created_at, answered_questions=answer_links(db, turn.id))


def session_view(db: Session, record: ExperienceSession) -> schemas.SessionView:
    from app.mining import view
    from app.models import MiningRun
    db.refresh(record)
    def rows(model):
        return list(db.scalars(select(model).where(model.session_id == record.id).order_by(model.created_at, model.id)))

    return schemas.SessionView(
        id=record.id, status=record.status, created_at=record.created_at, updated_at=record.updated_at,
        context_revision=record.context_revision, mining_status=record.mining_status,
        projects=[schemas.ProjectView.model_validate(row) for row in rows(ExperienceProject)],
        turns=[turn_view(db, row) for row in rows(ConversationTurn)],
        facts=[fact_view(db, row) for row in rows(ExperienceFact)],
        evidence=[schemas.EvidenceView.model_validate(row) for row in rows(FactEvidence)],
        history=[schemas.ChangeView.model_validate(row) for row in rows(FactChange)],
        mining_runs=[view(db, row) for row in rows(MiningRun)],
    )


def operation_key(request, kind, scope, token=None, *, required=False):
    values = request.headers.getlist('idempotency-key')
    if not values and not required:
        return None, token
    if len(values) != 1:
        raise idem.IdempotencyError(422, 'idempotency_key_invalid')
    credentials = request.headers.getlist('authorization')
    if len(credentials) != 1 or not credentials[0].lower().startswith('bearer '):
        raise idem.IdempotencyError(401, 'idempotency_credential_invalid')
    supplied = credentials[0][7:]
    return idem.parse(values[0], supplied, kind, scope), supplied


def creation_receipt(db, row, key, token, response, tag=None):
    idem.match_receipt(row, key)
    sid = row.session_id
    try:
        session = facts.authorize(db, sid, token, lock=True)
    except PermissionError:
        current = idem.existing(db, key)
        if current:
            idem.match_receipt(current, key)
        raise idem.IdempotencyError(401, 'idempotency_credential_invalid') from None
    key.fresh()
    row = idem.existing(db, key)
    if row is None:
        raise idem.IdempotencyError(410, 'idempotency_result_unavailable')
    idem.match_receipt(row, key, tag)
    if db.get(ExperienceProject, row.project_id) is None or db.get(ConversationTurn, row.initial_turn_id) is None:
        raise idem.IdempotencyError(410, 'idempotency_result_unavailable')
    response.headers['Idempotency-Replayed'] = 'true'
    return schemas.CreatedSession(session_id=sid, project_id=row.project_id,
                                  initial_turn_id=row.initial_turn_id, status=session.status, access_token=token)


@router.post("/sessions", response_model=schemas.CreatedSession, status_code=201)
def create_session(body: schemas.CreateSession, db: Database, request: Request, response: Response):
    key, token = operation_key(request, 'create_session', 'global')
    if key:
        idem.lock(db, key)
        row = idem.existing(db, key)
        if row:
            return creation_receipt(db, row, key, token, response, idem.request_tag(key, token, body.model_dump(mode='json')))
    project, turn, token = facts.create_experience(db, body.raw_input, token=token if key else None)
    if key:
        idem.remember(db, key, token, body.model_dump(mode='json'), session_id=project.session_id,
                      project_id=project.id, initial_turn_id=turn.id)
    return schemas.CreatedSession(session_id=project.session_id, project_id=project.id,
                                  initial_turn_id=turn.id, status="active", access_token=token)


@router.get('/session-creations/recovery', response_model=schemas.CreatedSession)
def recover_creation(db: Database, request: Request, response: Response):
    key, token = operation_key(request, 'create_session', 'global', required=True)
    idem.lock(db, key)
    row = idem.existing(db, key)
    if row is None:
        raise idem.IdempotencyError(404, 'idempotency_creation_not_found')
    return creation_receipt(db, row, key, token, response)


@router.get("/sessions/{session_id}", response_model=schemas.SessionView)
def read_session(session_id: UUID, token: Token, db: Database):
    # Serialize under the same parent lock as writes for a consistent aggregate.
    record = facts.authorize(db, session_id, token, lock=True)
    return session_view(db, record)


@router.post("/sessions/{session_id}/turns", response_model=schemas.TurnView, status_code=201)
def create_turn(session_id: UUID, body: schemas.AddTurn, token: Token, db: Database, request: Request, response: Response):
    key, _ = operation_key(request, 'add_turn', f'session:{session_id}', token)
    if key:
        idem.lock(db, key)
        facts.authorize(db, session_id, token, lock=True)
        key.fresh()
        row = idem.existing(db, key)
        if row:
            idem.match_receipt(row, key, idem.request_tag(key, token, body.model_dump(mode='json')))
            turn = db.get(ConversationTurn, row.turn_id)
            if turn is None:
                raise idem.IdempotencyError(410, 'idempotency_result_unavailable')
            response.headers['Idempotency-Replayed'] = 'true'
            return turn_view(db, turn)
    turn = facts.add_turn(db, session_id, token, body.content)
    if key:
        idem.remember(db, key, token, body.model_dump(mode='json'), session_id=session_id, target_id=session_id, turn_id=turn.id)
    return turn_view(db, turn)


@router.post("/projects/{project_id}/facts", response_model=schemas.FactView, status_code=201)
def create_fact(project_id: UUID, body: schemas.AddFact, token: Token, db: Database, request: Request, response: Response):
    key, _ = operation_key(request, 'add_fact', f'project:{project_id}', token)
    project = db.get(ExperienceProject, project_id) if not key else None
    if key:
        idem.lock(db, key)
        project = db.get(ExperienceProject, project_id)
        if project is None:
            raise PermissionError('Resource unavailable')
        facts.authorize(db, project.session_id, token, lock=True)
        key.fresh()
        row = idem.existing(db, key)
        if row:
            idem.match_receipt(row, key, idem.request_tag(key, token, body.model_dump(mode='json')))
            fact = db.get(ExperienceFact, row.fact_id)
            if fact is None:
                raise idem.IdempotencyError(410, 'idempotency_result_unavailable')
            response.headers['Idempotency-Replayed'] = 'true'
            return fact_view(db, fact)
    fact = facts.add_fact(db, project_id, token, body.statement, body.source_turn_ids)
    if key:
        idem.remember(db, key, token, body.model_dump(mode='json'), session_id=fact.session_id, target_id=project_id, fact_id=fact.id)
    return fact_view(db, fact)


@router.patch("/facts/{fact_id}", response_model=schemas.FactView)
def mutate_fact(fact_id: UUID, body: schemas.FactMutation, token: Token, db: Database):
    options = {"expected_version": body.expected_version}
    if isinstance(body, schemas.EditFact):
        options["statement"] = body.statement
    elif isinstance(body, schemas.SetMemory):
        options['memory_state'] = body.memory_state
    else:
        options["status"] = {"confirm": FactStatus.USER_CONFIRMED, "reject": FactStatus.REJECTED,
                             "verify_material": FactStatus.EVIDENCE_SUPPORTED}[body.action]
        if isinstance(body, schemas.VerifyFact):
            options.update(material_reference=body.material_reference, basis=body.basis)
    return fact_view(db, facts.change_fact(db, fact_id, token, **options))


@router.post("/sessions/{session_id}/end", response_model=schemas.SessionView)
def close_session(session_id: UUID, token: Token, db: Database):
    record = facts.authorize(db, session_id, token, lock=True)
    if record.status == "active":
        facts.end_session(db, session_id, token)
        db.flush()
    return session_view(db, record)


@router.get("/sessions/{session_id}/export", response_model=schemas.SessionExport)
def export_session(session_id: UUID, token: Token, db: Database, response: Response):
    record = facts.authorize(db, session_id, token, lock=True)
    response.headers["Content-Disposition"] = f'attachment; filename="pathwise-{session_id}.json"'
    return schemas.SessionExport(exported_at=utcnow(), data=session_view(db, record))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: UUID, token: Token, db: Database):
    record = facts.authorize(db, session_id, token, lock=True)
    idem.erase_receipts(db, session_id)
    from app.mining import erase_receipts
    erase_receipts(db, session_id)
    db.delete(record)
    db.flush()
    return Response(status_code=204)
