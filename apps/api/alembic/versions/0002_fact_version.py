"""Stable integer fact versions, including existing facts."""
from alembic import op
import sqlalchemy as sa

revision = "0002_fact_version"
down_revision = "0001_experience_library"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("experience_facts", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.alter_column("experience_facts", "version", server_default=None)
    op.create_check_constraint("ck_fact_version", "experience_facts", "version > 0")


def downgrade():
    op.drop_constraint("ck_fact_version", "experience_facts", type_="check")
    op.drop_column("experience_facts", "version")
