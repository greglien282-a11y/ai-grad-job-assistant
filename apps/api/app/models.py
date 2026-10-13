"""M1-1A storage. UUIDs identify records; separate credentials authorize access."""
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FactStatus(StrEnum):
    PENDING = "pending"
    USER_CONFIRMED = "user_confirmed"
    EVIDENCE_SUPPORTED = "evidence_supported"
    REJECTED = "rejected"


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperienceSession(Record, Base):
    __tablename__ = "experience_sessions"
    __table_args__ = (CheckConstraint("status IN ('active', 'ended')", name="ck_session_status"),)
    access_token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExperienceProject(Record, Base):
    __tablename__ = "experience_projects"
    __table_args__ = (UniqueConstraint("id", "session_id", name="uq_project_session"),)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("experience_sessions.id", ondelete="CASCADE"), index=True)
    raw_input: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(200))


class ConversationTurn(Record, Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_turn_session"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_turn_role"),
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("experience_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)


class ExperienceFact(Record, Base):
    __tablename__ = "experience_facts"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "session_id"], ["experience_projects.id", "experience_projects.session_id"], ondelete="CASCADE"),
        UniqueConstraint("id", "session_id", name="uq_fact_session"),
        CheckConstraint("status IN ('pending', 'user_confirmed', 'evidence_supported', 'rejected')", name="ck_fact_status"),
        CheckConstraint("length(trim(statement)) > 0", name="ck_fact_statement"),
        CheckConstraint("version > 0", name="ck_fact_version"),
        CheckConstraint("status != 'evidence_supported' OR evidence_id IS NOT NULL", name="ck_fact_evidence"),
        ForeignKeyConstraint(["evidence_id", "id", "session_id"], ["fact_evidence.id", "fact_evidence.fact_id", "fact_evidence.session_id"], name="fk_fact_current_evidence", use_alter=True),
    )
    project_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    statement: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}
    status: Mapped[str] = mapped_column(String(24), default=FactStatus.PENDING)
    evidence_id: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FactSource(Base):
    __tablename__ = "fact_sources"
    __table_args__ = (
        ForeignKeyConstraint(["fact_id", "session_id"], ["experience_facts.id", "experience_facts.session_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["turn_id", "session_id"], ["conversation_turns.id", "conversation_turns.session_id"], ondelete="CASCADE"),
    )
    fact_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    turn_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(Uuid)


class FactEvidence(Record, Base):
    __tablename__ = "fact_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["fact_id", "session_id"], ["experience_facts.id", "experience_facts.session_id"], ondelete="CASCADE"),
        UniqueConstraint("id", "fact_id", "session_id", name="uq_evidence_fact_session"),
        CheckConstraint("length(trim(material_reference)) > 0 AND length(trim(basis)) > 0", name="ck_evidence_basis"),
        CheckConstraint("reviewer = 'user'", name="ck_evidence_reviewer"),
    )
    fact_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid)
    material_reference: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(16), default="user")


class FactChange(Record, Base):
    __tablename__ = "fact_changes"
    __table_args__ = (
        ForeignKeyConstraint(["fact_id", "session_id"], ["experience_facts.id", "experience_facts.session_id"], ondelete="CASCADE"),
        CheckConstraint("actor IN ('user', 'system')", name="ck_change_actor"),
    )
    fact_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    session_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(16))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict] = mapped_column(JSONB)


class IdempotencyOperation(Base):
    __tablename__ = "idempotency_operations"
    __table_args__ = (
        CheckConstraint("state IN ('completed','deleted')", name="ck_operation_state"),
        CheckConstraint("(state='deleted' AND operation IS NULL AND session_id IS NULL AND target_id IS NULL AND request_tag IS NULL AND project_id IS NULL AND initial_turn_id IS NULL AND turn_id IS NULL AND fact_id IS NULL) OR (state='completed' AND session_id IS NOT NULL AND request_tag IS NOT NULL AND ((operation='create_session' AND project_id IS NOT NULL AND initial_turn_id IS NOT NULL) OR (operation='add_turn' AND target_id IS NOT NULL AND turn_id IS NOT NULL) OR (operation='add_fact' AND target_id IS NOT NULL AND fact_id IS NOT NULL)))", name="ck_operation_receipt"),
    )
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    operation: Mapped[str | None] = mapped_column(String(24))
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("experience_sessions.id"), index=True)
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    request_tag: Mapped[str | None] = mapped_column(String(64))
    project_id: Mapped[UUID | None] = mapped_column(Uuid)
    initial_turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    fact_id: Mapped[UUID | None] = mapped_column(Uuid)
