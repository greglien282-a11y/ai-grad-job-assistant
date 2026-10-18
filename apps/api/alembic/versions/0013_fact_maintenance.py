"""Inert B2-a fact-operation metadata; no API or grants."""
from alembic import op
import sqlalchemy as sa
revision='0013_fact_maintenance'
down_revision='0012_request_manifest'
branch_labels=depends_on=None

DDL = """
CREATE TABLE conversation_operations (
	id UUID NOT NULL,
	contract_version SMALLINT NOT NULL,
	key_digest VARCHAR(64) NOT NULL,
	state VARCHAR(24) NOT NULL,
	session_id UUID,
	input_turn_id UUID,
	kind VARCHAR(16),
	action VARCHAR(24),
	parent_operation_id UUID,
	submission_tag VARCHAR(64),
	request_tag VARCHAR(64),
	proposed_action VARCHAR(24),
	proposal_spans JSONB,
	progress_stage VARCHAR(24),
	base_revision INTEGER,
	result_revision INTEGER,
	target_fact_id UUID,
	target_version INTEGER,
	effect_count SMALLINT,
	outcome_code VARCHAR(32),
	decision_contract VARCHAR(32),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_co_session UNIQUE (id, session_id),
	FOREIGN KEY(session_id) REFERENCES experience_sessions (id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(input_turn_id, session_id) REFERENCES conversation_turns (id, session_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(target_fact_id, session_id) REFERENCES experience_facts (id, session_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(parent_operation_id, session_id) REFERENCES conversation_operations (id, session_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_co_identity CHECK (contract_version=1 AND key_digest ~ '^[a-f0-9]{64}$' AND state IN ('applied','needs_clarification','deleted')),
	CONSTRAINT ck_co_expiry CHECK (expires_at>created_at),
	CONSTRAINT ck_co_shape CHECK (((state='deleted' AND num_nonnulls(session_id,input_turn_id,kind,action,parent_operation_id,submission_tag,request_tag,proposed_action,proposal_spans,progress_stage,base_revision,result_revision,target_fact_id,target_version,effect_count,outcome_code,decision_contract,completed_at)=0) OR (state<>'deleted' AND session_id IS NOT NULL AND input_turn_id IS NOT NULL AND kind IS NOT NULL AND action IS NOT NULL AND proposal_spans IS NOT NULL AND base_revision>0 AND result_revision>=base_revision AND effect_count BETWEEN 0 AND 5 AND request_tag ~ '^[a-f0-9]{64}$' AND decision_contract='explicit-target-v1' AND completed_at>=created_at)) IS TRUE),
	UNIQUE (key_digest)
);
CREATE INDEX ix_co_expired ON conversation_operations (expires_at) WHERE state='deleted';
CREATE INDEX ix_co_input ON conversation_operations (input_turn_id);
CREATE INDEX ix_co_session_created ON conversation_operations (session_id, created_at, id);
CREATE UNIQUE INDEX uq_co_resolution ON conversation_operations (parent_operation_id) WHERE state<>'deleted';
CREATE UNIQUE INDEX uq_co_submission ON conversation_operations (session_id, submission_tag) WHERE kind='root' AND state<>'deleted';
CREATE TABLE fact_change_sources (
	id UUID NOT NULL,
	operation_id UUID NOT NULL,
	effect_slot SMALLINT NOT NULL,
	change_id UUID NOT NULL,
	fact_id UUID NOT NULL,
	session_id UUID NOT NULL,
	turn_id UUID NOT NULL,
	source_role VARCHAR(16) NOT NULL,
	reason VARCHAR(24) NOT NULL,
	start_cp INTEGER NOT NULL,
	end_cp INTEGER NOT NULL,
	quote TEXT NOT NULL,
	before_version INTEGER,
	after_version INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(change_id, fact_id, session_id) REFERENCES fact_changes (id, fact_id, session_id) ON DELETE CASCADE,
	FOREIGN KEY(operation_id, session_id) REFERENCES conversation_operations (id, session_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(turn_id, session_id) REFERENCES conversation_turns (id, session_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT uq_fcs_change_role UNIQUE (change_id, source_role),
	CONSTRAINT uq_fcs_effect_role UNIQUE (operation_id, effect_slot, source_role),
	CONSTRAINT ck_fcs_kind CHECK (effect_slot BETWEEN 1 AND 5 AND source_role IN ('statement','intent') AND reason IN ('addition','explicit_correction','explicit_withdrawal','progress_update')),
	CONSTRAINT ck_fcs_quote CHECK (start_cp>=0 AND end_cp>start_cp AND length(quote) BETWEEN 1 AND 10000 AND (source_role<>'statement' OR length(quote)<=500)),
	CONSTRAINT ck_fcs_versions CHECK (after_version>0 AND (before_version IS NULL OR before_version>0))
);
CREATE INDEX ix_fcs_fact_version ON fact_change_sources (fact_id, after_version);
CREATE INDEX ix_fcs_turn ON fact_change_sources (turn_id);
"""

