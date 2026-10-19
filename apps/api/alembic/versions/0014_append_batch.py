"""B2-c1 append v2. Forward only; v1 validator snapshot remains unchanged.

CREATE OR REPLACE preserves function identity, owner and ACL; no new callable
helper or runtime grant is introduced. No history/backfill or paid-table writes.
"""
from alembic import op
import sqlalchemy as sa

revision = '0014_append_batch'
down_revision = '0013_fact_maintenance'
branch_labels = depends_on = None

# Frozen 0013 validator SQL, used verbatim for v1 and safe downgrade.
V1_VALIDATE = r'''
CREATE OR REPLACE FUNCTION {q}.maintenance_validate(oid uuid) RETURNS void
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
            IF (SELECT count(*) FROM {q}.fact_sources WHERE fact_id=f.id)<>1 OR NOT EXISTS(
              SELECT 1 FROM {q}.fact_sources fs WHERE fs.fact_id=f.id AND fs.turn_id=t.id AND fs.session_id=s.id
              AND fs.citations=jsonb_build_array(jsonb_build_object('turn_id',t.id::text,
                'quote',r.quote,'start',r.start_cp,'end',r.end_cp))) THEN
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
          PERFORM {q}.maintenance_original_fact(f.id);
        END LOOP;
        FOR r IN SELECT effect_slot,count(*) AS sources,count(DISTINCT change_id) AS changes,
          count(*) FILTER(WHERE source_role='statement') AS statements,count(*) FILTER(WHERE source_role='intent') AS intents
          FROM {q}.fact_change_sources WHERE operation_id=o.id GROUP BY effect_slot LOOP
          IF r.changes<>1 OR r.statements<>(CASE WHEN a='withdraw' THEN 0 ELSE 1 END)
            OR r.intents<>(CASE WHEN a='append' THEN 0 ELSE 1 END) THEN
              RAISE EXCEPTION 'maintenance_effect_sources' USING ERRCODE='23514'; END IF;
        END LOOP;
      END $$
'''

SHAPE = "((state='deleted' AND num_nonnulls(session_id,input_turn_id,kind,action,parent_operation_id,submission_tag,request_tag,proposed_action,proposal_spans,progress_stage,base_revision,result_revision,target_fact_id,target_version,effect_count,outcome_code,decision_contract,completed_at)=0) OR (state<>'deleted' AND session_id IS NOT NULL AND input_turn_id IS NOT NULL AND kind IS NOT NULL AND action IS NOT NULL AND proposal_spans IS NOT NULL AND base_revision>0 AND result_revision>=base_revision AND effect_count BETWEEN 0 AND 5 AND request_tag ~ '^[a-f0-9]{64}$' AND decision_contract='explicit-target-v1' AND completed_at>=created_at)) IS TRUE"

