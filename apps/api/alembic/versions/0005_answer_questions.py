"""Answer/question identity links; no copies of private question text."""
from alembic import op
import sqlalchemy as sa

revision = '0005_answer_questions'
down_revision = '0004_ai_mining'
branch_labels = depends_on = None


def upgrade():
    op.create_unique_constraint('uq_question_session', 'ai_mining_questions', ['id','session_id'])
    op.create_table('ai_answer_questions',
        sa.Column('turn_id', sa.Uuid(), primary_key=True),
        sa.Column('question_id', sa.Uuid(), primary_key=True),
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('question_version', sa.Integer(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['turn_id','session_id'], ['conversation_turns.id','conversation_turns.session_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id','session_id'], ['ai_mining_questions.id','ai_mining_questions.session_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('turn_id','slot', name='uq_answer_question_slot'),
        sa.CheckConstraint('slot IN (1,2) AND question_version > 0', name='ck_answer_question_slot'))
    op.execute('CREATE TRIGGER user_source BEFORE INSERT ON ai_answer_questions FOR EACH ROW EXECUTE FUNCTION pathwise_user_source()')
    op.execute('CREATE TRIGGER bump_context AFTER INSERT OR DELETE ON ai_answer_questions FOR EACH ROW EXECUTE FUNCTION pathwise_bump_context()')
    op.execute('''CREATE FUNCTION pathwise_immutable_answer_link() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'answer question links are immutable' USING ERRCODE='23514';
    END $$''')
    op.execute('CREATE TRIGGER immutable_answer_link BEFORE UPDATE ON ai_answer_questions FOR EACH ROW EXECUTE FUNCTION pathwise_immutable_answer_link()')


def downgrade():
    op.drop_table('ai_answer_questions')
    op.execute('DROP FUNCTION pathwise_immutable_answer_link()')
    op.drop_constraint('uq_question_session', 'ai_mining_questions', type_='unique')
