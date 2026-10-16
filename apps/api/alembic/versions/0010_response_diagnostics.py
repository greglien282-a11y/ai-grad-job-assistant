"""Extend diagnostic codes only; preserve runtime identity, ACL and transitions."""
from alembic import op
import sqlalchemy as sa

revision = '0010_response_diagnostics'
down_revision = '0009_controlled_probe'
branch_labels = depends_on = None

CODES = (
    'controlled_envelope_invalid', 'controlled_model_mismatch',
    'controlled_usage_invalid', 'controlled_output_json_invalid',
    'controlled_output_schema_invalid', 'controlled_facts_invalid',
    'controlled_preview_invalid', 'controlled_output_truncated',
    'controlled_output_refused', 'controlled_output_mode_invalid',
)
OLD = "'controlled_response_invalid',"
NEW = OLD + ','.join("'" + code + "'" for code in CODES) + ','


def replace_whitelist(before, after):
    connection = op.get_bind()
    definition = connection.scalar(sa.text('''SELECT pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname=current_schema() AND p.proname='controlled_runtime'
          AND p.proargtypes='25 25 25 3802'::oidvector'''))
    if definition is None or definition.count(before) != 1:
        raise RuntimeError('controlled_diagnostic_function_unexpected')
    # pg_get_functiondef returns CREATE OR REPLACE. Existing owner, OID,
    # grants, SECURITY DEFINER and search_path remain unchanged.
    # SQLAlchemy compiles literal '%' in PL/pgSQL %ROWTYPE for psycopg's
    # parameter style; passing the definition as raw driver SQL would not.
    connection.execute(sa.text(definition.replace(before, after, 1)))


def upgrade():
    replace_whitelist(OLD, NEW)


def downgrade():
    connection = op.get_bind()
    schema = connection.scalar(sa.text('SELECT current_schema()'))
    q = connection.dialect.identifier_preparer.quote_identifier(schema)
    # Never rewrite or discard an immutable experiment's new diagnostics.
    op.execute(f'LOCK TABLE {q}.paid_funding IN ACCESS EXCLUSIVE MODE')
    op.execute(f'LOCK TABLE {q}.controlled_probe IN ACCESS EXCLUSIVE MODE')
    if connection.scalar(sa.text(f'''SELECT EXISTS(SELECT 1 FROM {q}.controlled_probe
            WHERE diagnostic->>'safe_code' = ANY(:codes))'''), {'codes':list(CODES)}):
        raise RuntimeError('controlled_diagnostic_downgrade_blocked')
    replace_whitelist(NEW, OLD)
