"""Mock cost budgets and attempts; no references to private business records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0006_cost_ledger'
down_revision = '0005_answer_questions'
branch_labels = depends_on = None


def upgrade():
    op.create_table('cost_budgets',
        sa.Column('namespace', sa.String(64), primary_key=True),
        sa.Column('kind', sa.String(16), primary_key=True),
        sa.Column('key', sa.String(128), primary_key=True),
        sa.Column('ceiling', sa.Numeric(20,6), nullable=False),
        sa.Column('call_limit', sa.Numeric(20,6), nullable=False),
        sa.Column('held', sa.Numeric(20,6), nullable=False),
        sa.Column('spent', sa.Numeric(20,6), nullable=False),
        sa.Column('frozen', sa.Boolean(), nullable=False),
        sa.Column('max_active', sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('global','provider','model','session')", name='ck_cost_budget_kind'),
        sa.CheckConstraint('ceiling >= 0 AND held >= 0 AND spent >= 0 AND call_limit >= 0', name='ck_cost_budget_money'),
        sa.CheckConstraint('max_active > 0', name='ck_cost_budget_active'))
    op.create_table('cost_calls',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('namespace',sa.String(64),nullable=False),
        sa.Column('operation_hash',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('profile_id',sa.String(64),nullable=False),
        sa.Column('profile_hash',sa.String(64),nullable=False),
        sa.Column('profile_snapshot',JSONB(),nullable=False),
        sa.Column('provider',sa.String(32),nullable=False),
        sa.Column('model',sa.String(64),nullable=False),
        sa.Column('session_tag',sa.String(128),nullable=False),
        sa.Column('transport',sa.String(16),nullable=False),
        sa.Column('state',sa.String(24),nullable=False),
        sa.Column('reserved',sa.Numeric(20,6),nullable=False),
        sa.Column('estimated',sa.Numeric(20,6)),
        sa.Column('actual',sa.Numeric(20,6)),
        sa.Column('invoice_key',sa.String(64),unique=True),
        sa.Column('rate',JSONB(),nullable=False),
        sa.Column('usage',JSONB()),
        sa.Column('model_evidence',JSONB()),
        sa.Column('error_code',sa.String(40)),
        sa.Column('lease_until',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('namespace','operation_hash',name='uq_cost_operation'),
        sa.CheckConstraint("state IN ('reserved','sent','response_received','unknown','reconciled')", name='ck_cost_call_state'),
        sa.CheckConstraint('reserved >= 0 AND (estimated IS NULL OR estimated >= 0) AND (actual IS NULL OR actual >= 0)',name='ck_cost_call_money'),
        sa.CheckConstraint("transport = 'mock'",name='ck_cost_mock_only'))
    op.create_index('ix_cost_calls_namespace','cost_calls',['namespace'])


def downgrade():
    op.drop_table('cost_calls')
    op.drop_table('cost_budgets')
