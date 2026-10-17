"""Inert paid-mining metadata. No provider, authorization or dispatch entry."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base


class MiningPaidIdentity(Base):
    __tablename__ = 'mining_paid_identities'
    __table_args__ = (
        CheckConstraint("actor_scope ~ '^[a-f0-9]{64}$' AND session_scope ~ '^[a-f0-9]{64}$'", name='ck_mpi_scopes'),
        CheckConstraint("length(issuer_version) BETWEEN 1 AND 64", name='ck_mpi_issuer'),)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('experience_sessions.id', ondelete='CASCADE'), primary_key=True)
    actor_scope: Mapped[str] = mapped_column(String(64))
    session_scope: Mapped[str] = mapped_column(String(64), unique=True)
    issuer_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class MiningPaidLimit(Base):
    __tablename__ = 'mining_paid_limits'
    __table_args__ = (
        CheckConstraint("kind IN ('user','session') AND currency='CNY'", name='ck_mpl_scope'),
        CheckConstraint("scope ~ '^[a-f0-9]{64}$' AND evidence_sha ~ '^[a-f0-9]{64}$'", name='ck_mpl_hashes'),
        CheckConstraint('ceiling>=0 AND calls_limit>=0 AND concurrent_limit>=0', name='ck_mpl_limits'),)
    ledger_id: Mapped[UUID] = mapped_column(ForeignKey('paid_funding.ledger_id', ondelete='RESTRICT'), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), server_default='CNY')
    ceiling: Mapped[Decimal] = mapped_column(Numeric(20,6), server_default='0')
    calls_limit: Mapped[int] = mapped_column(Integer, server_default='0')
    concurrent_limit: Mapped[int] = mapped_column(Integer, server_default='0')
    evidence_sha: Mapped[str] = mapped_column(String(64))


class PaidMiningMetadata:
    root_run_id: Mapped[UUID] = mapped_column(unique=True)
    ledger_id: Mapped[UUID] = mapped_column(ForeignKey('paid_funding.ledger_id', ondelete='RESTRICT'))
    grant_id: Mapped[UUID] = mapped_column(ForeignKey('paid_grants.id', ondelete='RESTRICT'))
    operation_hash: Mapped[str] = mapped_column(String(64), unique=True)
    receipt_hash: Mapped[str] = mapped_column(String(64))
    request_sha: Mapped[str] = mapped_column(String(64))
    policy_sha: Mapped[str] = mapped_column(String(64))
    context_sha: Mapped[str] = mapped_column(String(64))
    prompt_sha: Mapped[str] = mapped_column(String(64))
    schema_sha: Mapped[str] = mapped_column(String(64))
    account_sha: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    config_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


def metadata_checks(prefix):
    return (
        CheckConstraint(' AND '.join(f"{n} ~ '^[a-f0-9]{{64}}$'" for n in (
            'operation_hash','receipt_hash','request_sha','policy_sha','context_sha','prompt_sha','schema_sha','account_sha')),
            name=f'ck_{prefix}_hashes'),
        CheckConstraint("provider='deepseek_official' AND model='deepseek-flash'", name=f'ck_{prefix}_model'),
        CheckConstraint(' AND '.join(f'length({n}) BETWEEN 1 AND 64' for n in (
            'config_version','prompt_version','schema_version')), name=f'ck_{prefix}_versions'),)


class MiningPaidPlan(PaidMiningMetadata, Base):
    __tablename__ = 'mining_paid_plans'
    __table_args__ = metadata_checks('mpp')
    run_id: Mapped[UUID] = mapped_column(ForeignKey('ai_mining_runs.id', ondelete='CASCADE'), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('mining_paid_identities.session_id', ondelete='CASCADE'))


class MiningPaidBinding(PaidMiningMetadata, Base):
    __tablename__ = 'mining_paid_bindings'
    __table_args__ = (*metadata_checks('mpb'),
        CheckConstraint('contract_version=1', name='ck_mpb_version'),
        CheckConstraint("actor_scope ~ '^[a-f0-9]{64}$' AND session_scope ~ '^[a-f0-9]{64}$'", name='ck_mpb_scopes'),
        CheckConstraint("(binding_state='bound' AND tombstoned_at IS NULL) OR (binding_state='tombstoned' AND tombstoned_at IS NOT NULL AND tombstoned_at>=created_at)", name='ck_mpb_tombstone'),)
    # Deliberately no business FK: erasure must not erase billing liability.
    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    call_id: Mapped[UUID] = mapped_column(ForeignKey('paid_calls.id', ondelete='RESTRICT'), unique=True)
    contract_version: Mapped[int] = mapped_column(Integer, server_default='1')
    actor_scope: Mapped[str] = mapped_column(String(64))
    session_scope: Mapped[str] = mapped_column(String(64))
    binding_state: Mapped[str] = mapped_column(String(16), server_default='bound')
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
