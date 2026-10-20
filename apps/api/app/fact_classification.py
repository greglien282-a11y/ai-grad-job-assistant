"""C2a isolation only. No classifier, typed writer or public typed projection.

Historical schemas are explicitly recognized, never inferred from a failed query.
Missing privileges, partial columns and unknown classification schema markers
fail closed. Alembic topology is verified separately by migration tooling.
"""
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.maintenance_errors import ConversationError

FIELDS = ('fact_kind', 'progress_stage', 'classification_contract')
LEGACY = ('legacy_unspecified', 'legacy_unknown', 'legacy-v0')
HEAD = '0015_fact_classification'
MARKER = 'pathwise-classification-schema-v1'
CHECK = """((fact_kind='legacy_unspecified' AND progress_stage='legacy_unknown'
 AND classification_contract IN ('legacy-v0','unclassified-v1')) OR
 (classification_contract='explicit-typed-v1' AND
 ((fact_kind='personal_action' AND progress_stage IN ('in_progress','completed')) OR
 (fact_kind='plan' AND progress_stage IN ('planned','in_progress')) OR
 (fact_kind IN ('background','boundary') AND progress_stage='not_applicable'))))"""


def has_columns(db):
    # Catalog-only admission does not add alembic_version SELECT to B2-b roles.
    marker = db.scalar(text("SELECT obj_description('experience_facts'::regclass,'pg_class')")) or ''
    columns = set(db.execute(text("""SELECT attname FROM pg_attribute
        WHERE attrelid='experience_facts'::regclass AND attnum>0 AND NOT attisdropped
          AND attname IN ('fact_kind','progress_stage','classification_contract')""")).scalars())
    functions = db.scalar(text("""SELECT count(*) FROM pg_proc
        WHERE pronamespace=current_schema()::regnamespace AND proname LIKE 'classification_%'"""))
    if MARKER in marker.splitlines() and columns == set(FIELDS) and functions == 3 and db.scalar(text("""SELECT EXISTS(
        SELECT 1 FROM pg_constraint WHERE conrelid='experience_facts'::regclass
        AND conname='ck_fact_classification' AND convalidated)""")) and db.scalar(text("""SELECT count(*) FROM pg_trigger
        WHERE tgrelid IN ('experience_facts'::regclass,'fact_changes'::regclass,
          'fact_sources'::regclass,'conversation_operations'::regclass)
          AND tgname LIKE 'classification_%' AND tgenabled='O'""")) == 8:
        return True
    # Genuine pre-feature schemas only; never default missing current fields.
    if not any(line.startswith('pathwise-classification-schema-') for line in marker.splitlines()) and not columns and functions == 0 and db.scalar(text("SELECT to_regclass('mining_paid_bindings') IS NOT NULL")):
        return False
    raise ConversationError(503, 'fact_classification_schema_unavailable')


def classification(db, fact):
    if not has_columns(db):
        return LEGACY
    return tuple(db.execute(text('SELECT fact_kind,progress_stage,classification_contract '
                                'FROM experience_facts WHERE id=:id'), {'id': fact.id}).one())


def require_legacy(db, sid, *, code='fact_contract_upgrade_required', project_id=None, fact_id=None):
    """Caller must authorize first, and hold the Session lock before mutations."""
    try:
        current = has_columns(db)
        scope = 'f.session_id=:sid'
        params = {'sid': sid}
        if project_id is not None:
            scope += ' AND f.project_id=:pid'; params['pid'] = project_id
        if fact_id is not None:
            scope += ' AND f.id=:fid'; params['fid'] = fact_id
        history = """EXISTS(SELECT 1 FROM fact_changes c WHERE c.fact_id=f.id AND
          ((c.before ?| ARRAY['fact_kind','progress_stage','classification_contract'] AND
            (c.before->>'fact_kind' IS DISTINCT FROM 'legacy_unspecified' OR
             c.before->>'progress_stage' IS DISTINCT FROM 'legacy_unknown' OR
             c.before->>'classification_contract' IS DISTINCT FROM 'legacy-v0')) OR
           (c.after ?| ARRAY['fact_kind','progress_stage','classification_contract'] AND
            (c.after->>'fact_kind' IS DISTINCT FROM 'legacy_unspecified' OR
             c.after->>'progress_stage' IS DISTINCT FROM 'legacy_unknown' OR
             c.after->>'classification_contract' IS DISTINCT FROM 'legacy-v0'))))"""
        condition = history
        if current:
            condition = "(f.fact_kind<>'legacy_unspecified' OR f.progress_stage<>'legacy_unknown' OR f.classification_contract<>'legacy-v0') OR " + history
        if db.scalar(text(f'SELECT EXISTS(SELECT 1 FROM experience_facts f WHERE {scope} AND ({condition}))'), params):
            raise ConversationError(409, code)
    except SQLAlchemyError:
        raise ConversationError(503, 'fact_classification_schema_unavailable') from None
