"""Inert metadata only. No body store, authorization or dispatch interface."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base

HASH_FIELDS = ('operation_hash','receipt_hash','root_request_tag','request_sha','context_sha',
    'prompt_sha','prompt_file_sha','schema_sha','schema_file_sha','profile_sha')
CONFIG_FIELDS = ('config_version','prompt_version','schema_version','provider','model',
    'expected_version','version_policy','endpoint','region','deployment','mode','structured_mode')
IDENTITY_FIELDS = ('run_id','root_run_id','session_id','context_revision','contract_version',
    'manifest_version','output_cap',*HASH_FIELDS,*CONFIG_FIELDS)


class RequestManifest(Base):
    __tablename__ = 'mining_request_manifests'
    __table_args__ = (
        CheckConstraint('manifest_version=1 AND contract_version=1 AND context_revision>=0 AND output_cap=1200',name='ck_mrm_versions'),
        CheckConstraint(' AND '.join(f"{n} ~ '^[a-f0-9]{{64}}$'" for n in HASH_FIELDS),name='ck_mrm_hashes'),
        CheckConstraint("storage_state='metadata_only'",name='ck_mrm_inert'),
        CheckConstraint('expires_at>created_at',name='ck_mrm_expiry'),
        CheckConstraint("provider='deepseek_official' AND model='deepseek-flash' AND endpoint='https://api.deepseek.com/chat/completions' AND mode='non_thinking' AND structured_mode='json_object'",name='ck_mrm_target'),)
    # Business erasure cascades; the expiry-bounded, hash-only tombstone below
    # protects the deleted root, independently of 0011's billing audit.
    run_id: Mapped[UUID] = mapped_column(ForeignKey('ai_mining_runs.id',ondelete='CASCADE'),primary_key=True)
    root_run_id: Mapped[UUID] = mapped_column(unique=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('experience_sessions.id',ondelete='CASCADE'))
    context_revision: Mapped[int] = mapped_column(Integer)
    contract_version: Mapped[int] = mapped_column(Integer)
    manifest_version: Mapped[int] = mapped_column(Integer)
    output_cap: Mapped[int] = mapped_column(Integer)
    storage_state: Mapped[str] = mapped_column(String(24),server_default='metadata_only')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.clock_timestamp())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


for _name in HASH_FIELDS:
    setattr(RequestManifest,_name,mapped_column(String(64),nullable=False,unique=_name=='operation_hash'))
for _name in CONFIG_FIELDS:
    setattr(RequestManifest,_name,mapped_column(String(256 if _name=='endpoint' else 64),nullable=False))


class RequestManifestTombstone(Base):
    __tablename__ = 'mining_request_tombstones'
    __table_args__ = (
        CheckConstraint("root_digest ~ '^[a-f0-9]{64}$' AND operation_hash ~ '^[a-f0-9]{64}$' AND request_sha ~ '^[a-f0-9]{64}$'",name='ck_mrt_hashes'),
        CheckConstraint("expires_at=erased_at+interval '24 hours'",name='ck_mrt_expiry'),)
    root_digest: Mapped[str] = mapped_column(String(64),primary_key=True)
    operation_hash: Mapped[str] = mapped_column(String(64),unique=True)
    request_sha: Mapped[str] = mapped_column(String(64))
    erased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
