"""Transactional persistence operations, not HTTP endpoints or AI extraction.

Call inside Session.begin(); callers own commit/rollback. Lock the parent session
before writes to serialize edits and ending a session. History is append-only here.
"""
import hashlib
import secrets
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConversationTurn, ExperienceFact, ExperienceProject, ExperienceSession, FactChange, FactEvidence, FactSource, FactStatus, utcnow


class VersionConflict(Exception):
    """The caller is attempting to change an obsolete fact version."""


class StateConflict(ValueError):
    """The operation conflicts with the current resource state."""


def required_text(value: str) -> str:
    if not value.strip() or len(value) > 10000:
        raise ValueError("Text must contain 1–10000 characters")
    return value


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_experience(db: Session, raw_input: str) -> tuple[ExperienceProject, ConversationTurn, str]:
    required_text(raw_input)
    token = secrets.token_urlsafe(32)
    session = ExperienceSession(access_token_hash=token_hash(token))
    db.add(session)
    db.flush()
    project = ExperienceProject(session_id=session.id, raw_input=raw_input)
    turn = ConversationTurn(session_id=session.id, role="user", content=raw_input)
    db.add_all([project, turn])
    db.flush()
    return project, turn, token


def authorize(db: Session, session_id: UUID, token: str, *, write: bool = False, lock: bool = False) -> ExperienceSession:
    query = select(ExperienceSession).where(ExperienceSession.id == session_id)
    if write or lock:
        query = query.with_for_update()
    session = db.scalar(query.execution_options(populate_existing=True))
    if session is None or not secrets.compare_digest(session.access_token_hash, token_hash(token)):
        raise PermissionError("Session unavailable")
    if write and session.status != "active":
        raise StateConflict("Session has ended")
    return session


def add_turn(db: Session, session_id: UUID, token: str, content: str) -> ConversationTurn:
    session = authorize(db, session_id, token, write=True)
    turn = ConversationTurn(session_id=session_id, role="user", content=required_text(content))
    session.updated_at = utcnow()
    db.add(turn)
    db.flush()
    return turn


def snapshot(db: Session, fact: ExperienceFact, *, edit: FactChange | None = None) -> dict:
    """Current provenance for future API serialization, distinct from origin.

    FactSource always preserves the original extraction links. Once edited,
    only the latest user edit is the current statement's source. Confirmation
    changes trust status, never restores the original turn as supporting evidence.
    """
    sources = db.scalars(select(FactSource.turn_id).where(FactSource.fact_id == fact.id)).all()
    original_sources = sorted(str(item) for item in sources)
    if edit is None:
        edit = db.scalar(select(FactChange).where(
            FactChange.fact_id == fact.id, FactChange.action == "edited",
        ).order_by(FactChange.after["version"].as_integer().desc().nulls_last(),
                   FactChange.created_at.desc(), FactChange.id.desc()).limit(1))
    return {"statement": fact.statement, "status": str(fact.status),
            "version": fact.version,
            "original_source_turn_ids": original_sources,
            "source_kind": "user_edit" if edit else "conversation_turns",
            "source_turn_ids": [] if edit else original_sources,
            "source_change_id": str(edit.id) if edit else None,
            "evidence_id": str(fact.evidence_id) if fact.evidence_id else None}


def record_change(db: Session, fact: ExperienceFact, action: str, before: dict | None, actor: str = "user") -> None:
    change = FactChange(id=uuid4(), fact_id=fact.id, session_id=fact.session_id,
                        action=action, actor=actor, before=before)
    # The edit's ID is known before insert, so its snapshot can cite itself.
    change.after = snapshot(db, fact, edit=change if action == "edited" else None)
    db.add(change)
    db.flush()


def add_fact(db: Session, project_id: UUID, token: str, statement: str, source_turn_ids: list[UUID]) -> ExperienceFact:
    project = db.get(ExperienceProject, project_id)
    if project is None:
        raise PermissionError("Session unavailable")
    session = authorize(db, project.session_id, token, write=True)
    required_text(statement)
    if not source_turn_ids or len(set(source_turn_ids)) != len(source_turn_ids):
        raise ValueError("Supply distinct user source turns")
    for turn_id in source_turn_ids:
        turn = db.get(ConversationTurn, turn_id)
        if turn is None or turn.session_id != project.session_id or turn.role != "user":
            raise ValueError("Source must be a user turn in this session")
    fact = ExperienceFact(project_id=project.id, session_id=project.session_id, statement=statement)
    session.updated_at = utcnow()
    db.add(fact)
    db.flush()
    db.add_all([FactSource(fact_id=fact.id, turn_id=item, session_id=project.session_id) for item in source_turn_ids])
    db.flush()
    record_change(db, fact, "created", None, "system")
    return fact


def change_fact(db: Session, fact_id: UUID, token: str, *, statement: str | None = None,
                status: FactStatus | None = None, material_reference: str | None = None,
                basis: str | None = None, expected_version: int) -> ExperienceFact:
    fact = db.get(ExperienceFact, fact_id)
    if fact is None:
        raise PermissionError("Session unavailable")
    session = authorize(db, fact.session_id, token, write=True)
    # Reload after acquiring the parent lock: another transaction may have edited it.
    db.refresh(fact)
    if fact.version != expected_version:
        raise VersionConflict("Fact version has changed")
    before = snapshot(db, fact)
    if statement is not None:
        required_text(statement)
        if status is not None or material_reference is not None or basis is not None:
            raise ValueError("Edit and confirmation must be separate operations")
        if statement == fact.statement:
            raise StateConflict("Statement is unchanged")
        fact.statement, fact.status, fact.evidence_id = statement, FactStatus.PENDING, None
        action = "edited"
    else:
        if status is None:
            raise ValueError("Provide statement or status")
        status = FactStatus(status)
        allowed = {
            FactStatus.PENDING: {FactStatus.USER_CONFIRMED, FactStatus.REJECTED},
            FactStatus.USER_CONFIRMED: {FactStatus.EVIDENCE_SUPPORTED, FactStatus.REJECTED},
            FactStatus.EVIDENCE_SUPPORTED: {FactStatus.REJECTED},
            FactStatus.REJECTED: set(),
        }
        if status not in allowed[FactStatus(fact.status)]:
            raise StateConflict("Illegal fact status transition")
        if status == FactStatus.EVIDENCE_SUPPORTED:
            if material_reference is None or basis is None:
                raise ValueError("Material reference and human verification basis required")
            evidence = FactEvidence(fact_id=fact.id, session_id=fact.session_id,
                                    material_reference=required_text(material_reference), basis=required_text(basis))
            db.add(evidence)
            db.flush()
            fact.evidence_id = evidence.id
        elif material_reference is not None or basis is not None:
            raise ValueError("Evidence is only accepted during material verification")
        fact.status = status
        action = "status_changed"
    fact.updated_at = utcnow()
    session.updated_at = fact.updated_at
    db.flush()
    record_change(db, fact, action, before)
    return fact


def eligible_facts(db: Session, project_id: UUID, token: str) -> list[ExperienceFact]:
    project = db.get(ExperienceProject, project_id)
    if project is None:
        raise PermissionError("Session unavailable")
    authorize(db, project.session_id, token)
    return list(db.scalars(select(ExperienceFact).where(
        ExperienceFact.project_id == project_id,
        ExperienceFact.status.in_([FactStatus.USER_CONFIRMED, FactStatus.EVIDENCE_SUPPORTED]),
    )))


def end_session(db: Session, session_id: UUID, token: str) -> None:
    session = authorize(db, session_id, token, write=True)
    session.status = "ended"
    session.updated_at = utcnow()
