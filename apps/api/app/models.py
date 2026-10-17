"""M1-1A storage. UUIDs identify records; separate credentials authorize access."""
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, Uuid, Index, text, Numeric, Boolean
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
    __table_args__ = (CheckConstraint("status IN ('active', 'ended')", name="ck_session_status"),
                      CheckConstraint("context_revision > 0", name="ck_context_revision"),
                      CheckConstraint("mining_status IN ('not_started','active','stopped')", name="ck_mining_status"))
    access_token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    context_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    mining_status: Mapped[str] = mapped_column(String(16), default="not_started", server_default="not_started")


class ExperienceProject(Record, Base):
    __tablename__ = "experience_projects"
    __table_args__ = (UniqueConstraint("id", "session_id", name="uq_project_session"),
                      UniqueConstraint("session_id", name="uq_mvp_one_project"))
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
        CheckConstraint("origin IN ('manual','ai_extracted')", name="ck_fact_origin"),
        CheckConstraint("memory_state IN ('unspecified','certain','approximate','needs_check')", name="ck_fact_memory"),
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
    origin: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    memory_state: Mapped[str] = mapped_column(String(16), default="unspecified", server_default="unspecified")
    ai_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_mining_runs.id", ondelete="SET NULL", use_alter=True, name="fk_fact_ai_run"))


