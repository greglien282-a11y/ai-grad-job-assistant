"""Separate paid-control records. No HTTP capability or initial paid authority."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, Record


class PaidFunding(Base):
    __tablename__ = 'paid_funding'
    __table_args__ = (CheckConstraint('id = 1', name='ck_paid_single_pool'),
                      CheckConstraint('ceiling >= 0 AND held >= 0 AND spent >= 0', name='ck_paid_pool_money'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ledger_id: Mapped[UUID] = mapped_column(unique=True)
    ceiling: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    held: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    spent: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    frozen: Mapped[bool] = mapped_column(Boolean)
    approval_digest: Mapped[str | None] = mapped_column(String(64))


class PaidScope(Base):
    __tablename__ = 'paid_scopes'
    __table_args__ = (CheckConstraint("kind IN ('provider','model')", name='ck_paid_scope_kind'),
                      CheckConstraint('ceiling >= 0', name='ck_paid_scope_money'))
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    ceiling: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    approval_digest: Mapped[str] = mapped_column(String(64))


class PaidGrant(Record, Base):
    __tablename__ = 'paid_grants'
    __table_args__ = (CheckConstraint('pool_id = 1', name='ck_paid_grant_pool'),
                      CheckConstraint('starts_at < expires_at AND ceiling >= 0 AND call_limit > 0 AND calls_limit > 0', name='ck_paid_grant_limits'))
    pool_id: Mapped[int] = mapped_column(ForeignKey('paid_funding.id'))
    approver: Mapped[str] = mapped_column(String(64))
    approval_digest: Mapped[str] = mapped_column(String(64), unique=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean)
    ceiling: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    call_limit: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    calls_limit: Mapped[int] = mapped_column(Integer)
    policy_hash: Mapped[str] = mapped_column(String(64))
    policy: Mapped[dict] = mapped_column(JSONB)


class PaidCall(Record, Base):
    __tablename__ = 'paid_calls'
    __table_args__ = (CheckConstraint("state IN ('reserved','sent','response_received','unknown','reconciled')", name='ck_paid_call_state'),
                      CheckConstraint('reserved > 0 AND (actual IS NULL OR actual >= 0) AND (actual_usd IS NULL OR actual_usd >= 0)', name='ck_paid_call_money'))
    grant_id: Mapped[UUID] = mapped_column(ForeignKey('paid_grants.id'))
    operation_hash: Mapped[str] = mapped_column(String(64), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    policy_hash: Mapped[str] = mapped_column(String(64))
    batch_tag: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24))
    reserved: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    actual: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    invoice_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    usage: Mapped[dict | None] = mapped_column(JSONB)


class PaidAudit(Record, Base):
    __tablename__ = 'paid_audit'
    action: Mapped[str] = mapped_column(String(32))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSONB)
