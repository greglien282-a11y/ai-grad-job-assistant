-- TEST-SCHEMA PROPOSAL ONLY. Not Alembic; no production installation path.
-- __SCHEMA__/__ROLE__ are validated/quoted by the test installer.
CREATE TABLE __SCHEMA__.binding_identity (
  session_id uuid PRIMARY KEY REFERENCES __SCHEMA__.experience_sessions(id) ON DELETE CASCADE,
  actor_scope text NOT NULL CHECK(actor_scope ~ '^[a-f0-9]{64}$'),
  session_scope text NOT NULL UNIQUE CHECK(session_scope ~ '^[a-f0-9]{64}$')
);
-- Sub-caps only: no second funding pool, balance, refund or settlement API.
CREATE TABLE __SCHEMA__.binding_limits (
  kind text NOT NULL CHECK(kind IN ('user','session')),
  scope text NOT NULL CHECK(scope ~ '^[a-f0-9]{64}$'),
  currency text NOT NULL CHECK(currency='CNY'),
  ceiling numeric(20,6) NOT NULL CHECK(ceiling>=0),
  calls_limit integer NOT NULL CHECK(calls_limit>0),
  concurrent_limit integer NOT NULL CHECK(concurrent_limit>0),
  evidence_sha text NOT NULL CHECK(evidence_sha ~ '^[a-f0-9]{64}$'),
  PRIMARY KEY(kind,scope)
);
CREATE TABLE __SCHEMA__.binding_plans (
  run_id uuid PRIMARY KEY REFERENCES __SCHEMA__.ai_mining_runs(id) ON DELETE CASCADE,
  root_run_id uuid NOT NULL,
  session_id uuid NOT NULL REFERENCES __SCHEMA__.binding_identity(session_id) ON DELETE CASCADE,
  ledger_id uuid NOT NULL, grant_id uuid NOT NULL REFERENCES __SCHEMA__.paid_grants(id),
  operation_hash text NOT NULL CHECK(operation_hash ~ '^[a-f0-9]{64}$'),
  receipt_hash text NOT NULL CHECK(receipt_hash ~ '^[a-f0-9]{64}$'),
  request_sha text NOT NULL CHECK(request_sha ~ '^[a-f0-9]{64}$'),
  policy_sha text NOT NULL CHECK(policy_sha ~ '^[a-f0-9]{64}$'),
  context_sha text NOT NULL CHECK(context_sha ~ '^[a-f0-9]{64}$'),
  prompt_sha text NOT NULL CHECK(prompt_sha ~ '^[a-f0-9]{64}$'),
  schema_sha text NOT NULL CHECK(schema_sha ~ '^[a-f0-9]{64}$'),
  account_sha text NOT NULL CHECK(account_sha ~ '^[a-f0-9]{64}$'),
  profile_version text NOT NULL CHECK(profile_version='fixed-fixture-binding-v1'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE __SCHEMA__.mining_call_bindings (
  contract_version integer NOT NULL CHECK(contract_version=1),
  run_id uuid PRIMARY KEY, root_run_id uuid NOT NULL UNIQUE,
  operation_hash text NOT NULL UNIQUE CHECK(operation_hash ~ '^[a-f0-9]{64}$'),
  receipt_hash text NOT NULL CHECK(receipt_hash ~ '^[a-f0-9]{64}$'),
  actor_scope text NOT NULL CHECK(actor_scope ~ '^[a-f0-9]{64}$'),
  session_scope text NOT NULL CHECK(session_scope ~ '^[a-f0-9]{64}$'),
  ledger_id uuid NOT NULL,
  call_id uuid NOT NULL UNIQUE REFERENCES __SCHEMA__.paid_calls(id) ON DELETE RESTRICT,
  grant_id uuid NOT NULL REFERENCES __SCHEMA__.paid_grants(id) ON DELETE RESTRICT,
  provider text NOT NULL CHECK(provider='deepseek_official'),
  model text NOT NULL CHECK(model='deepseek-flash'),
  profile_version text NOT NULL CHECK(profile_version='fixed-fixture-binding-v1'),
  request_sha text NOT NULL CHECK(request_sha ~ '^[a-f0-9]{64}$'),
  policy_sha text NOT NULL CHECK(policy_sha ~ '^[a-f0-9]{64}$'),
  context_sha text NOT NULL CHECK(context_sha ~ '^[a-f0-9]{64}$'),
  prompt_sha text NOT NULL CHECK(prompt_sha ~ '^[a-f0-9]{64}$'),
  schema_sha text NOT NULL CHECK(schema_sha ~ '^[a-f0-9]{64}$'),
  binding_state text NOT NULL CHECK(binding_state IN ('bound','tombstoned')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  tombstoned_at timestamptz,
  CHECK ((binding_state='bound' AND tombstoned_at IS NULL) OR
         (binding_state='tombstoned' AND tombstoned_at IS NOT NULL AND tombstoned_at>=created_at))
);
CREATE FUNCTION __SCHEMA__.binding_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='mining_call_bindings' AND
     OLD.binding_state='bound' AND NEW.binding_state='tombstoned' AND NEW.tombstoned_at IS NOT NULL AND
     (to_jsonb(NEW)-'binding_state'-'tombstoned_at')=(to_jsonb(OLD)-'binding_state'-'tombstoned_at') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'binding_immutable';
END $$;
CREATE TRIGGER binding_immutable BEFORE UPDATE OR DELETE ON __SCHEMA__.mining_call_bindings
  FOR EACH ROW EXECUTE FUNCTION __SCHEMA__.binding_immutable();
CREATE TRIGGER binding_plan_immutable BEFORE UPDATE ON __SCHEMA__.binding_plans
  FOR EACH ROW EXECUTE FUNCTION __SCHEMA__.binding_immutable();
CREATE TRIGGER binding_identity_immutable BEFORE UPDATE ON __SCHEMA__.binding_identity
  FOR EACH ROW EXECUTE FUNCTION __SCHEMA__.binding_immutable();
CREATE FUNCTION __SCHEMA__.binding_erasure() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
  -- No paid table mutation/refund; audit is independent of business deletion.
  UPDATE __SCHEMA__.mining_call_bindings SET binding_state='tombstoned',tombstoned_at=clock_timestamp()
    WHERE run_id=OLD.id AND binding_state='bound';
  RETURN OLD;
END $$;
CREATE TRIGGER binding_erasure AFTER DELETE ON __SCHEMA__.ai_mining_runs
  FOR EACH ROW EXECUTE FUNCTION __SCHEMA__.binding_erasure();

CREATE FUNCTION __SCHEMA__.binding_runtime(ledger uuid, action text, rid uuid, usage jsonb DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE f __SCHEMA__.paid_funding%ROWTYPE; p __SCHEMA__.binding_plans%ROWTYPE;
  b __SCHEMA__.mining_call_bindings%ROWTYPE; c __SCHEMA__.paid_calls%ROWTYPE;
  g __SCHEMA__.paid_grants%ROWTYPE; ident __SCHEMA__.binding_identity%ROWTYPE;
  r __SCHEMA__.ai_mining_runs%ROWTYPE; lim __SCHEMA__.binding_limits%ROWTYPE;
  answer jsonb; cid uuid; stamp timestamptz; k text; v text; used numeric; n integer; active integer;
BEGIN
  IF current_database() NOT IN ('pathwise_test','pathwise_e2e') THEN RAISE EXCEPTION 'binding_isolated_schema_required'; END IF;
  -- Reject owner, SET ROLE, membership and table/function escalation, including
  -- direct paid_runtime access that would bypass the binding's sub-caps.
  IF session_user<>__ROLE_LITERAL__ OR NOT EXISTS (SELECT 1 FROM pg_roles u WHERE rolname=session_user AND NOT
     (u.rolsuper OR u.rolcreatedb OR u.rolcreaterole OR u.rolbypassrls OR u.rolreplication OR u.rolinherit
      OR EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=u.oid)
      OR has_database_privilege(u.oid,current_database(),'CREATE')
      OR EXISTS(SELECT 1 FROM pg_namespace x WHERE x.nspname NOT LIKE 'pg_temp_%' AND has_schema_privilege(u.oid,x.oid,'CREATE'))
      OR EXISTS(SELECT 1 FROM pg_class t JOIN pg_namespace x ON x.oid=t.relnamespace
        WHERE x.nspname=__SCHEMA_LITERAL__ AND t.relkind IN ('r','p') AND
        has_table_privilege(u.oid,t.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
      OR has_function_privilege(u.oid,'__SCHEMA_RAW__.paid_runtime(text,text,jsonb)','EXECUTE'))) THEN
    RAISE EXCEPTION 'binding_restricted_login_required';
  END IF;
  SELECT * INTO f FROM __SCHEMA__.paid_funding WHERE id=1 FOR UPDATE;
  IF NOT FOUND OR f.ledger_id<>ledger THEN RAISE EXCEPTION 'binding_ledger_mismatch'; END IF;
  IF NOT EXISTS(SELECT 1 FROM __SCHEMA__.controlled_probe) AND
    (f.held<>(SELECT coalesce(sum(reserved),0) FROM __SCHEMA__.paid_calls WHERE actual IS NULL)
     OR f.spent<>(SELECT coalesce(sum(actual),0) FROM __SCHEMA__.paid_calls)
     OR EXISTS(SELECT 1 FROM __SCHEMA__.paid_calls WHERE (state='reconciled')<>(actual IS NOT NULL)
        OR (actual IS NULL)<>(actual_usd IS NULL))) THEN
    RAISE EXCEPTION 'binding_ledger_inconsistent';
  END IF;
  SELECT * INTO b FROM __SCHEMA__.mining_call_bindings WHERE run_id=rid;
  IF FOUND THEN
    SELECT * INTO c FROM __SCHEMA__.paid_calls WHERE id=b.call_id;
    IF c.id IS NULL OR b.ledger_id<>ledger OR c.grant_id<>b.grant_id OR c.request_hash<>b.request_sha
       OR c.policy_hash<>b.policy_sha OR c.operation_hash<>b.operation_hash
       OR c.provider<>b.provider OR c.model<>b.model THEN RAISE EXCEPTION 'binding_ledger_inconsistent'; END IF;
    IF action='bind' THEN RETURN jsonb_build_object('call_id',b.call_id,'created',false); END IF;
    IF action IN ('received','unknown') THEN
      RETURN __SCHEMA__.paid_runtime(ledger::text,action,jsonb_build_object('id',b.call_id,'usage',usage));
    END IF;
  ELSIF action<>'bind' THEN RAISE EXCEPTION 'binding_missing';
  END IF;
  IF action NOT IN ('bind','permit') THEN RAISE EXCEPTION 'binding_action_invalid'; END IF;
  IF EXISTS(SELECT 1 FROM __SCHEMA__.paid_calls pc LEFT JOIN __SCHEMA__.mining_call_bindings x ON x.call_id=pc.id
    WHERE x.call_id IS NULL) THEN RAISE EXCEPTION 'binding_unattributed_call'; END IF;
  IF b.binding_state='tombstoned' THEN RAISE EXCEPTION 'binding_business_deleted'; END IF;
  SELECT * INTO p FROM __SCHEMA__.binding_plans WHERE run_id=rid;
  -- Hold a key-share lock until allocation/permit commits. A concurrent DELETE
  -- must either finish first (no allocation), or run its tombstone trigger after
  -- this binding is visible; never leave an unmarked orphan due to a race.
  SELECT * INTO r FROM __SCHEMA__.ai_mining_runs WHERE id=rid FOR KEY SHARE;
  SELECT * INTO ident FROM __SCHEMA__.binding_identity WHERE session_id=p.session_id;
  IF p.run_id IS NULL OR r.id IS NULL OR ident.session_id IS NULL OR p.ledger_id<>ledger OR r.session_id<>p.session_id
    OR NOT EXISTS(SELECT 1 FROM __SCHEMA__.experience_sessions s WHERE s.id=p.session_id AND s.status='active'
      AND s.mining_status='active' AND s.context_revision=r.reserved_revision)
    OR r.state<>'running' OR r.lease_until<=clock_timestamp() THEN RAISE EXCEPTION 'binding_business_inactive'; END IF;
  SELECT * INTO g FROM __SCHEMA__.paid_grants WHERE id=p.grant_id;
  IF g.id IS NULL OR g.policy_hash<>p.policy_sha OR encode(sha256(convert_to(g.policy->>'account_ref','UTF8')),'hex')<>p.account_sha
    OR g.policy->>'provider'<>'deepseek_official' OR g.policy->>'model'<>'deepseek-flash'
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(g.policy->'certificates') cert WHERE cert->>'request_sha'=p.request_sha)
    THEN RAISE EXCEPTION 'binding_plan_invalid'; END IF;
  -- Freeze new dispatch while ANY potentially billable result is unreconciled.
  -- Existing bound GET/replay above stays readable; no automatic refund/retry.
  IF EXISTS(SELECT 1 FROM __SCHEMA__.paid_calls WHERE actual IS NULL AND state IN ('sent','unknown','response_received')) THEN
    IF action='permit' AND c.state<>'reserved' THEN RETURN jsonb_build_object('permitted',false); END IF;
    RAISE EXCEPTION 'binding_unsettled_pool';
  END IF;
  IF action='bind' THEN
    answer:=__SCHEMA__.paid_runtime(ledger::text,'reserve',jsonb_build_object('id',gen_random_uuid(),
      'grant',p.grant_id,'operation',p.operation_hash,'request',p.request_sha,'policy',p.policy_sha,'batch','binding-v1-offline'));
    IF (answer->>'created')::boolean IS NOT TRUE THEN RAISE EXCEPTION 'binding_call_already_used'; END IF;
    cid:=(answer->>'id')::uuid;
    INSERT INTO __SCHEMA__.mining_call_bindings(contract_version,run_id,root_run_id,operation_hash,receipt_hash,
      actor_scope,session_scope,ledger_id,call_id,grant_id,provider,model,profile_version,
      request_sha,policy_sha,context_sha,prompt_sha,schema_sha,binding_state)
      VALUES(1,rid,p.root_run_id,p.operation_hash,p.receipt_hash,ident.actor_scope,ident.session_scope,ledger,cid,p.grant_id,
        'deepseek_official','deepseek-flash',p.profile_version,p.request_sha,p.policy_sha,p.context_sha,p.prompt_sha,p.schema_sha,'bound');
  ELSE cid:=b.call_id;
  END IF;
  -- Same central funding lock serializes all allocations, then sub-cap locks in
  -- user/session order. Accounting comes ONLY from paid_calls, never a new pool.
  FOREACH k IN ARRAY ARRAY['user','session'] LOOP
    v:=CASE WHEN k='user' THEN ident.actor_scope ELSE ident.session_scope END;
    SELECT * INTO lim FROM __SCHEMA__.binding_limits WHERE kind=k AND scope=v FOR UPDATE;
    IF lim.kind IS NULL OR lim.currency<>'CNY' THEN RAISE EXCEPTION 'binding_scope_unapproved'; END IF;
    SELECT count(*),coalesce(sum(coalesce(pc.actual,pc.reserved)),0),
      count(*) FILTER(WHERE pc.actual IS NULL) INTO n,used,active
      FROM __SCHEMA__.mining_call_bindings x JOIN __SCHEMA__.paid_calls pc ON pc.id=x.call_id
      WHERE (k='user' AND x.actor_scope=v) OR (k='session' AND x.session_scope=v);
    IF used>lim.ceiling OR n>lim.calls_limit OR active>lim.concurrent_limit THEN RAISE EXCEPTION 'binding_scope_exceeded'; END IF;
  END LOOP;
  IF action='permit' THEN
    RETURN __SCHEMA__.paid_runtime(ledger::text,'permit',jsonb_build_object('id',cid,'request',p.request_sha,'policy',p.policy_sha));
  END IF;
  RETURN jsonb_build_object('call_id',cid,'created',true);
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA __SCHEMA__ FROM __ROLE__;
REVOKE ALL ON FUNCTION __SCHEMA__.binding_runtime(uuid,text,uuid,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION __SCHEMA__.binding_immutable() FROM PUBLIC;
REVOKE ALL ON FUNCTION __SCHEMA__.binding_erasure() FROM PUBLIC;
GRANT USAGE ON SCHEMA __SCHEMA__ TO __ROLE__;
GRANT SELECT ON __SCHEMA__.mining_call_bindings,__SCHEMA__.paid_calls,__SCHEMA__.paid_funding TO __ROLE__;
GRANT EXECUTE ON FUNCTION __SCHEMA__.binding_runtime(uuid,text,uuid,jsonb) TO __ROLE__;
