"""One project per session, extractive mining and short-transaction recovery."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_ai_mining"
down_revision = "0003_idempotency"
branch_labels = depends_on = None


def upgrade():
    # A unique constraint fails safely on legacy multi-project sessions: no merge/deletion.
    op.create_unique_constraint('uq_mvp_one_project', 'experience_projects', ['session_id'])
    op.add_column('experience_sessions', sa.Column('context_revision', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('experience_sessions', sa.Column('mining_status', sa.String(16), nullable=False, server_default='not_started'))
    op.create_check_constraint('ck_context_revision', 'experience_sessions', 'context_revision > 0')
    op.create_check_constraint('ck_mining_status', 'experience_sessions', "mining_status IN ('not_started','active','stopped')")
    op.add_column('experience_facts', sa.Column('origin', sa.String(16), nullable=False, server_default='manual'))
    op.add_column('experience_facts', sa.Column('memory_state', sa.String(16), nullable=False, server_default='unspecified'))
    op.add_column('experience_facts', sa.Column('ai_run_id', sa.Uuid()))
    op.create_check_constraint('ck_fact_origin', 'experience_facts', "origin IN ('manual','ai_extracted')")
    op.create_check_constraint('ck_fact_memory', 'experience_facts', "memory_state IN ('unspecified','certain','approximate','needs_check')")
    op.add_column('fact_sources', sa.Column('citations', JSONB()))
    op.create_table('ai_mining_runs',
        sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('experience_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False), sa.Column('input_turn_id', sa.Uuid(), nullable=False),
        sa.Column('base_revision', sa.Integer(), nullable=False), sa.Column('reserved_revision', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False), sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('error_code', sa.String(48)), sa.Column('retry_of', sa.Uuid(), sa.ForeignKey('ai_mining_runs.id', ondelete='SET NULL')),
        sa.Column('provider', sa.String(32), nullable=False), sa.Column('prompt_version', sa.String(16), nullable=False),
        sa.Column('tokens_in', sa.Integer(), nullable=False), sa.Column('tokens_out', sa.Integer(), nullable=False),
        sa.Column('assistant_turn_id', sa.Uuid(), sa.ForeignKey('conversation_turns.id', ondelete='SET NULL')),
        sa.ForeignKeyConstraint(['project_id','session_id'], ['experience_projects.id','experience_projects.session_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['input_turn_id','session_id'], ['conversation_turns.id','conversation_turns.session_id'], ondelete='CASCADE'),
        sa.CheckConstraint("state IN ('reserved','running','completed','failed','unknown','stale')", name='ck_mining_state'),
        sa.CheckConstraint('base_revision > 0 AND reserved_revision >= base_revision', name='ck_mining_revisions'))
    op.create_unique_constraint('uq_mining_retry_parent', 'ai_mining_runs', ['retry_of'])
    op.create_index('ix_ai_mining_runs_session_id', 'ai_mining_runs', ['session_id'])
    op.create_index('uq_mining_active', 'ai_mining_runs', ['session_id'], unique=True, postgresql_where=sa.text("state IN ('reserved','running')"))
    op.create_foreign_key('fk_fact_ai_run', 'experience_facts', 'ai_mining_runs', ['ai_run_id'], ['id'], ondelete='SET NULL')
    op.create_table('ai_mining_receipts',
        sa.Column('key_digest', sa.String(64), primary_key=True), sa.Column('state', sa.String(16), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('experience_sessions.id')),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('ai_mining_runs.id')), sa.Column('request_tag', sa.String(64)),
        sa.CheckConstraint("(state='live' AND session_id IS NOT NULL AND run_id IS NOT NULL AND request_tag IS NOT NULL) OR (state='deleted' AND session_id IS NULL AND run_id IS NULL AND request_tag IS NULL)", name='ck_mining_receipt'))
    for col in ('session_id','expires_at'):
        op.create_index('ix_ai_mining_receipts_'+col, 'ai_mining_receipts', [col])
    op.create_table('ai_mining_questions',
        sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('experience_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('ai_mining_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text()), sa.Column('state', sa.String(16), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("state IN ('active','skipped','corrected','hidden','deleted')", name='ck_question_state'),
        sa.CheckConstraint("(state='deleted' AND content IS NULL) OR (state!='deleted' AND content IS NOT NULL)", name='ck_question_content'))
    op.create_index('ix_ai_mining_questions_session_id', 'ai_mining_questions', ['session_id'])
    op.create_table('ai_mining_capacity', sa.Column('id', sa.Integer(), primary_key=True))
    op.execute('INSERT INTO ai_mining_capacity (id) VALUES (1)')
    # Row changes, not requests: old APIs and new APIs share the same context clock.
    op.execute('''CREATE FUNCTION pathwise_bump_context() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      UPDATE experience_sessions SET context_revision=context_revision+1, updated_at=clock_timestamp()
        WHERE id=CASE WHEN TG_OP='DELETE' THEN OLD.session_id ELSE NEW.session_id END;
      RETURN NULL;
    END $$''')
    for table in ('experience_projects','conversation_turns','experience_facts','fact_evidence','ai_mining_questions'):
        op.execute(f'CREATE TRIGGER bump_context AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION pathwise_bump_context()')
    op.execute('''CREATE FUNCTION pathwise_session_context() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.status IS DISTINCT FROM OLD.status OR NEW.mining_status IS DISTINCT FROM OLD.mining_status THEN
        NEW.context_revision=OLD.context_revision+1;
      END IF;
      RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER session_context BEFORE UPDATE ON experience_sessions FOR EACH ROW EXECUTE FUNCTION pathwise_session_context()')
    op.execute('''CREATE FUNCTION pathwise_user_source() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM conversation_turns WHERE id=NEW.turn_id AND session_id=NEW.session_id AND role='user') THEN
        RAISE EXCEPTION 'user source required' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER user_source BEFORE INSERT OR UPDATE ON fact_sources FOR EACH ROW EXECUTE FUNCTION pathwise_user_source()')
    op.execute('''CREATE FUNCTION pathwise_immutable_turn() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.id IS DISTINCT FROM OLD.id OR NEW.session_id IS DISTINCT FROM OLD.session_id
         OR NEW.role IS DISTINCT FROM OLD.role OR NEW.content IS DISTINCT FROM OLD.content THEN
        RAISE EXCEPTION 'conversation turns are immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER immutable_turn BEFORE UPDATE ON conversation_turns FOR EACH ROW EXECUTE FUNCTION pathwise_immutable_turn()')


def downgrade():
    for table in ('experience_projects','conversation_turns','experience_facts','fact_evidence','ai_mining_questions'):
        op.execute(f'DROP TRIGGER bump_context ON {table}')
    op.execute('DROP TRIGGER session_context ON experience_sessions')
    op.execute('DROP TRIGGER user_source ON fact_sources')
    op.execute('DROP TRIGGER immutable_turn ON conversation_turns')
    for name in ('pathwise_bump_context','pathwise_session_context','pathwise_user_source','pathwise_immutable_turn'):
        op.execute(f'DROP FUNCTION {name}()')
    op.drop_constraint('fk_fact_ai_run', 'experience_facts', type_='foreignkey')
    for table in ('ai_mining_questions','ai_mining_receipts','ai_mining_runs','ai_mining_capacity'):
        op.drop_table(table)
    op.drop_column('fact_sources', 'citations')
    for name in ('ck_fact_origin','ck_fact_memory'):
        op.drop_constraint(name, 'experience_facts', type_='check')
    for col in ('ai_run_id','origin','memory_state'):
        op.drop_column('experience_facts', col)
    for name in ('ck_context_revision','ck_mining_status'):
        op.drop_constraint(name, 'experience_sessions', type_='check')
    for col in ('context_revision','mining_status'):
        op.drop_column('experience_sessions', col)
    op.drop_constraint('uq_mvp_one_project', 'experience_projects', type_='unique')