def upgrade():
    conn=op.get_bind()
    q=conn.dialect.identifier_preparer.quote_identifier(conn.scalar(sa.text('SELECT current_schema()')))
    op.execute(f'LOCK TABLE {q}.experience_sessions, {q}.experience_facts, {q}.fact_changes IN ACCESS EXCLUSIVE MODE NOWAIT')
    op.create_unique_constraint('uq_change_fact_session','fact_changes',['id','fact_id','session_id'])
    op.execute(DDL)
    install(q)


def install(q):
    # All names are migration-quoted, all runtime data is typed. No runtime SQL
    # interpolation or externally selected namespace, no paid_* writes/grants.
    op.execute(f'''CREATE FUNCTION {q}.maintenance_validate(oid uuid) RETURNS void
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      DECLARE o {q}.conversation_operations%ROWTYPE; p {q}.conversation_operations%ROWTYPE;
        t {q}.conversation_turns%ROWTYPE; s {q}.experience_sessions%ROWTYPE;
        c {q}.fact_changes%ROWTYPE; f {q}.experience_facts%ROWTYPE;
        r record; span jsonb; n integer; ns integer; ni integer; total integer;
        a text; expected_reason text;
      BEGIN
        SELECT * INTO o FROM {q}.conversation_operations WHERE id=oid;
        IF o.id IS NULL OR o.state='deleted' THEN RETURN; END IF;
        SELECT * INTO s FROM {q}.experience_sessions WHERE id=o.session_id FOR UPDATE;
        SELECT * INTO t FROM {q}.conversation_turns WHERE id=o.input_turn_id;
        IF s.id IS NULL OR s.status<>'active' OR t.id IS NULL OR t.session_id<>s.id OR t.role<>'user'
          OR o.result_revision IS DISTINCT FROM s.context_revision OR o.base_revision IS NULL
          OR o.base_revision>o.result_revision OR o.effect_count IS NULL
          OR o.request_tag IS NULL OR o.request_tag !~ '^[a-f0-9]{{64}}$'
          OR o.decision_contract IS DISTINCT FROM 'explicit-target-v1'
          OR o.expires_at<=clock_timestamp() OR o.expires_at>o.created_at+interval '24 hours'
          OR o.completed_at IS NULL OR o.completed_at<o.created_at THEN
            RAISE EXCEPTION 'maintenance_operation_invalid' USING ERRCODE='23514'; END IF;
        IF EXISTS(SELECT 1 FROM {q}.ai_mining_runs WHERE session_id=s.id AND
          (state IN ('reserved','running','unknown'))) THEN
            RAISE EXCEPTION 'maintenance_mining_unresolved' USING ERRCODE='23514'; END IF;
        IF o.kind='root' THEN
          IF o.parent_operation_id IS NOT NULL OR o.submission_tag IS NULL
            OR o.submission_tag !~ '^[a-f0-9]{{64}}$' THEN
              RAISE EXCEPTION 'maintenance_root_invalid' USING ERRCODE='23514'; END IF;
          -- Never adopt an old turn or conceal a prior mining input.
          IF (SELECT xmin::text::bigint FROM {q}.conversation_turns WHERE id=t.id)<>pg_current_xact_id()::text::bigint % 4294967296
            OR EXISTS(SELECT 1 FROM {q}.ai_mining_runs WHERE input_turn_id=t.id) THEN
              RAISE EXCEPTION 'maintenance_input_reused' USING ERRCODE='23514'; END IF;
        ELSIF o.kind='resolution' THEN
          SELECT * INTO p FROM {q}.conversation_operations WHERE id=o.parent_operation_id;
          IF p.id IS NULL OR p.kind<>'root' OR p.state<>'needs_clarification'
            OR p.session_id<>s.id OR p.input_turn_id<>t.id OR o.submission_tag IS NOT NULL
            OR o.state<>'applied' OR o.action IS DISTINCT FROM p.proposed_action
            OR o.proposal_spans IS DISTINCT FROM p.proposal_spans
            OR o.progress_stage IS DISTINCT FROM p.progress_stage THEN
              RAISE EXCEPTION 'maintenance_resolution_invalid' USING ERRCODE='23514'; END IF;
        ELSE RAISE EXCEPTION 'maintenance_kind_invalid' USING ERRCODE='23514'; END IF;
        IF jsonb_typeof(o.proposal_spans) IS DISTINCT FROM 'array'
          OR jsonb_array_length(o.proposal_spans) NOT BETWEEN 1 AND 6 THEN
            RAISE EXCEPTION 'maintenance_spans_invalid' USING ERRCODE='23514'; END IF;
        ns:=0; ni:=0;
        FOR span IN SELECT value FROM jsonb_array_elements(o.proposal_spans) LOOP
          IF jsonb_typeof(span) IS DISTINCT FROM 'object' OR NOT span ?& array['role','start','end']
            OR (SELECT count(*) FROM jsonb_object_keys(span))<>3
            OR jsonb_typeof(span->'start') IS DISTINCT FROM 'number'
            OR jsonb_typeof(span->'end') IS DISTINCT FROM 'number'
            OR (span->>'start') !~ '^[0-9]+$' OR (span->>'end') !~ '^[0-9]+$'
            OR (span->>'start')::numeric>2147483647 OR (span->>'end')::numeric>length(t.content)
            OR (span->>'start')::numeric >= (span->>'end')::numeric THEN
              RAISE EXCEPTION 'maintenance_spans_invalid' USING ERRCODE='23514'; END IF;
          IF span->>'role'='statement' THEN ns:=ns+1;
          ELSIF span->>'role'='intent' THEN ni:=ni+1;
          ELSE RAISE EXCEPTION 'maintenance_spans_invalid' USING ERRCODE='23514'; END IF;
        END LOOP;
        a:=o.action;
        IF o.state='needs_clarification' THEN
          IF o.kind<>'root' OR a IS DISTINCT FROM 'disambiguate' OR o.target_fact_id IS NOT NULL
            OR o.target_version IS NOT NULL OR o.effect_count<>0 OR o.outcome_code IS DISTINCT FROM 'target_ambiguous'
            OR o.proposed_action IS NULL OR o.proposed_action NOT IN ('correct','withdraw','progress') THEN
              RAISE EXCEPTION 'maintenance_ambiguity_invalid' USING ERRCODE='23514'; END IF;
          a:=o.proposed_action;
        ELSIF o.state='applied' THEN
          IF o.proposed_action IS NOT NULL THEN RAISE EXCEPTION 'maintenance_action_invalid' USING ERRCODE='23514'; END IF;
        ELSE RAISE EXCEPTION 'maintenance_state_invalid' USING ERRCODE='23514'; END IF;
        -- GQ08 type/progress validators belong to B2-c, not this migration.
        IF a='progress' THEN RAISE EXCEPTION 'maintenance_progress_unavailable' USING ERRCODE='23514'; END IF;
        IF o.progress_stage IS NOT NULL THEN RAISE EXCEPTION 'maintenance_progress_unavailable' USING ERRCODE='23514'; END IF;
        IF a='append' THEN
          IF ns NOT BETWEEN 1 AND 5 OR ni<>0 OR o.target_fact_id IS NOT NULL OR o.target_version IS NOT NULL
            OR o.outcome_code IS NULL OR o.outcome_code NOT IN ('created','no_new_fact')
            OR (o.outcome_code='created' AND o.effect_count NOT BETWEEN 1 AND ns)
            OR (o.outcome_code='no_new_fact' AND o.effect_count<>0) THEN
              RAISE EXCEPTION 'maintenance_append_invalid' USING ERRCODE='23514'; END IF;
        ELSIF a IN ('correct','withdraw') THEN
          IF ni<>1 OR ns<>(CASE WHEN a='correct' THEN 1 ELSE 0 END) THEN
            RAISE EXCEPTION 'maintenance_action_spans_invalid' USING ERRCODE='23514'; END IF;
          IF o.state='applied' AND (o.target_fact_id IS NULL OR o.target_version IS NULL OR o.effect_count<>1
            OR o.outcome_code IS DISTINCT FROM (CASE WHEN a='correct' THEN 'corrected' ELSE 'withdrawn' END)) THEN
              RAISE EXCEPTION 'maintenance_target_invalid' USING ERRCODE='23514'; END IF;
        ELSE RAISE EXCEPTION 'maintenance_action_invalid' USING ERRCODE='23514'; END IF;
        SELECT count(DISTINCT change_id),count(DISTINCT fact_id) INTO n,total
          FROM {q}.fact_change_sources WHERE operation_id=o.id;
        IF n<>o.effect_count OR total<>n THEN RAISE EXCEPTION 'maintenance_effect_count' USING ERRCODE='23514'; END IF;
        -- One local command/session/transaction: unlinked effects or a second
        -- saved answer must not disappear from a supposedly complete receipt.
        IF (SELECT count(*) FROM {q}.fact_changes WHERE session_id=s.id
              AND xmin::text::bigint=pg_current_xact_id()::text::bigint % 4294967296)<>n
          OR (SELECT count(*) FROM {q}.conversation_turns WHERE session_id=s.id AND role='user'
              AND xmin::text::bigint=pg_current_xact_id()::text::bigint % 4294967296)
            <> (CASE WHEN o.kind='root' THEN 1 ELSE 0 END) THEN
              RAISE EXCEPTION 'maintenance_unreceipted_effect' USING ERRCODE='23514'; END IF;
        IF n>0 AND (SELECT array_agg(DISTINCT effect_slot ORDER BY effect_slot) FROM {q}.fact_change_sources WHERE operation_id=o.id)
          IS DISTINCT FROM ARRAY(SELECT generate_series(1,n)::smallint) THEN
            RAISE EXCEPTION 'maintenance_effect_slots' USING ERRCODE='23514'; END IF;
        FOR r IN SELECT * FROM {q}.fact_change_sources WHERE operation_id=o.id LOOP
          SELECT * INTO c FROM {q}.fact_changes WHERE id=r.change_id;
          SELECT * INTO f FROM {q}.experience_facts WHERE id=r.fact_id;
          IF c.id IS NULL OR f.id IS NULL OR c.fact_id<>f.id OR c.session_id<>s.id OR f.session_id<>s.id
            OR r.session_id<>s.id OR r.turn_id<>t.id OR r.end_cp>length(t.content)
            OR r.quote IS DISTINCT FROM substring(t.content FROM r.start_cp+1 FOR r.end_cp-r.start_cp)
            OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(o.proposal_spans) v
              WHERE v->>'role'=r.source_role AND (v->>'start')::integer=r.start_cp AND (v->>'end')::integer=r.end_cp)
            OR (SELECT xmin::text::bigint FROM {q}.fact_changes WHERE id=c.id)<>pg_current_xact_id()::text::bigint % 4294967296
            OR jsonb_typeof(c.after->'version') IS DISTINCT FROM 'number'
            OR c.after->>'version' IS DISTINCT FROM r.after_version::text
            OR f.version<>r.after_version OR f.statement IS DISTINCT FROM c.after->>'statement'
            OR f.status IS DISTINCT FROM c.after->>'status'
            OR jsonb_typeof(c.after->'statement') IS DISTINCT FROM 'string' THEN
              RAISE EXCEPTION 'maintenance_source_invalid' USING ERRCODE='23514'; END IF;
          IF a='append' THEN
            expected_reason:='addition';
            IF c.action<>'created' OR c.actor<>'system' OR (c.before IS NOT NULL AND c.before<>'null'::jsonb) OR r.before_version IS NOT NULL
              OR r.after_version<>1 OR f.status<>'pending' OR r.source_role<>'statement' THEN
                RAISE EXCEPTION 'maintenance_created_invalid' USING ERRCODE='23514'; END IF;
            IF NOT EXISTS(SELECT 1 FROM {q}.fact_sources fs, jsonb_array_elements(fs.citations) x
              WHERE fs.fact_id=f.id AND fs.turn_id=t.id AND fs.session_id=s.id AND x->>'turn_id'=t.id::text
              AND x->>'quote'=r.quote AND x->>'start'=r.start_cp::text AND x->>'end'=r.end_cp::text) THEN
                RAISE EXCEPTION 'maintenance_original_source_invalid' USING ERRCODE='23514'; END IF;
          ELSE
            expected_reason:=CASE WHEN a='correct' THEN 'explicit_correction' ELSE 'explicit_withdrawal' END;
            IF f.id<>o.target_fact_id OR r.before_version IS DISTINCT FROM o.target_version
              OR r.after_version<>r.before_version+1 OR c.before->>'version' IS DISTINCT FROM r.before_version::text
              OR jsonb_typeof(c.before->'version') IS DISTINCT FROM 'number'
              OR c.before->>'status' IS NULL OR c.before->>'status' NOT IN ('pending','user_confirmed','evidence_supported')
              OR c.actor<>'user' OR f.evidence_id IS NOT NULL
              OR c.action IS DISTINCT FROM (CASE WHEN a='correct' THEN 'edited' ELSE 'status_changed' END)
              OR f.status IS DISTINCT FROM (CASE WHEN a='correct' THEN 'pending' ELSE 'rejected' END) THEN
                RAISE EXCEPTION 'maintenance_change_invalid' USING ERRCODE='23514'; END IF;
          END IF;
          IF r.reason<>expected_reason OR (r.source_role='statement' AND r.quote IS DISTINCT FROM c.after->>'statement') THEN
            RAISE EXCEPTION 'maintenance_statement_mismatch' USING ERRCODE='23514'; END IF;
        END LOOP;
        FOR r IN SELECT effect_slot,count(*) AS sources,count(DISTINCT change_id) AS changes,
          count(*) FILTER(WHERE source_role='statement') AS statements,count(*) FILTER(WHERE source_role='intent') AS intents
          FROM {q}.fact_change_sources WHERE operation_id=o.id GROUP BY effect_slot LOOP
          IF r.changes<>1 OR r.statements<>(CASE WHEN a='withdraw' THEN 0 ELSE 1 END)
            OR r.intents<>(CASE WHEN a='append' THEN 0 ELSE 1 END) THEN
              RAISE EXCEPTION 'maintenance_effect_sources' USING ERRCODE='23514'; END IF;
        END LOOP;
      END $$''')
    op.execute(f'''CREATE FUNCTION {q}.maintenance_guard() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      BEGIN
        IF TG_OP='TRUNCATE' THEN RAISE EXCEPTION 'maintenance_immutable' USING ERRCODE='23514'; END IF;
        IF TG_RELID='{q}.conversation_operations'::regclass THEN
          IF TG_OP='INSERT' THEN
            IF NEW.state='deleted' THEN RAISE EXCEPTION 'maintenance_tombstone_insert' USING ERRCODE='23514'; END IF;
            NEW.created_at:=clock_timestamp(); NEW.completed_at:=NEW.created_at; RETURN NEW;
          ELSIF TG_OP='UPDATE' THEN
            IF OLD.state='deleted' OR NEW.state<>'deleted'
              OR (to_jsonb(NEW)-ARRAY['session_id','input_turn_id','kind','action','parent_operation_id','submission_tag','request_tag','proposed_action','proposal_spans','progress_stage','base_revision','result_revision','target_fact_id','target_version','effect_count','outcome_code','decision_contract','completed_at','state'])
                IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['session_id','input_turn_id','kind','action','parent_operation_id','submission_tag','request_tag','proposed_action','proposal_spans','progress_stage','base_revision','result_revision','target_fact_id','target_version','effect_count','outcome_code','decision_contract','completed_at','state']) THEN
                  RAISE EXCEPTION 'maintenance_immutable' USING ERRCODE='23514'; END IF;
            RETURN NEW;
          ELSIF OLD.state='deleted' AND OLD.expires_at<=clock_timestamp() THEN RETURN OLD;
          ELSE RAISE EXCEPTION 'maintenance_immutable' USING ERRCODE='23514'; END IF;
        ELSIF TG_RELID='{q}.fact_change_sources'::regclass THEN
          IF TG_OP='INSERT' THEN NEW.created_at:=clock_timestamp(); RETURN NEW; END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RAISE EXCEPTION 'maintenance_immutable' USING ERRCODE='23514';
        ELSIF TG_RELID='{q}.fact_changes'::regclass THEN
          IF TG_OP='UPDATE' AND (SELECT xmin::text::bigint FROM {q}.fact_changes WHERE id=OLD.id)
            <>pg_current_xact_id()::text::bigint % 4294967296 THEN
              RAISE EXCEPTION 'maintenance_history_immutable' USING ERRCODE='23514'; END IF;
          IF EXISTS(SELECT 1 FROM {q}.fact_change_sources WHERE change_id=OLD.id)
            AND EXISTS(SELECT 1 FROM {q}.experience_sessions WHERE id=OLD.session_id) THEN
              RAISE EXCEPTION 'maintenance_history_immutable' USING ERRCODE='23514'; END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
        ELSIF TG_RELID='{q}.conversation_turns'::regclass THEN
          -- xmin alone proves a write, not an INSERT. Block touching old turns
          -- (even only timestamps) to make them look newly created to a receipt.
          IF (SELECT xmin::text::bigint FROM {q}.conversation_turns WHERE id=OLD.id)
            <>pg_current_xact_id()::text::bigint % 4294967296 THEN
              RAISE EXCEPTION 'maintenance_input_immutable' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        ELSIF TG_RELID='{q}.experience_facts'::regclass THEN
          IF EXISTS(SELECT 1 FROM {q}.fact_change_sources WHERE fact_id=OLD.id)
            AND (NEW.version<OLD.version OR NEW.version>OLD.version+1) THEN
              RAISE EXCEPTION 'maintenance_version_invalid' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END IF;
        RAISE EXCEPTION 'maintenance_trigger_scope' USING ERRCODE='23514';
      END $$''')
    op.execute(f'''CREATE FUNCTION {q}.maintenance_deferred() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      BEGIN
        IF TG_TABLE_NAME='conversation_operations' THEN
          IF TG_OP='UPDATE' AND NEW.state='deleted' THEN
            IF EXISTS(SELECT 1 FROM {q}.experience_sessions WHERE id=OLD.session_id) THEN
              RAISE EXCEPTION 'maintenance_erasure_requires_session_delete' USING ERRCODE='23514'; END IF;
          ELSIF TG_OP='INSERT' THEN PERFORM {q}.maintenance_validate(NEW.id); END IF;
        ELSIF TG_TABLE_NAME='fact_change_sources' THEN
          IF TG_OP='DELETE' THEN
            IF EXISTS(SELECT 1 FROM {q}.experience_sessions WHERE id=OLD.session_id) THEN
              RAISE EXCEPTION 'maintenance_source_immutable' USING ERRCODE='23514'; END IF;
          ELSE PERFORM {q}.maintenance_validate(NEW.operation_id); END IF;
        END IF;
        RETURN NULL;
      END $$''')
    op.execute(f'''CREATE FUNCTION {q}.maintenance_erase_session() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      BEGIN
        IF TG_RELID<>'{q}.experience_sessions'::regclass OR TG_OP<>'DELETE' THEN
          RAISE EXCEPTION 'maintenance_trigger_scope' USING ERRCODE='23514'; END IF;
        UPDATE {q}.conversation_operations SET state='deleted',session_id=NULL,input_turn_id=NULL,
          kind=NULL,action=NULL,parent_operation_id=NULL,submission_tag=NULL,request_tag=NULL,
          proposed_action=NULL,proposal_spans=NULL,progress_stage=NULL,base_revision=NULL,result_revision=NULL,
          target_fact_id=NULL,target_version=NULL,effect_count=NULL,outcome_code=NULL,decision_contract=NULL,completed_at=NULL
          WHERE session_id=OLD.id;
        RETURN OLD;
      END $$''')
    op.execute(f'''CREATE FUNCTION {q}.maintenance_current_fact() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      DECLARE f {q}.experience_facts%ROWTYPE;
      BEGIN
        SELECT * INTO f FROM {q}.experience_facts WHERE id=NEW.id;
        IF EXISTS(SELECT 1 FROM {q}.fact_change_sources WHERE fact_id=f.id) AND NOT EXISTS(
          SELECT 1 FROM {q}.fact_changes c WHERE c.fact_id=f.id AND c.session_id=f.session_id
          AND jsonb_typeof(c.after->'version')='number' AND c.after->>'version'=f.version::text
          AND jsonb_typeof(c.after->'statement')='string'
          AND c.after->>'statement'=f.statement AND c.after->>'status'=f.status) THEN
            RAISE EXCEPTION 'maintenance_current_mismatch' USING ERRCODE='23514'; END IF;
        -- History at older versions is never compared with a later statement.
        IF EXISTS(SELECT 1 FROM {q}.fact_change_sources src
          JOIN {q}.fact_changes c ON c.id=src.change_id
          WHERE src.fact_id=f.id AND src.after_version=f.version AND
          (f.statement IS DISTINCT FROM c.after->>'statement'
           OR f.status IS DISTINCT FROM c.after->>'status')) THEN
            RAISE EXCEPTION 'maintenance_current_mismatch' USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$''')
    for table in ('conversation_operations','fact_change_sources'):
        op.execute(f'CREATE TRIGGER maintenance_guard BEFORE INSERT OR UPDATE OR DELETE ON {q}.{table} FOR EACH ROW EXECUTE FUNCTION {q}.maintenance_guard()')
        op.execute(f'CREATE TRIGGER maintenance_no_truncate BEFORE TRUNCATE ON {q}.{table} FOR EACH STATEMENT EXECUTE FUNCTION {q}.maintenance_guard()')
        op.execute(f'CREATE CONSTRAINT TRIGGER maintenance_consistent AFTER INSERT OR UPDATE OR DELETE ON {q}.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {q}.maintenance_deferred()')
        op.execute(f'REVOKE ALL ON {q}.{table} FROM PUBLIC')
    op.execute(f'CREATE TRIGGER maintenance_history_guard BEFORE UPDATE OR DELETE ON {q}.fact_changes FOR EACH ROW EXECUTE FUNCTION {q}.maintenance_guard()')
    op.execute(f'CREATE TRIGGER maintenance_erase BEFORE DELETE ON {q}.experience_sessions FOR EACH ROW EXECUTE FUNCTION {q}.maintenance_erase_session()')
    op.execute(f'CREATE CONSTRAINT TRIGGER maintenance_current AFTER UPDATE ON {q}.experience_facts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {q}.maintenance_current_fact()')
    op.execute(f'CREATE TRIGGER maintenance_version BEFORE UPDATE ON {q}.experience_facts FOR EACH ROW EXECUTE FUNCTION {q}.maintenance_guard()')
    op.execute(f'CREATE TRIGGER maintenance_input_guard BEFORE UPDATE ON {q}.conversation_turns FOR EACH ROW EXECUTE FUNCTION {q}.maintenance_guard()')
    # Default ACLs may grant a named application role access on CREATE. Revoke
    # those too; new tables/functions have no production runtime writer yet.
    conn=op.get_bind()
    quote=conn.dialect.identifier_preparer.quote_identifier
    functions=('maintenance_validate(uuid)','maintenance_guard()',
        'maintenance_deferred()','maintenance_erase_session()','maintenance_current_fact()')
    for kind,targets,catalog,acl,owner,default in (
        ('TABLE',('conversation_operations','fact_change_sources'),'pg_class','relacl','relowner','r'),
        ('FUNCTION',functions,'pg_proc','proacl','proowner','f')):
        for target in targets:
            cast='regclass' if kind=='TABLE' else 'regprocedure'
            grantees=conn.execute(sa.text(f'''SELECT DISTINCT a.grantee FROM {catalog} c CROSS JOIN LATERAL
              aclexplode(coalesce(c.{acl},acldefault('{default}',c.{owner}))) a
              WHERE c.oid=CAST(:t AS {cast}) AND a.grantee<>c.{owner}'''),{'t':f'{q}.{target}'}).scalars().all()
            op.execute(f'REVOKE ALL ON {kind} {q}.{target} FROM PUBLIC')
            for oid in grantees:
                if oid:
                    name=conn.scalar(sa.text('SELECT rolname FROM pg_roles WHERE oid=:oid'),{'oid':oid})
                    op.execute(f'REVOKE ALL ON {kind} {q}.{target} FROM {quote(name)}')


