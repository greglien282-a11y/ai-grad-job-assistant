"""C2a classification foundation; no runtime typed writer or history backfill."""
from alembic import op
import sqlalchemy as sa

revision = '0015_fact_classification'
down_revision = '0014_append_batch'
branch_labels = depends_on = None

CHECK = """((fact_kind='legacy_unspecified' AND progress_stage='legacy_unknown'
 AND classification_contract IN ('legacy-v0','unclassified-v1')) OR
 (classification_contract='explicit-typed-v1' AND
 ((fact_kind='personal_action' AND progress_stage IN ('in_progress','completed')) OR
 (fact_kind='plan' AND progress_stage IN ('planned','in_progress')) OR
 (fact_kind IN ('background','boundary') AND progress_stage='not_applicable'))))"""
FUNCTIONS = ('classification_value(jsonb)', 'classification_current()', 'classification_guard()')
TYPED_HISTORY = """EXISTS(SELECT 1 FROM {q}.fact_changes h WHERE h.fact_id=f.id AND
 ((h.before ?| ARRAY['fact_kind','progress_stage','classification_contract'] AND
   (h.before->>'fact_kind' IS DISTINCT FROM 'legacy_unspecified' OR
    h.before->>'progress_stage' IS DISTINCT FROM 'legacy_unknown' OR
    h.before->>'classification_contract' IS DISTINCT FROM 'legacy-v0')) OR
  (h.after ?| ARRAY['fact_kind','progress_stage','classification_contract'] AND
   (h.after->>'fact_kind' IS DISTINCT FROM 'legacy_unspecified' OR
    h.after->>'progress_stage' IS DISTINCT FROM 'legacy_unknown' OR
    h.after->>'classification_contract' IS DISTINCT FROM 'legacy-v0'))))"""


def namespace():
    conn = op.get_bind()
    q = conn.dialect.identifier_preparer.quote_identifier(conn.scalar(sa.text('SELECT current_schema()')))
    op.execute(f'LOCK TABLE {q}.experience_sessions,{q}.experience_facts,{q}.fact_changes,{q}.fact_sources,{q}.conversation_operations,{q}.fact_change_sources IN ACCESS EXCLUSIVE MODE NOWAIT')
    return q