class FactSource(Base):
    __tablename__ = "fact_sources"
    __table_args__ = (
        ForeignKeyConstraint(["fact_id", "session_id"], ["experience_facts.id", "experience_facts.session_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["turn_id", "session_id"], ["conversation_turns.id", "conversation_turns.session_id"], ondelete="CASCADE"),
    )
    fact_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    turn_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(Uuid)
    citations: Mapped[list | None] = mapped_column(JSONB)


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


class MiningRun(Record, Base):
    __tablename__ = "ai_mining_runs"
    __table_args__ = (
        UniqueConstraint('retry_of', name='uq_mining_retry_parent'),
        ForeignKeyConstraint(["project_id", "session_id"], ["experience_projects.id", "experience_projects.session_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["input_turn_id", "session_id"], ["conversation_turns.id", "conversation_turns.session_id"], ondelete="CASCADE"),
        CheckConstraint("state IN ('reserved','running','completed','failed','unknown','stale')", name="ck_mining_state"),
        CheckConstraint("base_revision > 0 AND reserved_revision >= base_revision", name="ck_mining_revisions"),
        Index("uq_mining_active", "session_id", unique=True, postgresql_where=text("state IN ('reserved','running')")),
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("experience_sessions.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    input_turn_id: Mapped[UUID] = mapped_column(Uuid)
    base_revision: Mapped[int] = mapped_column(Integer)
    reserved_revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(48))
    retry_of: Mapped[UUID | None] = mapped_column(ForeignKey("ai_mining_runs.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(32), default="scripted")
    prompt_version: Mapped[str] = mapped_column(String(16), default="extractive-v1")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    assistant_turn_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversation_turns.id", ondelete="SET NULL"))


class MiningReceipt(Base):
    __tablename__ = "ai_mining_receipts"
    __table_args__ = (CheckConstraint("(state='live' AND session_id IS NOT NULL AND run_id IS NOT NULL AND request_tag IS NOT NULL) OR (state='deleted' AND session_id IS NULL AND run_id IS NULL AND request_tag IS NULL)", name="ck_mining_receipt"),)
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("experience_sessions.id"), index=True)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_mining_runs.id"))
    request_tag: Mapped[str | None] = mapped_column(String(64))


class MiningQuestion(Record, Base):
    __tablename__ = "ai_mining_questions"
    __table_args__ = (UniqueConstraint('id', 'session_id', name='uq_question_session'),
                      CheckConstraint("state IN ('active','skipped','corrected','hidden','deleted')", name="ck_question_state"),
                      CheckConstraint("(state='deleted' AND content IS NULL) OR (state!='deleted' AND content IS NOT NULL)", name="ck_question_content"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("experience_sessions.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("ai_mining_runs.id", ondelete="CASCADE"))
    content: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)


class MiningCapacity(Base):
    __tablename__ = "ai_mining_capacity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Singleton row lock coordinates admission across processes; no personal data.


class AnswerQuestion(Base):
    """Immutable IDs/version only. Question deletion never erases a user answer."""
    __tablename__ = 'ai_answer_questions'
    __table_args__ = (
        ForeignKeyConstraint(['turn_id','session_id'], ['conversation_turns.id','conversation_turns.session_id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['question_id','session_id'], ['ai_mining_questions.id','ai_mining_questions.session_id'], ondelete='CASCADE'),
        UniqueConstraint('turn_id', 'slot', name='uq_answer_question_slot'),
        CheckConstraint('slot IN (1,2) AND question_version > 0', name='ck_answer_question_slot'),
    )
    turn_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    question_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(Uuid)
    question_version: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer)


# Isolated offline cost ledger. No FK to private experience records, no prompts.
class CostBudget(Base):
    __tablename__ = 'cost_budgets'
    __table_args__ = (
        CheckConstraint("kind IN ('global','provider','model','session')", name='ck_cost_budget_kind'),
        CheckConstraint('ceiling >= 0 AND held >= 0 AND spent >= 0 AND call_limit >= 0', name='ck_cost_budget_money'),
        CheckConstraint('max_active > 0', name='ck_cost_budget_active'),
    )
    namespace: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    ceiling: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    call_limit: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    held: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    spent: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    max_active: Mapped[int] = mapped_column(Integer, default=2)


class CostCall(Record, Base):
    __tablename__ = 'cost_calls'
    __table_args__ = (
        UniqueConstraint('namespace', 'operation_hash', name='uq_cost_operation'),
        CheckConstraint("state IN ('reserved','sent','response_received','unknown','reconciled')", name='ck_cost_call_state'),
        CheckConstraint('reserved >= 0 AND (estimated IS NULL OR estimated >= 0) AND (actual IS NULL OR actual >= 0)', name='ck_cost_call_money'),
        CheckConstraint("transport = 'mock'", name='ck_cost_mock_only'),
    )
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    operation_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    profile_id: Mapped[str] = mapped_column(String(64))
    profile_hash: Mapped[str] = mapped_column(String(64))
    profile_snapshot: Mapped[dict] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    session_tag: Mapped[str] = mapped_column(String(128))
    transport: Mapped[str] = mapped_column(String(16), default='mock')
    state: Mapped[str] = mapped_column(String(24), default='reserved')
    reserved: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    estimated: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    invoice_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    rate: Mapped[dict] = mapped_column(JSONB)
    usage: Mapped[dict | None] = mapped_column(JSONB)
    model_evidence: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# C-0 preflight controls are deliberately fixture-only. They CANNOT approve fees.
class ProbeFunding(Base):
    __tablename__ = 'probe_funding'
    __table_args__ = (CheckConstraint('id = 1 AND approved_real_cny = 0', name='ck_probe_zero_authority'),
                      CheckConstraint('fixture_ceiling >= 0 AND held >= 0 AND spent >= 0', name='ck_probe_funding_money'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approved_real_cny: Mapped[Decimal] = mapped_column(Numeric(20,6), default=0)
    fixture_ceiling: Mapped[Decimal] = mapped_column(Numeric(20,6))
    held: Mapped[Decimal] = mapped_column(Numeric(20,6), default=0)
    spent: Mapped[Decimal] = mapped_column(Numeric(20,6), default=0)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    last_review_digest: Mapped[str | None] = mapped_column(String(64))


class ProbeGrant(Record, Base):
    __tablename__ = 'probe_grants'
    __table_args__ = (CheckConstraint("mode IN ('draft','offline_fixture','revoked')", name='ck_probe_grant_mode'),
                      CheckConstraint('pool_id = 1 AND approved_real_cny = 0', name='ck_probe_grant_zero'),
                      CheckConstraint('starts_at < expires_at AND fixture_limit >= 0 AND calls_limit > 0', name='ck_probe_grant_limits'))
    pool_id: Mapped[int] = mapped_column(ForeignKey('probe_funding.id'), default=1)
    mode: Mapped[str] = mapped_column(String(24), default='draft')
    approved_real_cny: Mapped[Decimal] = mapped_column(Numeric(20,6), default=0)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fixture_limit: Mapped[Decimal] = mapped_column(Numeric(20,6))
    calls_limit: Mapped[int] = mapped_column(Integer)
    policy: Mapped[dict] = mapped_column(JSONB)


class ProbeAttempt(Record, Base):
    __tablename__ = 'probe_attempts'
    __table_args__ = (UniqueConstraint('operation_hash', name='uq_probe_operation'),
                      CheckConstraint("state IN ('reserved','sent','response_received','unknown','reconciled')", name='ck_probe_attempt_state'),
                      CheckConstraint("execution = 'offline_http_fixture'", name='ck_probe_attempt_offline'),
                      CheckConstraint('reserved >= 0 AND (actual IS NULL OR actual >= 0)', name='ck_probe_attempt_money'))
    grant_id: Mapped[UUID] = mapped_column(ForeignKey('probe_grants.id'))
    operation_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    policy_snapshot: Mapped[dict] = mapped_column(JSONB)
    batch_tag: Mapped[str] = mapped_column(String(64))
    execution: Mapped[str] = mapped_column(String(24), default='offline_http_fixture')
    state: Mapped[str] = mapped_column(String(24), default='reserved')
    reserved: Mapped[Decimal] = mapped_column(Numeric(20,6))
    actual: Mapped[Decimal | None] = mapped_column(Numeric(20,6))
    invoice_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    usage: Mapped[dict | None] = mapped_column(JSONB)

# Register independent paid-control metadata; no runtime dispatch registration.
from app import paid_models  # noqa: E402,F401
from app import controlled_probe_models  # noqa: E402,F401
from app import mining_paid_models  # noqa: E402,F401
