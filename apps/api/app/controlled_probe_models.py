"""Single risk-accepted experiment, sharing paid_funding; no initial approval."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ControlledProbe(Base):
    __tablename__ = 'controlled_probe'
    __table_args__ = (
        CheckConstraint('id = 1 AND pool_id = 1', name='ck_controlled_single'),
        CheckConstraint("state IN ('approved','reserved','sent','response_received','unknown','reconciled')", name='ck_controlled_state'),
        CheckConstraint('reserved > 0 AND (actual_cny IS NULL OR actual_cny >= 0)', name='ck_controlled_money'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey('paid_funding.id'))
    grant_id: Mapped[UUID] = mapped_column(unique=True)
    policy_hash: Mapped[str] = mapped_column(String(64))
    policy: Mapped[dict] = mapped_column(JSONB)
    revoked: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(24))
    reserved: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    actual_cny: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    invoice_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostic: Mapped[dict | None] = mapped_column(JSONB)
