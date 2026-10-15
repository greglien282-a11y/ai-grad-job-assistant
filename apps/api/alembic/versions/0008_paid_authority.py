"""Independent paid authority; empty grants, zero funding, no HTTP enablement."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0008_paid_authority'
down_revision = '0007_probe_preflight'
branch_labels = depends_on = None


def upgrade():
    op.create_table('paid_funding',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ledger_id', sa.Uuid(), nullable=False, unique=True),
        sa.Column('ceiling', sa.Numeric(20,6), nullable=False),
        sa.Column('held', sa.Numeric(20,6), nullable=False),
        sa.Column('spent', sa.Numeric(20,6), nullable=False),
        sa.Column('frozen', sa.Boolean(), nullable=False),
        sa.Column('approval_digest', sa.String(64)),
        sa.CheckConstraint('id = 1', name='ck_paid_single_pool'),
        sa.CheckConstraint('ceiling >= 0 AND held >= 0 AND spent >= 0', name='ck_paid_pool_money'))
    op.create_table('paid_scopes',
        sa.Column('kind', sa.String(16), primary_key=True),
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('ceiling', sa.Numeric(20,6), nullable=False),
        sa.Column('approval_digest', sa.String(64), nullable=False),
        sa.CheckConstraint("kind IN ('provider','model')", name='ck_paid_scope_kind'),
        sa.CheckConstraint('ceiling >= 0', name='ck_paid_scope_money'))
    op.create_table('paid_grants',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('pool_id', sa.Integer(), sa.ForeignKey('paid_funding.id'), nullable=False),
        sa.Column('approver', sa.String(64), nullable=False),
        sa.Column('approval_digest', sa.String(64), nullable=False, unique=True),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('ceiling', sa.Numeric(20,6), nullable=False),
        sa.Column('call_limit', sa.Numeric(20,6), nullable=False),
        sa.Column('calls_limit', sa.Integer(), nullable=False),
        sa.Column('policy_hash', sa.String(64), nullable=False),
        sa.Column('policy', JSONB(), nullable=False),
        sa.CheckConstraint('pool_id = 1', name='ck_paid_grant_pool'),
        sa.CheckConstraint('starts_at < expires_at AND ceiling >= 0 AND call_limit > 0 AND calls_limit > 0', name='ck_paid_grant_limits'))
    op.create_table('paid_calls',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('grant_id', sa.Uuid(), sa.ForeignKey('paid_grants.id'), nullable=False),
        sa.Column('operation_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('policy_hash', sa.String(64), nullable=False),
        sa.Column('batch_tag', sa.String(64), nullable=False),
        sa.Column('provider', sa.String(32), nullable=False),
        sa.Column('model', sa.String(64), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('reserved', sa.Numeric(20,6), nullable=False),
        sa.Column('actual', sa.Numeric(20,6)),
        sa.Column('actual_usd', sa.Numeric(24,12)),
        sa.Column('invoice_hash', sa.String(64), unique=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('usage', JSONB()),
        sa.CheckConstraint("state IN ('reserved','sent','response_received','unknown','reconciled')", name='ck_paid_call_state'),
        sa.CheckConstraint('reserved > 0 AND (actual IS NULL OR actual >= 0) AND (actual_usd IS NULL OR actual_usd >= 0)', name='ck_paid_call_money'))
    op.create_table('paid_audit',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('evidence_digest', sa.String(64), nullable=False),
        sa.Column('detail', JSONB(), nullable=False))
    # No positive ceiling, scopes, approvals, price or token certificate seeded.
    op.execute(sa.text('INSERT INTO paid_funding VALUES (1, :ledger, 0, 0, 0, false, NULL)').bindparams(ledger=uuid4()))
    schema = op.get_bind().scalar(sa.text('SELECT current_schema()'))
    q = op.get_bind().dialect.identifier_preparer.quote_identifier(schema)
    op.execute(f'''CREATE FUNCTION {q}.paid_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF TG_TABLE_NAME='paid_grants' AND TG_OP='UPDATE' AND
         (to_jsonb(NEW)-'revoked')=(to_jsonb(OLD)-'revoked') AND to_jsonb(OLD)->>'revoked'='false' AND to_jsonb(NEW)->>'revoked'='true' THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'paid_immutable_record';
    END $$''')
    for table in ('paid_grants', 'paid_audit'):
        op.execute(f'CREATE TRIGGER paid_immutable BEFORE UPDATE OR DELETE ON {q}.{table} FOR EACH ROW EXECUTE FUNCTION {q}.paid_immutable()')
    # Fixed search_path, fully qualified relations, no dynamic SQL in the
    # privileged function. All mutations lock the same singleton first.
    op.execute(f'''CREATE FUNCTION {q}.paid_runtime(ledger text, action text, p jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE pool {q}.paid_funding%ROWTYPE; g {q}.paid_grants%ROWTYPE; c {q}.paid_calls%ROWTYPE;
      stamp timestamptz; cert jsonb; pol jsonb; amount numeric; used numeric; lim numeric; n integer; k text; v text;
    BEGIN
      SELECT * INTO pool FROM {q}.paid_funding WHERE id=1 FOR UPDATE;
      IF NOT FOUND OR pool.ledger_id::text<>ledger THEN RAISE EXCEPTION 'paid_ledger_identity_mismatch'; END IF;
      stamp:=clock_timestamp();
      IF action='recover' THEN
        WITH recovered AS (UPDATE {q}.paid_calls SET state='unknown' WHERE state='sent' AND lease_until<=stamp RETURNING id,request_hash)
          INSERT INTO {q}.paid_audit(id,created_at,action,evidence_digest,detail)
            SELECT gen_random_uuid(),stamp,'recover_unknown',request_hash,jsonb_build_object('call_id',id) FROM recovered;
        GET DIAGNOSTICS n=ROW_COUNT;
        -- Even expired reserved calls keep their reserve until explicit owner
        -- review; no runtime refund/reconciliation capability exists.
        RETURN jsonb_build_object('recovered',n);
      END IF;
      IF action='reserve' THEN
        IF (p->>'operation') IS NULL OR (p->>'operation') !~ '^[a-f0-9]{{64}}$' OR
           (p->>'request') IS NULL OR (p->>'request') !~ '^[a-f0-9]{{64}}$' OR
           (p->>'batch') IS NULL OR (p->>'batch') !~ '^[-A-Za-z0-9_.:]{{1,64}}$' THEN RAISE EXCEPTION 'paid_payload_invalid'; END IF;
        SELECT * INTO c FROM {q}.paid_calls WHERE operation_hash=p->>'operation';
        IF FOUND THEN
          IF c.grant_id::text IS DISTINCT FROM p->>'grant' OR c.request_hash IS DISTINCT FROM p->>'request' OR c.policy_hash IS DISTINCT FROM p->>'policy' OR c.batch_tag IS DISTINCT FROM p->>'batch'
            THEN RAISE EXCEPTION 'paid_idempotency_conflict'; END IF;
          RETURN jsonb_build_object('id',c.id,'created',false);
        END IF;
        SELECT * INTO g FROM {q}.paid_grants WHERE id=(p->>'grant')::uuid;
      ELSE
        SELECT * INTO c FROM {q}.paid_calls WHERE id=(p->>'id')::uuid;
        IF NOT FOUND THEN RAISE EXCEPTION 'paid_call_missing'; END IF;
        IF action='unknown' THEN
          IF c.state='unknown' THEN RETURN jsonb_build_object('changed',false); END IF;
          IF c.state<>'sent' THEN RAISE EXCEPTION 'paid_transition_invalid'; END IF;
          UPDATE {q}.paid_calls SET state='unknown' WHERE id=c.id;
          INSERT INTO {q}.paid_audit VALUES(gen_random_uuid(),stamp,'unknown',c.request_hash,jsonb_build_object('call_id',c.id));
          RETURN jsonb_build_object('changed',true);
        ELSIF action='received' THEN
          IF c.state<>'sent' THEN RAISE EXCEPTION 'paid_transition_invalid'; END IF;
          -- Only normalized counts, never arbitrary response bodies.
          IF jsonb_typeof(p->'usage')<>'object' OR (p->'usage') IS NULL OR
             (p->'usage')-'input_tokens'-'output_tokens' <> '{{}}'::jsonb OR
             jsonb_typeof(p->'usage'->'input_tokens') IS DISTINCT FROM 'number' OR jsonb_typeof(p->'usage'->'output_tokens') IS DISTINCT FROM 'number' OR
             (p->'usage'->>'input_tokens') !~ '^[0-9]{{1,9}}$' OR (p->'usage'->>'output_tokens') !~ '^[0-9]{{1,9}}$'
             THEN RAISE EXCEPTION 'paid_usage_invalid'; END IF;
          SELECT * INTO g FROM {q}.paid_grants WHERE id=c.grant_id;
          SELECT x INTO cert FROM jsonb_array_elements(g.policy->'certificates') x WHERE x->>'request_sha'=c.request_hash;
          IF (p->'usage'->>'input_tokens')::numeric>(cert->>'input_bound')::numeric OR
             (p->'usage'->>'output_tokens')::numeric>(g.policy->>'output_cap')::numeric THEN
            UPDATE {q}.paid_funding SET frozen=true WHERE id=1;
          END IF;
          UPDATE {q}.paid_calls SET usage=p->'usage', state=CASE WHEN lease_until>stamp THEN 'response_received' ELSE 'unknown' END WHERE id=c.id;
          INSERT INTO {q}.paid_audit VALUES(gen_random_uuid(),stamp,'received',c.request_hash,jsonb_build_object('call_id',c.id));
          RETURN jsonb_build_object('changed',true);
        ELSIF action<>'permit' THEN RAISE EXCEPTION 'paid_action_invalid'; END IF;
        IF c.state<>'reserved' THEN RETURN jsonb_build_object('permitted',false); END IF;
        IF c.request_hash IS DISTINCT FROM p->>'request' OR c.policy_hash IS DISTINCT FROM p->>'policy' THEN RAISE EXCEPTION 'paid_configuration_changed'; END IF;
        IF c.lease_until<=stamp THEN RAISE EXCEPTION 'paid_lease_expired'; END IF;
        SELECT * INTO g FROM {q}.paid_grants WHERE id=c.grant_id;
      END IF;
      IF g.id IS NULL OR g.revoked OR NOT (g.starts_at<=stamp AND stamp<g.expires_at) THEN RAISE EXCEPTION 'paid_grant_inactive'; END IF;
      IF g.policy_hash IS DISTINCT FROM p->>'policy' THEN RAISE EXCEPTION 'paid_configuration_changed'; END IF;
      pol:=g.policy;
      IF pool.ceiling<=0 OR pool.frozen OR EXISTS(SELECT 1 FROM {q}.paid_calls WHERE state='unknown' OR (state='sent' AND lease_until<=stamp))
        THEN RAISE EXCEPTION 'paid_pool_blocked'; END IF;
      IF NOT ((pol->>'price_starts_at')::timestamptz<=stamp AND stamp<(pol->'price'->>'expires_at')::timestamptz AND
              (pol->>'fx_starts_at')::timestamptz<=stamp AND stamp<(pol->'fx'->>'expires_at')::timestamptz)
        THEN RAISE EXCEPTION 'paid_rate_expired'; END IF;
      SELECT x INTO cert FROM jsonb_array_elements(pol->'certificates') x WHERE x->>'request_sha'=p->>'request';
      IF cert IS NULL OR cert->>'kind'<>'owner_attested_full_request_bound' OR cert->>'covers_full_request_and_framing'<>'true' OR
         (cert->>'expires_at')::timestamptz<=stamp THEN RAISE EXCEPTION 'paid_token_bound_unproven'; END IF;
      IF action='permit' THEN
        IF pool.held+pool.spent>pool.ceiling THEN RAISE EXCEPTION 'paid_budget_exceeded'; END IF;
        FOREACH k IN ARRAY ARRAY['provider','model'] LOOP
          v:=pol->>k;
          SELECT ceiling INTO lim FROM {q}.paid_scopes WHERE kind=k AND key=v;
          SELECT coalesce(sum(coalesce(actual,reserved)),0) INTO used FROM {q}.paid_calls
            WHERE (k='provider' AND provider=v) OR (k='model' AND model=v);
          IF lim IS NULL OR used>lim THEN RAISE EXCEPTION 'paid_scope_exceeded'; END IF;
        END LOOP;
        UPDATE {q}.paid_calls SET state='sent',lease_until=stamp+interval '60 seconds' WHERE id=c.id;
        INSERT INTO {q}.paid_audit VALUES(gen_random_uuid(),stamp,'sent_intent',c.request_hash,jsonb_build_object('call_id',c.id));
        RETURN jsonb_build_object('permitted',true);
      END IF;
      amount:=ceil((
        (cert->>'input_bound')::numeric * greatest((pol->'price'->>'peak_miss')::numeric,(pol->'price'->>'offpeak_miss')::numeric,
          (pol->'price'->>'peak_hit')::numeric,(pol->'price'->>'offpeak_hit')::numeric) +
        (pol->>'output_cap')::numeric * greatest((pol->'price'->>'peak_output')::numeric,(pol->'price'->>'offpeak_output')::numeric)
        ) * (pol->'fx'->>'cny_per_usd')::numeric * (pol->'fx'->>'tax_margin_factor')::numeric)/1000000;
      SELECT count(*) INTO n FROM {q}.paid_calls WHERE state IN ('reserved','sent');
      IF n>=2 THEN RAISE EXCEPTION 'paid_concurrency_exceeded'; END IF;
      SELECT count(*),coalesce(sum(coalesce(actual,reserved)),0) INTO n,used FROM {q}.paid_calls WHERE grant_id=g.id;
      IF n>=g.calls_limit THEN RAISE EXCEPTION 'paid_call_limit'; END IF;
      IF amount<=0 OR amount>g.call_limit OR used+amount>g.ceiling OR pool.held+pool.spent+amount>pool.ceiling THEN RAISE EXCEPTION 'paid_budget_exceeded'; END IF;
      FOREACH k IN ARRAY ARRAY['provider','model'] LOOP
        v:=pol->>k;
        SELECT ceiling INTO lim FROM {q}.paid_scopes WHERE kind=k AND key=v;
        IF lim IS NULL THEN RAISE EXCEPTION 'paid_scope_unapproved'; END IF;
        SELECT coalesce(sum(coalesce(actual,reserved)),0) INTO used FROM {q}.paid_calls
          WHERE (k='provider' AND provider=v) OR (k='model' AND model=v);
        IF used+amount>lim THEN RAISE EXCEPTION 'paid_scope_exceeded'; END IF;
      END LOOP;
      INSERT INTO {q}.paid_calls(id,created_at,grant_id,operation_hash,request_hash,policy_hash,batch_tag,provider,model,state,reserved,lease_until)
        VALUES((p->>'id')::uuid,stamp,g.id,p->>'operation',p->>'request',g.policy_hash,p->>'batch',pol->>'provider',pol->>'model','reserved',amount,stamp+interval '60 seconds');
      UPDATE {q}.paid_funding SET held=held+amount WHERE id=1;
      INSERT INTO {q}.paid_audit VALUES(gen_random_uuid(),stamp,'reserve',p->>'request',jsonb_build_object('call_id',p->>'id'));
      RETURN jsonb_build_object('id',p->>'id','created',true);
    END $$''')
    op.execute(f'REVOKE ALL ON FUNCTION {q}.paid_runtime(text,text,jsonb) FROM PUBLIC')
    op.execute(f'REVOKE ALL ON FUNCTION {q}.paid_immutable() FROM PUBLIC')
    for table in ('paid_funding','paid_scopes','paid_grants','paid_calls','paid_audit'):
        op.execute(f'REVOKE ALL ON TABLE {q}.{table} FROM PUBLIC')


def downgrade():
    schema = op.get_bind().scalar(sa.text('SELECT current_schema()'))
    q = op.get_bind().dialect.identifier_preparer.quote_identifier(schema)
    op.execute(f'DROP FUNCTION {q}.paid_runtime(text,text,jsonb)')
    for table in ('paid_audit','paid_calls','paid_grants','paid_scopes','paid_funding'):
        op.drop_table(table)
    op.execute(f'DROP FUNCTION {q}.paid_immutable()')
