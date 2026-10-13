"""Initial experience persistence schema (frozen; independent of live models)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_experience_library'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('experience_sessions',
    sa.Column('access_token_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('active', 'ended')", name='ck_session_status'),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('conversation_turns',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('user', 'assistant')", name='ck_turn_role'),
    sa.ForeignKeyConstraint(['session_id'], ['experience_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_turn_session')
    )

    op.create_index(op.f('ix_conversation_turns_session_id'), 'conversation_turns', ['session_id'], unique=False)

    op.create_table('experience_projects',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('raw_input', sa.Text(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['experience_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_project_session')
    )

    op.create_index(op.f('ix_experience_projects_session_id'), 'experience_projects', ['session_id'], unique=False)

    op.create_table('experience_facts',
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('evidence_id', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status != 'evidence_supported' OR evidence_id IS NOT NULL", name='ck_fact_evidence'),
    sa.CheckConstraint("status IN ('pending', 'user_confirmed', 'evidence_supported', 'rejected')", name='ck_fact_status'),
    sa.CheckConstraint('length(trim(statement)) > 0', name='ck_fact_statement'),
    sa.ForeignKeyConstraint(['project_id', 'session_id'], ['experience_projects.id', 'experience_projects.session_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_fact_session')
    )

    op.create_index(op.f('ix_experience_facts_project_id'), 'experience_facts', ['project_id'], unique=False)

    op.create_index(op.f('ix_experience_facts_session_id'), 'experience_facts', ['session_id'], unique=False)

    op.create_table('fact_changes',
    sa.Column('fact_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('actor', sa.String(length=16), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("actor IN ('user', 'system')", name='ck_change_actor'),
    sa.ForeignKeyConstraint(['fact_id', 'session_id'], ['experience_facts.id', 'experience_facts.session_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_index(op.f('ix_fact_changes_fact_id'), 'fact_changes', ['fact_id'], unique=False)

    op.create_table('fact_evidence',
    sa.Column('fact_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('material_reference', sa.Text(), nullable=False),
    sa.Column('basis', sa.Text(), nullable=False),
    sa.Column('reviewer', sa.String(length=16), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("reviewer = 'user'", name='ck_evidence_reviewer'),
    sa.CheckConstraint('length(trim(material_reference)) > 0 AND length(trim(basis)) > 0', name='ck_evidence_basis'),
    sa.ForeignKeyConstraint(['fact_id', 'session_id'], ['experience_facts.id', 'experience_facts.session_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'fact_id', 'session_id', name='uq_evidence_fact_session')
    )

    op.create_table('fact_sources',
    sa.Column('fact_id', sa.Uuid(), nullable=False),
    sa.Column('turn_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['fact_id', 'session_id'], ['experience_facts.id', 'experience_facts.session_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['turn_id', 'session_id'], ['conversation_turns.id', 'conversation_turns.session_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('fact_id', 'turn_id')
    )

    op.create_foreign_key('fk_fact_current_evidence', 'experience_facts', 'fact_evidence', ['evidence_id', 'id', 'session_id'], ['id', 'fact_id', 'session_id'], use_alter=True)


def downgrade():
    op.drop_constraint('fk_fact_current_evidence', 'experience_facts', type_='foreignkey')
    op.drop_table('fact_sources')
    op.drop_table('fact_evidence')
    op.drop_table('fact_changes')
    op.drop_table('experience_facts')
    op.drop_table('experience_projects')
    op.drop_table('conversation_turns')
    op.drop_table('experience_sessions')
