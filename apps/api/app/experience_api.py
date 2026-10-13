"""Authenticated HTTP boundary; each request has an explicit DB transaction."""
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import facts, schemas
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
    return schemas.FactView(id=fact.id, project_id=fact.project_id, session_id=fact.session_id,
                            created_at=fact.created_at, updated_at=fact.updated_at, **facts.snapshot(db, fact))


def session_view(db: Session, record: ExperienceSession) -> schemas.SessionView:
    def rows(model):
        return list(db.scalars(select(model).where(model.session_id == record.id).order_by(model.created_at, model.id)))

    return schemas.SessionView(
        id=record.id, status=record.status, created_at=record.created_at, updated_at=record.updated_at,
        projects=[schemas.ProjectView.model_validate(row) for row in rows(ExperienceProject)],
        turns=[schemas.TurnView.model_validate(row) for row in rows(ConversationTurn)],
        facts=[fact_view(db, row) for row in rows(ExperienceFact)],
        evidence=[schemas.EvidenceView.model_validate(row) for row in rows(FactEvidence)],
        history=[schemas.ChangeView.model_validate(row) for row in rows(FactChange)],
    )


@router.post("/sessions", response_model=schemas.CreatedSession, status_code=201)
def create_session(body: schemas.CreateSession, db: Database):
    project, turn, token = facts.create_experience(db, body.raw_input)
    return schemas.CreatedSession(session_id=project.session_id, project_id=project.id,
                                  initial_turn_id=turn.id, status="active", access_token=token)


@router.get("/sessions/{session_id}", response_model=schemas.SessionView)
def read_session(session_id: UUID, token: Token, db: Database):
    # Serialize under the same parent lock as writes for a consistent aggregate.
    record = facts.authorize(db, session_id, token, lock=True)
    return session_view(db, record)


@router.post("/sessions/{session_id}/turns", response_model=schemas.TurnView, status_code=201)
def create_turn(session_id: UUID, body: schemas.AddTurn, token: Token, db: Database):
    return schemas.TurnView.model_validate(facts.add_turn(db, session_id, token, body.content))


@router.post("/projects/{project_id}/facts", response_model=schemas.FactView, status_code=201)
def create_fact(project_id: UUID, body: schemas.AddFact, token: Token, db: Database):
    return fact_view(db, facts.add_fact(db, project_id, token, body.statement, body.source_turn_ids))


@router.patch("/facts/{fact_id}", response_model=schemas.FactView)
def mutate_fact(fact_id: UUID, body: schemas.FactMutation, token: Token, db: Database):
    options = {"expected_version": body.expected_version}
    if isinstance(body, schemas.EditFact):
        options["statement"] = body.statement
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
    db.delete(record)
    db.flush()
    return Response(status_code=204)
