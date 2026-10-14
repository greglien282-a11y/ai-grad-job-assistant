"""ID-only operation receipts; deletion erases every linked/derived value."""
from alembic import op
import sqlalchemy as sa

revision = "0003_idempotency"
down_revision = "0002_fact_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('idempotency_operations',
        sa.Column('key_digest', sa.String(64), primary_key=True),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('operation', sa.String(24)),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('experience_sessions.id')),
        sa.Column('target_id', sa.Uuid()),
        sa.Column('request_tag', sa.String(64)),
        *[sa.Column(name, sa.Uuid()) for name in ('project_id', 'initial_turn_id', 'turn_id', 'fact_id')],
        sa.CheckConstraint("state IN ('completed','deleted')", name='ck_operation_state'),
        sa.CheckConstraint("(state='deleted' AND operation IS NULL AND session_id IS NULL AND target_id IS NULL AND request_tag IS NULL AND project_id IS NULL AND initial_turn_id IS NULL AND turn_id IS NULL AND fact_id IS NULL) OR (state='completed' AND session_id IS NOT NULL AND request_tag IS NOT NULL AND ((operation='create_session' AND project_id IS NOT NULL AND initial_turn_id IS NOT NULL) OR (operation='add_turn' AND target_id IS NOT NULL AND turn_id IS NOT NULL) OR (operation='add_fact' AND target_id IS NOT NULL AND fact_id IS NOT NULL)))", name='ck_operation_receipt'))
    op.create_index('ix_idempotency_operations_session_id', 'idempotency_operations', ['session_id'])
    op.create_index('ix_idempotency_operations_expires_at', 'idempotency_operations', ['expires_at'])


def downgrade():
    op.drop_index("ix_idempotency_operations_session_id", "idempotency_operations")
    op.drop_index("ix_idempotency_operations_expires_at", "idempotency_operations")
    op.drop_table("idempotency_operations")