def upgrade():
    q = namespace()
    conn = op.get_bind()
    old_comment = conn.scalar(sa.text("SELECT obj_description('experience_facts'::regclass,'pg_class')")) or ''
    comment = (old_comment + '\npathwise-classification-schema-v1').replace("'", "''")
    op.execute(f"COMMENT ON TABLE {q}.experience_facts IS '{comment}'")
    for field, default in (('fact_kind', 'legacy_unspecified'), ('progress_stage', 'legacy_unknown'),
                           ('classification_contract', 'legacy-v0')):
        op.add_column('experience_facts', sa.Column(field, sa.String(24), nullable=False, server_default=default))
    op.create_check_constraint('ck_fact_classification', 'experience_facts', CHECK)
    # Missing all three keys is the only old-snapshot legacy interpretation.
    # Never write normalized values back into an existing JSON object.
    op.execute(f"""CREATE FUNCTION {q}.classification_value(s jsonb) RETURNS jsonb
      LANGUAGE plpgsql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
      DECLARE k text; p text; c text;
      BEGIN
        IF NOT coalesce(s ?| ARRAY['fact_kind','progress_stage','classification_contract'],false) THEN
          RETURN jsonb_build_array('legacy_unspecified','legacy_unknown','legacy-v0'); END IF;
        k:=s->>'fact_kind'; p:=s->>'progress_stage'; c:=s->>'classification_contract';
        IF jsonb_typeof(s->'fact_kind') IS DISTINCT FROM 'string'
          OR jsonb_typeof(s->'progress_stage') IS DISTINCT FROM 'string'
          OR jsonb_typeof(s->'classification_contract') IS DISTINCT FROM 'string'
          OR NOT coalesce((k='legacy_unspecified' AND p='legacy_unknown' AND c IN ('legacy-v0','unclassified-v1'))
            OR (c='explicit-typed-v1' AND ((k='personal_action' AND p IN ('in_progress','completed'))
              OR (k='plan' AND p IN ('planned','in_progress'))
              OR (k IN ('background','boundary') AND p='not_applicable'))),false) THEN
          RAISE EXCEPTION 'classification_snapshot_invalid' USING ERRCODE='23514'; END IF;
        RETURN jsonb_build_array(k,p,c);
      END $$""")
    typed = TYPED_HISTORY.format(q=q)
    op.execute(f"""CREATE FUNCTION {q}.classification_current() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      DECLARE f {q}.experience_facts%ROWTYPE; fid uuid;
      BEGIN
        IF TG_TABLE_NAME='conversation_operations' THEN
          IF EXISTS(SELECT 1 FROM {q}.experience_facts candidate WHERE candidate.session_id=NEW.session_id
            AND (candidate.classification_contract<>'legacy-v0' OR {typed.replace('f.id', 'candidate.id')})) THEN
            RAISE EXCEPTION 'classification_legacy_operation_refused' USING ERRCODE='23514'; END IF;
          RETURN NULL;
        ELSIF TG_TABLE_NAME='fact_changes' THEN
          PERFORM {q}.classification_value(NEW.before);
          PERFORM {q}.classification_value(NEW.after);
          fid:=NEW.fact_id;
        ELSE fid:=NEW.id; END IF;
        SELECT * INTO f FROM {q}.experience_facts WHERE id=fid;
        IF f.id IS NULL THEN RETURN NULL; END IF; -- whole-session erasure
        IF f.classification_contract<>'legacy-v0' OR {typed} THEN
          IF (SELECT count(*) FROM {q}.fact_changes WHERE fact_id=f.id AND action='created')<>1
            OR NOT EXISTS(SELECT 1 FROM {q}.fact_changes c WHERE c.fact_id=f.id AND c.action='created'
              AND c.after->'original_source_turn_ids'=(SELECT jsonb_agg(turn_id::text ORDER BY turn_id::text)
                FROM {q}.fact_sources WHERE fact_id=f.id)) THEN
            RAISE EXCEPTION 'classification_original_source_invalid' USING ERRCODE='23514'; END IF;
          IF f.classification_contract='legacy-v0' OR NOT EXISTS(
            SELECT 1 FROM {q}.fact_changes c WHERE c.fact_id=f.id AND c.session_id=f.session_id
              AND jsonb_typeof(c.after->'version')='number' AND c.after->>'version'=f.version::text
              AND c.after->>'statement'=f.statement AND c.after->>'status'=f.status
              AND c.after->'evidence_id'=coalesce(to_jsonb(f.evidence_id),'null'::jsonb)
              AND c.after ?& ARRAY['fact_kind','progress_stage','classification_contract']
              AND {q}.classification_value(c.after)=jsonb_build_array(f.fact_kind,f.progress_stage,f.classification_contract)) THEN
            RAISE EXCEPTION 'classification_current_mismatch' USING ERRCODE='23514'; END IF;
        END IF;
        RETURN NULL;
      END $$""")
    op.execute(f"""CREATE FUNCTION {q}.classification_guard() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      DECLARE f {q}.experience_facts%ROWTYPE; fid uuid;
      BEGIN
        IF TG_OP='TRUNCATE' THEN
          -- TRUNCATE already holds the source-table ACCESS EXCLUSIVE lock.
          -- The original maintenance trigger retains its legacy lock policy.
          IF EXISTS(SELECT 1 FROM {q}.experience_facts candidate WHERE candidate.classification_contract<>'legacy-v0' OR {typed.replace('f.id', 'candidate.id')}) THEN
            RAISE EXCEPTION 'classification_immutable' USING ERRCODE='23514'; END IF;
          RETURN NULL;
        END IF;
        IF TG_TABLE_NAME IN ('fact_sources','fact_changes') AND TG_OP='UPDATE' THEN
          IF NEW.fact_id IS DISTINCT FROM OLD.fact_id AND EXISTS(
            SELECT 1 FROM {q}.experience_facts candidate WHERE candidate.id=NEW.fact_id
              AND (candidate.classification_contract<>'legacy-v0' OR {typed.replace('f.id', 'candidate.id')})) THEN
            RAISE EXCEPTION 'classification_immutable' USING ERRCODE='23514'; END IF;
        END IF;
        IF TG_TABLE_NAME='experience_facts' THEN
          IF TG_OP='INSERT' THEN
            -- Existing runtime INSERT grants do not authorize typed creation.
            -- Only trusted migration-owner synthetic fixtures can arrange it.
            IF NEW.classification_contract<>'legacy-v0' AND NOT pg_has_role(session_user,
              (SELECT relowner FROM pg_class WHERE oid=TG_RELID),'USAGE') THEN
              RAISE EXCEPTION 'classification_writer_unapproved' USING ERRCODE='23514'; END IF;
            RETURN NEW;
          END IF;
          IF TG_OP='UPDATE' AND (NEW.fact_kind,NEW.progress_stage,NEW.classification_contract)
            IS DISTINCT FROM (OLD.fact_kind,OLD.progress_stage,OLD.classification_contract) THEN
            RAISE EXCEPTION 'classification_command_unavailable' USING ERRCODE='23514'; END IF;
          fid:=OLD.id;
        ELSIF TG_OP='INSERT' THEN fid:=NEW.fact_id;
        ELSE fid:=OLD.fact_id; END IF;
        SELECT * INTO f FROM {q}.experience_facts WHERE id=fid;
        IF f.id IS NOT NULL AND (f.classification_contract<>'legacy-v0' OR {typed}) THEN
          IF TG_OP='INSERT' AND (SELECT xmin::text::bigint FROM {q}.experience_facts WHERE id=f.id)
            =pg_current_xact_id()::text::bigint % 4294967296 THEN RETURN NEW; END IF;
          IF TG_OP='DELETE' AND NOT EXISTS(SELECT 1 FROM {q}.experience_sessions WHERE id=f.session_id) THEN RETURN OLD; END IF;
          RAISE EXCEPTION 'classification_immutable' USING ERRCODE='23514'; END IF;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
      END $$""")
    for table, events in (('experience_facts','INSERT OR UPDATE'), ('fact_changes','INSERT OR UPDATE'),
                          ('conversation_operations','INSERT')):
        op.execute(f'CREATE CONSTRAINT TRIGGER classification_consistent AFTER {events} ON {q}.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {q}.classification_current()')
    for table, events in (('experience_facts','INSERT OR UPDATE OR DELETE'), ('fact_changes','INSERT OR UPDATE OR DELETE'),
                          ('fact_sources','INSERT OR UPDATE OR DELETE')):
        op.execute(f'CREATE TRIGGER classification_immutable BEFORE {events} ON {q}.{table} FOR EACH ROW EXECUTE FUNCTION {q}.classification_guard()')
    op.execute(f'CREATE TRIGGER classification_no_truncate BEFORE TRUNCATE ON {q}.fact_sources FOR EACH STATEMENT EXECUTE FUNCTION {q}.classification_guard()')
    # Follow the existing audited owner; runtime admission still refuses LOGIN
    # owners. No new role, grant, callable helper or deployment is configured.
    conn = op.get_bind()
    quote = conn.dialect.identifier_preparer.quote_identifier
    owner = conn.scalar(sa.text("SELECT r.rolname FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.oid=CAST(:fn AS regprocedure)"), {'fn': f'{q}.maintenance_current_fact()'})
    for fn in FUNCTIONS:
        grantees = conn.scalars(sa.text("""SELECT DISTINCT r.rolname FROM pg_proc p
          CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
          JOIN pg_roles r ON r.oid=a.grantee WHERE p.oid=CAST(:fn AS regprocedure) AND a.grantee<>p.proowner"""), {'fn': f'{q}.{fn}'}).all()
        op.execute(f'REVOKE ALL ON FUNCTION {q}.{fn} FROM PUBLIC')
        for name in grantees:
            op.execute(f'REVOKE ALL ON FUNCTION {q}.{fn} FROM {quote(name)}')
        op.execute(f'ALTER FUNCTION {q}.{fn} OWNER TO {quote(owner)}')


