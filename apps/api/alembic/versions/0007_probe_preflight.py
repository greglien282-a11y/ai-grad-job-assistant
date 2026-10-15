"""C-0 fixture-only approval preflights. Real authority is constrained to zero."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0007_probe_preflight'
down_revision='0006_cost_ledger'
branch_labels=depends_on=None


def upgrade():
    op.create_table('probe_funding',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('approved_real_cny',sa.Numeric(20,6),nullable=False),
        sa.Column('fixture_ceiling',sa.Numeric(20,6),nullable=False),
        sa.Column('held',sa.Numeric(20,6),nullable=False),
        sa.Column('spent',sa.Numeric(20,6),nullable=False),
        sa.Column('frozen',sa.Boolean(),nullable=False),
        sa.Column('last_review_digest',sa.String(64)),
        sa.CheckConstraint('id = 1 AND approved_real_cny = 0',name='ck_probe_zero_authority'),
        sa.CheckConstraint('fixture_ceiling >= 0 AND held >= 0 AND spent >= 0',name='ck_probe_funding_money'))
    op.create_table('probe_grants',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('pool_id',sa.Integer(),sa.ForeignKey('probe_funding.id'),nullable=False),
        sa.Column('mode',sa.String(24),nullable=False),
        sa.Column('approved_real_cny',sa.Numeric(20,6),nullable=False),
        sa.Column('starts_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('fixture_limit',sa.Numeric(20,6),nullable=False),
        sa.Column('calls_limit',sa.Integer(),nullable=False),
        sa.Column('policy',JSONB(),nullable=False),
        sa.CheckConstraint("mode IN ('draft','offline_fixture','revoked')",name='ck_probe_grant_mode'),
        sa.CheckConstraint('pool_id = 1 AND approved_real_cny = 0',name='ck_probe_grant_zero'),
        sa.CheckConstraint('starts_at < expires_at AND fixture_limit >= 0 AND calls_limit > 0',name='ck_probe_grant_limits'))
    op.create_table('probe_attempts',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('grant_id',sa.Uuid(),sa.ForeignKey('probe_grants.id'),nullable=False),
        sa.Column('operation_hash',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('policy_snapshot',JSONB(),nullable=False),
        sa.Column('batch_tag',sa.String(64),nullable=False),
        sa.Column('execution',sa.String(24),nullable=False),
        sa.Column('state',sa.String(24),nullable=False),
        sa.Column('reserved',sa.Numeric(20,6),nullable=False),
        sa.Column('actual',sa.Numeric(20,6)),
        sa.Column('invoice_hash',sa.String(64),unique=True),
        sa.Column('lease_until',sa.DateTime(timezone=True),nullable=False),
        sa.Column('error_code',sa.String(40)),
        sa.Column('usage',JSONB()),
        sa.UniqueConstraint('operation_hash',name='uq_probe_operation'),
        sa.CheckConstraint("state IN ('reserved','sent','response_received','unknown','reconciled')",name='ck_probe_attempt_state'),
        sa.CheckConstraint("execution = 'offline_http_fixture'",name='ck_probe_attempt_offline'),
        sa.CheckConstraint('reserved >= 0 AND (actual IS NULL OR actual >= 0)',name='ck_probe_attempt_money'))


def downgrade():
    op.drop_table('probe_attempts')
    op.drop_table('probe_grants')
    op.drop_table('probe_funding')