def downgrade():
    conn=op.get_bind()
    q=conn.dialect.identifier_preparer.quote_identifier(conn.scalar(sa.text('SELECT current_schema()')))
    op.execute(f'LOCK TABLE {q}.experience_sessions,{q}.experience_facts,{q}.fact_changes,{q}.conversation_operations,{q}.fact_change_sources IN ACCESS EXCLUSIVE MODE NOWAIT')
    if any(conn.scalar(sa.text(f'SELECT EXISTS(SELECT 1 FROM {q}.{t})')) for t in ('conversation_operations','fact_change_sources')):
        raise RuntimeError('maintenance_nonempty_downgrade_refused')
    op.execute(f'DROP TRIGGER maintenance_erase ON {q}.experience_sessions')
    op.execute(f'DROP TRIGGER maintenance_history_guard ON {q}.fact_changes')
    op.execute(f'DROP TRIGGER maintenance_current ON {q}.experience_facts')
    op.execute(f'DROP TRIGGER maintenance_version ON {q}.experience_facts')
    op.execute(f'DROP TRIGGER maintenance_input_guard ON {q}.conversation_turns')
    op.drop_table('fact_change_sources');op.drop_table('conversation_operations')
    for fn,args in (('maintenance_deferred',''),('maintenance_guard',''),('maintenance_erase_session',''),('maintenance_current_fact',''),('maintenance_validate','uuid')):
        op.execute(f'DROP FUNCTION {q}.{fn}({args})')
    op.drop_constraint('uq_change_fact_session','fact_changes',type_='unique')