def downgrade():
    q = namespace()
    if op.get_bind().scalar(sa.text(f"""SELECT EXISTS(SELECT 1 FROM {q}.experience_facts f
      WHERE f.classification_contract<>'legacy-v0' OR {TYPED_HISTORY.format(q=q)})""")):
        raise RuntimeError('classification_nonempty_downgrade_refused')
    for table in ('experience_facts','fact_changes','conversation_operations'):
        op.execute(f'DROP TRIGGER classification_consistent ON {q}.{table}')
    for table in ('experience_facts','fact_changes','fact_sources'):
        op.execute(f'DROP TRIGGER classification_immutable ON {q}.{table}')
    op.execute(f'DROP TRIGGER classification_no_truncate ON {q}.fact_sources')
    for fn in reversed(FUNCTIONS):
        op.execute(f'DROP FUNCTION {q}.{fn}')
    op.drop_constraint('ck_fact_classification', 'experience_facts', type_='check')
    for field in ('classification_contract','progress_stage','fact_kind'):
        op.drop_column('experience_facts', field)
    comment = op.get_bind().scalar(sa.text("SELECT obj_description('experience_facts'::regclass,'pg_class')")) or ''
    comment = comment.removesuffix('\npathwise-classification-schema-v1')
    op.execute(f"COMMENT ON TABLE {q}.experience_facts IS " + ("'" + comment.replace("'", "''") + "'" if comment else 'NULL'))