V2_CHECK = r'''
        IF o.contract_version=2 THEN
          -- append_v2_bijection: ordered proposal -> exactly one new effect.
          IF o.kind IS DISTINCT FROM 'root' OR o.action IS DISTINCT FROM 'append'
            OR length(t.content) NOT BETWEEN 1 AND 10000
            OR o.state IS DISTINCT FROM 'applied' OR o.outcome_code IS DISTINCT FROM 'created'
            OR o.parent_operation_id IS NOT NULL OR o.proposed_action IS NOT NULL
            OR o.target_fact_id IS NOT NULL OR o.target_version IS NOT NULL OR o.progress_stage IS NOT NULL
            OR ns NOT BETWEEN 1 AND 5 OR ni<>0 OR o.effect_count IS DISTINCT FROM ns
            OR (SELECT count(*) FROM {q}.conversation_turns WHERE session_id=s.id
              AND xmin::text::bigint=pg_current_xact_id()::text::bigint % 4294967296)<>1
            OR (SELECT count(*) FROM {q}.conversation_operations WHERE session_id=s.id
              AND xmin::text::bigint=pg_current_xact_id()::text::bigint % 4294967296)<>1
            OR (SELECT count(*) FROM {q}.experience_facts WHERE session_id=s.id
              AND xmin::text::bigint=pg_current_xact_id()::text::bigint % 4294967296)<>ns
            OR (SELECT count(*) FROM {q}.fact_sources WHERE session_id=s.id
              AND xmin::text::bigint=pg_current_xact_id()::text::bigint % 4294967296)<>ns
            OR EXISTS(SELECT 1 FROM {q}.experience_facts WHERE session_id=s.id AND status='rejected')
            OR EXISTS(SELECT 1 FROM {q}.fact_changes WHERE session_id=s.id
              AND (before->>'status'='rejected' OR after->>'status'='rejected')) THEN
            RAISE EXCEPTION 'append_v2_bijection' USING ERRCODE='23514'; END IF;
          total:=0; n:=0;
          FOR span IN SELECT value FROM jsonb_array_elements(o.proposal_spans) LOOP
            n:=n+1;
            IF span->>'role' IS DISTINCT FROM 'statement' OR (span->>'start')::integer<total
              OR translate(substring(t.content FROM total+1 FOR (span->>'start')::integer-total),
                U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000', '')<>''
              OR NOT EXISTS(SELECT 1 FROM {q}.fact_change_sources src
                JOIN {q}.experience_facts ef ON ef.id=src.fact_id
                JOIN {q}.fact_changes fc ON fc.id=src.change_id
                WHERE src.operation_id=o.id AND src.effect_slot=n AND src.source_role='statement'
                  AND src.start_cp=(span->>'start')::integer AND src.end_cp=(span->>'end')::integer
                  AND ef.project_id=(SELECT id FROM {q}.experience_projects WHERE session_id=s.id)
                  AND ef.origin='manual' AND ef.ai_run_id IS NULL AND ef.evidence_id IS NULL
                  AND fc.after->'evidence_id'='null'::jsonb AND fc.after->'ai_run_id'='null'::jsonb
                  AND fc.after->>'origin'='manual'
                  AND ef.xmin::text::bigint=pg_current_xact_id()::text::bigint % 4294967296)
              OR EXISTS(SELECT 1 FROM {q}.fact_change_sources prior
                JOIN {q}.fact_change_sources curr ON curr.operation_id=o.id AND curr.effect_slot=n
                WHERE prior.operation_id=o.id AND prior.effect_slot<n AND prior.quote=curr.quote) THEN
              RAISE EXCEPTION 'append_v2_bijection' USING ERRCODE='23514'; END IF;
            total:=(span->>'end')::integer;
          END LOOP;
          IF translate(substring(t.content FROM total+1),
            U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000', '')<>'' THEN
            RAISE EXCEPTION 'append_v2_bijection' USING ERRCODE='23514'; END IF;
        END IF;
'''


def namespace():
    conn = op.get_bind()
    q = conn.dialect.identifier_preparer.quote_identifier(conn.scalar(sa.text('SELECT current_schema()')))
    op.execute(f'LOCK TABLE {q}.experience_sessions,{q}.experience_facts,{q}.fact_changes,{q}.fact_sources,{q}.conversation_operations,{q}.fact_change_sources IN ACCESS EXCLUSIVE MODE NOWAIT')
    return q


def upgrade():
    q = namespace()
    op.execute(f'ALTER TABLE {q}.conversation_operations DROP CONSTRAINT ck_co_identity')
    op.execute(f"ALTER TABLE {q}.conversation_operations ADD CONSTRAINT ck_co_identity CHECK (contract_version IN (1,2) AND key_digest ~ '^[a-f0-9]{{64}}$' AND state IN ('applied','needs_clarification','deleted'))")
    op.execute(f'ALTER TABLE {q}.conversation_operations DROP CONSTRAINT ck_co_shape')
    shape = SHAPE.replace("decision_contract='explicit-target-v1'", "((contract_version=1 AND decision_contract='explicit-target-v1') OR (contract_version=2 AND decision_contract='append-batch-v1'))")
    op.execute(f'ALTER TABLE {q}.conversation_operations ADD CONSTRAINT ck_co_shape CHECK ({shape})')
    sql = V1_VALIDATE.replace("o.decision_contract IS DISTINCT FROM 'explicit-target-v1'", "(o.contract_version NOT IN (1,2) OR o.decision_contract IS DISTINCT FROM (CASE WHEN o.contract_version=1 THEN 'explicit-target-v1' ELSE 'append-batch-v1' END))")
    sql = sql.replace('      END $$', V2_CHECK + '      END $$')
    op.execute(sql.format(q=q))


def downgrade():
    q = namespace()
    if op.get_bind().scalar(sa.text(f'SELECT EXISTS(SELECT 1 FROM {q}.conversation_operations WHERE contract_version<>1)')):
        raise RuntimeError('append_nonempty_downgrade_refused')
    op.execute(V1_VALIDATE.format(q=q))
    op.execute(f'ALTER TABLE {q}.conversation_operations DROP CONSTRAINT ck_co_identity')
    op.execute(f"ALTER TABLE {q}.conversation_operations ADD CONSTRAINT ck_co_identity CHECK (contract_version=1 AND key_digest ~ '^[a-f0-9]{{64}}$' AND state IN ('applied','needs_clarification','deleted'))")
    op.execute(f'ALTER TABLE {q}.conversation_operations DROP CONSTRAINT ck_co_shape')
    op.execute(f'ALTER TABLE {q}.conversation_operations ADD CONSTRAINT ck_co_shape CHECK ({SHAPE})')
