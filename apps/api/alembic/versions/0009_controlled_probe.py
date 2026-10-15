"""Risk-accepted single CNY experiment. Original hard-bound gates unchanged."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0009_controlled_probe'
down_revision = '0008_paid_authority'
branch_labels = depends_on = None


def upgrade():
    op.create_table('controlled_probe',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pool_id', sa.Integer(), sa.ForeignKey('paid_funding.id'), nullable=False),
        sa.Column('grant_id', sa.Uuid(), nullable=False, unique=True),
        sa.Column('policy_hash', sa.String(64), nullable=False),
        sa.Column('policy', JSONB(), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('reserved', sa.Numeric(20,6), nullable=False),
        sa.Column('actual_cny', sa.Numeric(24,12)),
        sa.Column('invoice_hash', sa.String(64), unique=True),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('diagnostic', JSONB()),
        sa.CheckConstraint('id = 1 AND pool_id = 1', name='ck_controlled_single'),
        sa.CheckConstraint("state IN ('approved','reserved','sent','response_received','unknown','reconciled')", name='ck_controlled_state'),
        sa.CheckConstraint('reserved > 0 AND (actual_cny IS NULL OR actual_cny >= 0)', name='ck_controlled_money'))
    schema = op.get_bind().scalar(sa.text('SELECT current_schema()'))
    q = op.get_bind().dialect.identifier_preparer.quote_identifier(schema)
    # Immutable approval, one row for the lifetime of this ledger, even after
    # reconciliation. New keys/batches cannot replenish its single send slot.
    op.execute(f'''CREATE FUNCTION {q}.controlled_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
      IF TG_TABLE_NAME='controlled_probe' THEN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'controlled_immutable'; END IF;
        IF NEW.id<>OLD.id OR NEW.pool_id<>OLD.pool_id OR NEW.grant_id<>OLD.grant_id
          OR NEW.policy_hash<>OLD.policy_hash OR NEW.policy<>OLD.policy
          OR NEW.reserved<>OLD.reserved OR (OLD.revoked AND NOT NEW.revoked)
          THEN RAISE EXCEPTION 'controlled_immutable'; END IF;
        RETURN NEW;
      ELSIF TG_TABLE_NAME='paid_calls' THEN
        IF EXISTS(SELECT 1 FROM {q}.controlled_probe) THEN
          RAISE EXCEPTION 'controlled_exclusive_pool'; END IF;
        RETURN NEW;
      ELSE
        IF OLD.frozen AND NOT NEW.frozen AND EXISTS(SELECT 1 FROM {q}.controlled_probe
          WHERE state IN ('sent','response_received','unknown')) THEN
          RAISE EXCEPTION 'controlled_unreconciled'; END IF;
        RETURN NEW;
      END IF; END $$''')
    op.execute(f'CREATE TRIGGER controlled_immutable BEFORE UPDATE OR DELETE ON {q}.controlled_probe FOR EACH ROW EXECUTE FUNCTION {q}.controlled_guard()')
    op.execute(f'CREATE TRIGGER controlled_exclusive BEFORE INSERT ON {q}.paid_calls FOR EACH ROW EXECUTE FUNCTION {q}.controlled_guard()')
    op.execute(f'CREATE TRIGGER controlled_freeze BEFORE UPDATE ON {q}.paid_funding FOR EACH ROW EXECUTE FUNCTION {q}.controlled_guard()')
    op.execute(f'''CREATE FUNCTION {q}.controlled_runtime(ledger text, policy_sha text, action text, payload jsonb)
      RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      DECLARE f {q}.paid_funding%ROWTYPE; r {q}.controlled_probe%ROWTYPE; t timestamptz;
      BEGIN
        SELECT * INTO f FROM {q}.paid_funding WHERE id=1 FOR UPDATE;
        IF f.ledger_id::text IS DISTINCT FROM ledger THEN RAISE EXCEPTION 'controlled_ledger_mismatch'; END IF;
        SELECT * INTO r FROM {q}.controlled_probe WHERE id=1 FOR UPDATE;
        IF NOT FOUND OR r.policy_hash IS DISTINCT FROM policy_sha THEN RAISE EXCEPTION 'controlled_approval_missing'; END IF;
        t:=clock_timestamp();
        IF action IN ('reserve','permit') THEN
          IF r.revoked OR NOT ((r.policy->>'starts_at')::timestamptz<=t AND t<(r.policy->>'expires_at')::timestamptz)
            OR t>=(r.policy->>'price_expires_at')::timestamptz THEN RAISE EXCEPTION 'controlled_inactive'; END IF;
          IF payload->>'request_sha' IS DISTINCT FROM r.policy->>'request_sha' OR payload->>'operation' IS DISTINCT FROM r.policy->>'operation_hash'
            THEN RAISE EXCEPTION 'controlled_binding_changed'; END IF;
          IF f.frozen OR f.held+f.spent>f.ceiling THEN RAISE EXCEPTION 'controlled_frozen'; END IF;
        END IF;
        IF action='reserve' THEN
          IF r.state<>'approved' THEN RETURN jsonb_build_object('created',false,'state',r.state); END IF;
          IF f.held<>0 OR f.held+f.spent+r.reserved>f.ceiling THEN RAISE EXCEPTION 'controlled_budget_exceeded'; END IF;
          UPDATE {q}.paid_funding SET held=held+r.reserved WHERE id=1;
          UPDATE {q}.controlled_probe SET state='reserved' WHERE id=1;
          INSERT INTO {q}.paid_audit(id,created_at,action,evidence_digest,detail)
            VALUES(gen_random_uuid(),t,'controlled_reserve',r.policy->>'approval_sha',jsonb_build_object('currency','CNY','policy_hash',r.policy_hash));
          RETURN jsonb_build_object('created',true,'state','reserved');
        ELSIF action='permit' THEN
          IF r.state<>'reserved' THEN RETURN jsonb_build_object('permitted',false); END IF;
          UPDATE {q}.controlled_probe SET state='sent',lease_until=t+interval '60 seconds' WHERE id=1;
          UPDATE {q}.paid_funding SET frozen=true WHERE id=1;
          INSERT INTO {q}.paid_audit(id,created_at,action,evidence_digest,detail)
            VALUES(gen_random_uuid(),t,'controlled_sent',r.policy->>'approval_sha',jsonb_build_object('policy_hash',r.policy_hash));
          RETURN jsonb_build_object('permitted',true);
        ELSIF action IN ('received','unknown') THEN
          IF r.state<>'sent' THEN RAISE EXCEPTION 'controlled_transition_invalid'; END IF;
          IF (payload-ARRAY['http_status','validated','safe_code','reported_model','usage'])<>'{{}}'::jsonb
            OR payload->>'safe_code' IS NULL
            OR payload->>'safe_code' NOT IN ('controlled_validated','controlled_cancelled','controlled_result_unknown',
              'controlled_http_error','controlled_body_too_large','controlled_timeout','controlled_network_unknown',
              'controlled_response_invalid','controlled_secret_unavailable','controlled_secret_binding_changed','controlled_secret_invalid')
            OR (payload->>'validated' IS DISTINCT FROM (CASE WHEN action='received' THEN 'true' ELSE 'false' END))
            OR (payload->>'http_status' IS NOT NULL AND payload->>'http_status' !~ '^[1-5][0-9][0-9]$')
            THEN RAISE EXCEPTION 'controlled_diagnostic_invalid'; END IF;
          IF action='received' THEN
            IF payload->>'reported_model' IS NULL
              OR payload->>'reported_model' NOT IN ('deepseek-flash','DeepSeek-V4.1-Flash')
              OR payload->>'safe_code'<>'controlled_validated' OR payload->>'http_status' IS DISTINCT FROM '200'
              OR jsonb_typeof(payload->'usage') IS DISTINCT FROM 'object'
              OR ((payload->'usage')-ARRAY['prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','total_tokens'])<>'{{}}'::jsonb
              THEN RAISE EXCEPTION 'controlled_diagnostic_invalid'; END IF;
            IF EXISTS(SELECT 1 FROM jsonb_each_text(payload->'usage') WHERE value !~ '^[0-9]{{1,13}}$')
              OR (SELECT count(*) FROM jsonb_each(payload->'usage'))<>5
              THEN RAISE EXCEPTION 'controlled_diagnostic_invalid'; END IF;
          ELSIF payload ? 'usage' OR payload ? 'reported_model' THEN
            RAISE EXCEPTION 'controlled_diagnostic_invalid';
          END IF;
          UPDATE {q}.controlled_probe SET state=CASE WHEN action='received' THEN 'response_received' ELSE 'unknown' END,
            diagnostic=payload WHERE id=1;
          INSERT INTO {q}.paid_audit(id,created_at,action,evidence_digest,detail)
            VALUES(gen_random_uuid(),t,'controlled_'||action,r.policy->>'approval_sha',jsonb_build_object('policy_hash',r.policy_hash));
          RETURN jsonb_build_object('saved',true);
        ELSE RAISE EXCEPTION 'controlled_action_invalid'; END IF;
      END $$''')
    for fn in ('controlled_guard()', 'controlled_runtime(text,text,text,jsonb)'):
        op.execute(f'REVOKE ALL ON FUNCTION {q}.{fn} FROM PUBLIC')
    op.execute(f'REVOKE ALL ON TABLE {q}.controlled_probe FROM PUBLIC')
    # No approval, amount, currency evidence, runtime role or secret is seeded.


def downgrade():
    schema = op.get_bind().scalar(sa.text('SELECT current_schema()'))
    q = op.get_bind().dialect.identifier_preparer.quote_identifier(schema)
    op.execute(f'DROP TRIGGER controlled_freeze ON {q}.paid_funding')
    op.execute(f'DROP TRIGGER controlled_exclusive ON {q}.paid_calls')
    op.execute(f'DROP FUNCTION {q}.controlled_runtime(text,text,text,jsonb)')
    op.drop_table('controlled_probe')
    op.execute(f'DROP FUNCTION {q}.controlled_guard()')
