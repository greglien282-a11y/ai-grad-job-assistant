-- Disposable REFERENCE ONLY. __S__ is a validated random g3_ref_* schema.
-- Not an Alembic migration, not compatible with a production runtime factory.
CREATE TABLE __S__.ref_sessions (
 id uuid PRIMARY KEY, project_id uuid NOT NULL UNIQUE, subject_id uuid NOT NULL,
 credential_hash text NOT NULL CHECK(credential_hash ~ '^[a-f0-9]{64}$'),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 new_command_review_required boolean NOT NULL DEFAULT false,
 UNIQUE(id,project_id)
);
CREATE TABLE __S__.ref_operations (
 id uuid PRIMARY KEY, key_digest text NOT NULL UNIQUE CHECK(key_digest ~ '^[a-f0-9]{64}$'),
 scope_digest text NOT NULL CHECK(scope_digest ~ '^[a-f0-9]{64}$'), owner_digest text NOT NULL CHECK(owner_digest ~ '^[a-f0-9]{64}$'),
 contract_version integer NOT NULL CHECK(contract_version IN (1,2,3)),
 scheme text NOT NULL CHECK(scheme IN ('A','B','opaque')),
 state text NOT NULL DEFAULT 'applied' CHECK(state IN ('applied','deleted')),
 session_id uuid REFERENCES __S__.ref_sessions(id) DEFERRABLE INITIALLY DEFERRED,
 project_id uuid, input_turn_id uuid, choice_turn_id uuid,
 item_count integer, base_revision integer, result_revision integer, request_digest text,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '24 hours',
 created_xid bigint NOT NULL DEFAULT txid_current(),
 CHECK(expires_at>recorded_at),
 CHECK((contract_version IN (1,2) AND scheme='opaque') OR (contract_version=3 AND scheme IN ('A','B'))),
 CHECK((
   (state='deleted' AND num_nonnulls(session_id,project_id,input_turn_id,choice_turn_id,item_count,base_revision,result_revision,request_digest)=0)
   OR (state='applied' AND session_id IS NOT NULL AND project_id IS NOT NULL AND request_digest IS NOT NULL
     AND ((scheme='opaque' AND item_count=0)
       OR (item_count BETWEEN 1 AND 5 AND base_revision>0 AND result_revision=base_revision+1
         AND input_turn_id IS NOT NULL
         AND ((scheme='A' AND choice_turn_id IS NULL) OR (scheme='B' AND choice_turn_id IS NOT NULL)))))
 ) IS TRUE)
);
CREATE TABLE __S__.ref_auth_contexts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), operation_id uuid NOT NULL UNIQUE REFERENCES __S__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 session_id uuid NOT NULL REFERENCES __S__.ref_sessions(id) ON DELETE CASCADE,
 project_id uuid NOT NULL, authenticated_subject uuid NOT NULL,
 issuer text NOT NULL CHECK(issuer='synthetic-server-auth-v1'),
 db_login name NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_xid bigint NOT NULL DEFAULT txid_current()
);
CREATE TABLE __S__.ref_turns (
 id uuid PRIMARY KEY, operation_id uuid NOT NULL REFERENCES __S__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 session_id uuid NOT NULL REFERENCES __S__.ref_sessions(id) ON DELETE CASCADE,
 purpose text NOT NULL CHECK(purpose IN ('body','choice')), role text NOT NULL CHECK(role='user'),
 content text NOT NULL CHECK(length(content) BETWEEN 1 AND 10000),
 UNIQUE(operation_id,purpose),
 created_xid bigint NOT NULL DEFAULT txid_current()
);
-- Original text reuse is conservative; independent UI selections may legitimately
-- repeat the same labels in a later operation. They still need fresh identities.
CREATE UNIQUE INDEX ref_unique_original_turn ON __S__.ref_turns(session_id,content) WHERE purpose='body';
CREATE TABLE __S__.ref_facts (
 id uuid PRIMARY KEY, operation_id uuid NOT NULL REFERENCES __S__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 session_id uuid NOT NULL REFERENCES __S__.ref_sessions(id) ON DELETE CASCADE, project_id uuid NOT NULL,
 version integer NOT NULL CHECK(version=1), statement text NOT NULL CHECK(length(statement) BETWEEN 1 AND 500),
 status text NOT NULL CHECK(status='pending'), memory_state text NOT NULL CHECK(memory_state='unspecified'),
 origin text NOT NULL CHECK(origin='manual'), ai_run_id uuid CHECK(ai_run_id IS NULL), evidence_id uuid CHECK(evidence_id IS NULL),
 fact_kind text NOT NULL, progress_stage text NOT NULL,
 classification_contract text NOT NULL CHECK(classification_contract='explicit-typed-v1'),
 CHECK((fact_kind='personal_action' AND progress_stage IN ('completed','in_progress')) OR
 (fact_kind='plan' AND progress_stage IN ('planned','in_progress')) OR
 (fact_kind IN ('background','boundary') AND progress_stage='not_applicable')),
 UNIQUE(session_id,statement), created_xid bigint NOT NULL DEFAULT txid_current()
);
CREATE TABLE __S__.ref_changes (
 id uuid PRIMARY KEY, operation_id uuid NOT NULL REFERENCES __S__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 session_id uuid NOT NULL REFERENCES __S__.ref_sessions(id) ON DELETE CASCADE,
 fact_id uuid NOT NULL UNIQUE REFERENCES __S__.ref_facts(id) ON DELETE CASCADE,
 action text NOT NULL CHECK(action='created'), actor text NOT NULL CHECK(actor='system'),
 before jsonb CHECK(before IS NULL), after jsonb NOT NULL,
 created_xid bigint NOT NULL DEFAULT txid_current()
);
CREATE TABLE __S__.ref_sources (
 fact_id uuid PRIMARY KEY REFERENCES __S__.ref_facts(id) ON DELETE CASCADE,
 operation_id uuid NOT NULL REFERENCES __S__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 session_id uuid NOT NULL REFERENCES __S__.ref_sessions(id) ON DELETE CASCADE,
 turn_id uuid NOT NULL REFERENCES __S__.ref_turns(id), start_cp integer NOT NULL,
 end_cp integer NOT NULL, quote text NOT NULL,
 CHECK(start_cp>=0 AND end_cp>start_cp), created_xid bigint NOT NULL DEFAULT txid_current()
);
CREATE TABLE __S__.ref_fcs (
 operation_id uuid NOT NULL REFERENCES __S__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 effect_slot integer NOT NULL CHECK(effect_slot BETWEEN 1 AND 5), PRIMARY KEY(operation_id,effect_slot),
 session_id uuid NOT NULL REFERENCES __S__.ref_sessions(id) ON DELETE CASCADE,
 fact_id uuid NOT NULL UNIQUE REFERENCES __S__.ref_facts(id) ON DELETE CASCADE,
 change_id uuid NOT NULL UNIQUE REFERENCES __S__.ref_changes(id) ON DELETE CASCADE,
 turn_id uuid NOT NULL REFERENCES __S__.ref_turns(id), start_cp integer NOT NULL,
 end_cp integer NOT NULL, quote text NOT NULL,
 source_role text NOT NULL CHECK(source_role='statement'),
 CHECK(start_cp>=0 AND end_cp>start_cp), created_xid bigint NOT NULL DEFAULT txid_current()
);
CREATE TABLE __S__.ref_choices (
 id uuid PRIMARY KEY, operation_id uuid NOT NULL REFERENCES __S__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 effect_slot integer NOT NULL CHECK(effect_slot BETWEEN 1 AND 5), UNIQUE(operation_id,effect_slot),
 session_id uuid NOT NULL REFERENCES __S__.ref_sessions(id) ON DELETE CASCADE, project_id uuid NOT NULL,
 fact_id uuid NOT NULL UNIQUE REFERENCES __S__.ref_facts(id) ON DELETE CASCADE,
 fact_version integer NOT NULL CHECK(fact_version=1), change_id uuid NOT NULL UNIQUE REFERENCES __S__.ref_changes(id) ON DELETE CASCADE,
 basis_contract text NOT NULL, source_kind text NOT NULL,
 fact_kind text NOT NULL, progress_stage text NOT NULL, classification_contract text NOT NULL,
 statement_turn_id uuid NOT NULL REFERENCES __S__.ref_turns(id), start_cp integer NOT NULL, end_cp integer NOT NULL, quote text NOT NULL,
 selection_id uuid NOT NULL UNIQUE, selection jsonb NOT NULL,
 auth_context_id uuid NOT NULL REFERENCES __S__.ref_auth_contexts(id),
 validator_contract text NOT NULL CHECK(validator_contract='typed-semantic-spike-v1'),
 validation_result text NOT NULL CHECK(validation_result='finite_rule_match'),
 choice_turn_id uuid REFERENCES __S__.ref_turns(id), choice_start_cp integer, choice_end_cp integer, choice_quote text,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), created_xid bigint NOT NULL DEFAULT txid_current(),
 CHECK((source_kind='immutable_user_choice_event' AND basis_contract='g3-choice-event-ref-v1'
 AND num_nonnulls(choice_turn_id,choice_start_cp,choice_end_cp,choice_quote)=0)
 OR (source_kind='conversation_turn' AND basis_contract='g3-choice-turn-ref-v1'
 AND num_nonnulls(choice_turn_id,choice_start_cp,choice_end_cp,choice_quote)=4 AND choice_start_cp>=0 AND choice_end_cp>choice_start_cp))
);

-- Only a server-side function can record the audit context. actor='user' is
-- neither an input nor an authentication method. Tokens are synthetic fixtures.
CREATE FUNCTION __S__.ref_authorize(sid uuid, token text) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM __S__.ref_sessions s WHERE s.id=sid
 AND s.credential_hash=encode(sha256(convert_to(token,'UTF8')),'hex')) $$;
-- Row locking otherwise requires UPDATE privilege. Keep the writer INSERT-only
-- on receipts: this private function grants locking, never arbitrary mutation.
-- Caller already authenticates before key lookup; the role can SELECT receipts.
CREATE FUNCTION __S__.ref_lock_operation(key_hash text) RETURNS __S__.ref_operations
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
 DECLARE o __S__.ref_operations%ROWTYPE;
 BEGIN
 SELECT * INTO o FROM __S__.ref_operations WHERE key_digest=key_hash FOR UPDATE;
 RETURN o;
 END $$;
CREATE FUNCTION __S__.ref_record_auth(oid uuid, sid uuid, token text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
 DECLARE aid uuid; s __S__.ref_sessions%ROWTYPE;
 BEGIN
 IF NOT __S__.ref_authorize(sid,token) THEN RAISE EXCEPTION 'ref_auth_required' USING ERRCODE='42501'; END IF;
 SELECT * INTO s FROM __S__.ref_sessions WHERE id=sid;
 INSERT INTO __S__.ref_auth_contexts(operation_id,session_id,project_id,authenticated_subject,issuer,db_login)
 VALUES(oid,sid,s.project_id,s.subject_id,'synthetic-server-auth-v1',session_user) RETURNING id INTO aid;
 RETURN aid;
 END $$;

CREATE FUNCTION __S__.ref_validate(oid uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
 DECLARE o __S__.ref_operations%ROWTYPE; s __S__.ref_sessions%ROWTYPE; t __S__.ref_turns%ROWTYPE;
 a __S__.ref_auth_contexts%ROWTYPE; r record; expected jsonb; expected_choice text; request_body jsonb;
 BEGIN
 SELECT * INTO o FROM __S__.ref_operations WHERE id=oid;
 IF o.id IS NULL THEN RETURN; END IF;
 IF o.state='deleted' OR o.scheme='opaque' THEN
   IF EXISTS(SELECT 1 FROM __S__.ref_turns WHERE operation_id=oid) OR EXISTS(SELECT 1 FROM __S__.ref_auth_contexts WHERE operation_id=oid)
   OR EXISTS(SELECT 1 FROM __S__.ref_facts WHERE operation_id=oid) THEN RAISE EXCEPTION 'ref_opaque_graph' USING ERRCODE='23514'; END IF;
   RETURN;
 END IF;
 SELECT * INTO s FROM __S__.ref_sessions WHERE id=o.session_id;
 SELECT * INTO t FROM __S__.ref_turns WHERE id=o.input_turn_id;
 SELECT * INTO a FROM __S__.ref_auth_contexts WHERE operation_id=oid;
 IF s.id IS NULL OR s.project_id IS DISTINCT FROM o.project_id OR s.revision<o.result_revision
 OR o.owner_digest<>s.credential_hash OR o.scope_digest<>encode(sha256(convert_to(s.id::text,'UTF8')),'hex')
 OR t.id IS NULL OR t.operation_id<>oid OR t.session_id<>s.id OR t.purpose<>'body'
 OR a.id IS NULL OR a.session_id<>s.id OR a.project_id<>s.project_id OR a.authenticated_subject<>s.subject_id
 OR a.created_xid<>o.created_xid OR t.created_xid<>o.created_xid
 OR (SELECT count(*) FROM __S__.ref_turns WHERE operation_id=oid)<>(CASE WHEN o.scheme='A' THEN 1 ELSE 2 END)
 OR (SELECT count(*) FROM __S__.ref_facts WHERE operation_id=oid)<>o.item_count
 OR (SELECT count(*) FROM __S__.ref_changes WHERE operation_id=oid)<>o.item_count
 OR (SELECT count(*) FROM __S__.ref_sources WHERE operation_id=oid)<>o.item_count
 OR (SELECT count(*) FROM __S__.ref_fcs WHERE operation_id=oid)<>o.item_count
 OR (SELECT count(*) FROM __S__.ref_choices WHERE operation_id=oid)<>o.item_count
 OR (SELECT array_agg(effect_slot ORDER BY effect_slot) FROM __S__.ref_fcs WHERE operation_id=oid)
    IS DISTINCT FROM ARRAY(SELECT generate_series(1,o.item_count)) THEN
 RAISE EXCEPTION 'ref_graph_incomplete' USING ERRCODE='23514'; END IF;
 FOR r IN SELECT x.*, f.statement, f.version, f.fact_kind AS fk, f.progress_stage AS ps, f.classification_contract AS cc,
 f.status, f.origin, f.memory_state, f.ai_run_id, f.evidence_id, c.id AS cid, c.after AS snap,
 b.id AS bid,b.auth_context_id,b.selection,b.selection_id,b.fact_kind AS bk,b.progress_stage AS bp,b.classification_contract AS bc,
 b.source_kind,b.choice_turn_id,b.choice_start_cp,b.choice_end_cp,b.choice_quote,
 b.basis_contract,b.fact_version,b.statement_turn_id,b.start_cp AS bs,b.end_cp AS be,b.quote AS bq,
 z.start_cp AS zs,z.end_cp AS ze,z.quote AS zq,z.turn_id AS zt,
 f.operation_id AS fo,c.operation_id AS co,b.operation_id AS bo,z.operation_id AS zo,
 f.session_id AS fs,c.session_id AS cs,b.session_id AS bsession,z.session_id AS zsesh,
 f.project_id AS fp,b.project_id AS bpj,c.fact_id AS cf,b.fact_id AS bf,b.change_id AS bchange,
 f.created_xid AS fx,c.created_xid AS cx,b.created_xid AS bx,z.created_xid AS zx
 FROM __S__.ref_fcs x JOIN __S__.ref_facts f ON f.id=x.fact_id JOIN __S__.ref_changes c ON c.id=x.change_id
 JOIN __S__.ref_sources z ON z.fact_id=f.id JOIN __S__.ref_choices b ON b.operation_id=x.operation_id AND b.effect_slot=x.effect_slot
 WHERE x.operation_id=oid LOOP
 expected:=jsonb_build_object('version',1,'statement',r.statement,'status','pending','origin','manual','memory_state','unspecified',
 'ai_run_id',NULL,'evidence_id',NULL,'fact_kind',r.fk,'progress_stage',r.ps,'classification_contract',r.cc,
 'original_turn_id',t.id,'start_cp',r.start_cp,'end_cp',r.end_cp,'quote',r.quote,'basis_id',r.bid);
 expected_choice:=r.effect_slot::text||':'||r.fk||'/'||r.ps;
 IF r.fo<>oid OR r.co<>oid OR r.bo<>oid OR r.zo<>oid OR r.fs<>s.id OR r.cs<>s.id OR r.bsession<>s.id OR r.zsesh<>s.id
 OR r.session_id<>s.id OR r.fp<>s.project_id OR r.bpj<>s.project_id OR r.cf<>r.fact_id OR r.bf<>r.fact_id OR r.bchange<>r.cid
 OR r.turn_id<>t.id OR r.statement_turn_id<>t.id OR r.zt<>t.id OR r.auth_context_id<>a.id OR r.fact_version<>r.version
 OR (r.bk,r.bp,r.bc) IS DISTINCT FROM (r.fk,r.ps,r.cc)
 OR r.selection IS DISTINCT FROM jsonb_build_object('fact_kind',r.fk,'progress_stage',r.ps,'classification_contract',r.cc)
 OR r.snap IS DISTINCT FROM expected OR (r.bs,r.be,r.bq) IS DISTINCT FROM (r.start_cp,r.end_cp,r.quote)
 OR (r.zs,r.ze,r.zq) IS DISTINCT FROM (r.start_cp,r.end_cp,r.quote)
 OR substring(t.content FROM r.start_cp+1 FOR r.end_cp-r.start_cp) IS DISTINCT FROM r.quote OR r.quote<>r.statement
 OR r.end_cp>length(t.content) OR r.start_cp<0 OR r.end_cp<=r.start_cp
 OR r.fx<>o.created_xid OR r.cx<>o.created_xid OR r.bx<>o.created_xid OR r.zx<>o.created_xid OR r.created_xid<>o.created_xid
 OR (o.scheme='A' AND r.source_kind<>'immutable_user_choice_event')
 OR (o.scheme='B' AND (r.source_kind<>'conversation_turn' OR r.choice_turn_id IS DISTINCT FROM o.choice_turn_id
 OR r.choice_quote IS DISTINCT FROM expected_choice OR NOT EXISTS(SELECT 1 FROM __S__.ref_turns ct WHERE ct.id=o.choice_turn_id
 AND ct.operation_id=oid AND ct.session_id=s.id AND ct.purpose='choice' AND ct.created_xid=o.created_xid
 AND r.choice_end_cp<=length(ct.content) AND r.choice_end_cp-r.choice_start_cp=length(r.choice_quote)
 AND substring(ct.content FROM r.choice_start_cp+1 FOR r.choice_end_cp-r.choice_start_cp)=r.choice_quote))) THEN
 RAISE EXCEPTION 'ref_binding_invalid' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM __S__.ref_fcs x JOIN __S__.ref_choices b ON b.operation_id=x.operation_id AND b.effect_slot=x.effect_slot
   JOIN __S__.ref_facts f ON f.id=x.fact_id JOIN __S__.ref_changes c ON c.id=x.change_id JOIN __S__.ref_sources z ON z.fact_id=f.id WHERE x.operation_id=oid)<>o.item_count
 OR EXISTS(SELECT 1 FROM (SELECT start_cp,lag(end_cp) OVER(ORDER BY effect_slot) previous FROM __S__.ref_fcs WHERE operation_id=oid) v WHERE start_cp<coalesce(previous,0))
 OR regexp_replace(t.content,E'[ \\t\\r\\n]','','g') IS DISTINCT FROM
 (SELECT regexp_replace(string_agg(quote,'' ORDER BY effect_slot),E'[ \\t\\r\\n]','','g') FROM __S__.ref_fcs WHERE operation_id=oid)
 OR (o.scheme='B' AND (SELECT content FROM __S__.ref_turns WHERE id=o.choice_turn_id) IS DISTINCT FROM
 (SELECT string_agg(effect_slot::text||':'||fact_kind||'/'||progress_stage,E'\n' ORDER BY effect_slot) FROM __S__.ref_choices WHERE operation_id=oid)) THEN
 RAISE EXCEPTION 'ref_spans_invalid' USING ERRCODE='23514'; END IF;
 SELECT jsonb_build_object('reference_contract','g3-choice-graph-ref-v1','contract_version',3,'scheme',o.scheme,
 'session_id',s.id,'project_id',s.project_id,'base_revision',o.base_revision,'content',t.content,
 'items',jsonb_agg(jsonb_build_object('quote',b.quote,'start',b.start_cp,'end',b.end_cp,'fact_kind',b.fact_kind,
 'progress_stage',b.progress_stage,'classification_contract',b.classification_contract,'selection_id',b.selection_id)
 ORDER BY b.effect_slot)) INTO request_body FROM __S__.ref_choices b WHERE b.operation_id=oid;
 IF o.request_digest IS DISTINCT FROM encode(sha256(convert_to(request_body::text,'UTF8')),'hex') THEN
 RAISE EXCEPTION 'ref_request_digest_invalid' USING ERRCODE='23514'; END IF;
 END $$;

CREATE FUNCTION __S__.ref_consistent() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
 DECLARE oid uuid; o __S__.ref_operations%ROWTYPE;
 BEGIN
 IF TG_TABLE_NAME='ref_operations' THEN oid:=NEW.id;
 ELSIF TG_OP='DELETE' THEN oid:=OLD.operation_id; ELSE oid:=NEW.operation_id; END IF;
 PERFORM __S__.ref_validate(oid);
 SELECT * INTO o FROM __S__.ref_operations WHERE id=oid;
 IF o.state='applied' AND o.scheme<>'opaque' AND o.created_xid=txid_current() THEN
   PERFORM 1 FROM __S__.ref_sessions WHERE id=o.session_id FOR UPDATE;
   IF NOT EXISTS(SELECT 1 FROM __S__.ref_sessions WHERE id=o.session_id AND revision=o.result_revision AND NOT new_command_review_required) THEN
     RAISE EXCEPTION 'ref_revision_or_review' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
 END $$;
CREATE FUNCTION __S__.ref_revision() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
 BEGIN
 IF NOT EXISTS(SELECT 1 FROM __S__.ref_sessions WHERE id=NEW.id) THEN RETURN NULL; END IF;
 IF NEW.revision<>OLD.revision+1 OR (SELECT count(*) FROM __S__.ref_operations WHERE session_id=NEW.id AND created_xid=txid_current()
 AND base_revision=OLD.revision AND result_revision=NEW.revision AND state='applied' AND scheme<>'opaque')<>1 THEN
 RAISE EXCEPTION 'ref_revision_without_operation' USING ERRCODE='23514'; END IF;
 RETURN NULL;
 END $$;
CREATE CONSTRAINT TRIGGER ref_revision_guard AFTER UPDATE OF revision ON __S__.ref_sessions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.ref_revision();

-- An authorized erase is separate from append/replay. No content in tombstones.
CREATE FUNCTION __S__.ref_erase(sid uuid,token text) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
 BEGIN
 IF NOT __S__.ref_authorize(sid,token) THEN RAISE EXCEPTION 'ref_auth_required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM __S__.ref_sessions WHERE id=sid FOR UPDATE;
 UPDATE __S__.ref_operations SET state='deleted',session_id=NULL,project_id=NULL,input_turn_id=NULL,choice_turn_id=NULL,
 item_count=NULL,base_revision=NULL,result_revision=NULL,request_digest=NULL WHERE session_id=sid;
 DELETE FROM __S__.ref_sessions WHERE id=sid;
 END $$;
CREATE FUNCTION __S__.ref_immutable() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
 BEGIN
 IF TG_OP='TRUNCATE' THEN RAISE EXCEPTION 'ref_immutable' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME<>'ref_operations' AND TG_OP='DELETE' AND NOT EXISTS(SELECT 1 FROM __S__.ref_sessions WHERE id=OLD.session_id) THEN RETURN OLD; END IF;
 IF TG_TABLE_NAME='ref_operations' AND TG_OP='UPDATE' THEN
   IF current_user='__OWNER_NAME__' AND NEW.state='deleted'
   AND (NEW.id,NEW.key_digest,NEW.scope_digest,NEW.owner_digest,NEW.contract_version,NEW.scheme,NEW.recorded_at,NEW.expires_at,NEW.created_xid)
   IS NOT DISTINCT FROM (OLD.id,OLD.key_digest,OLD.scope_digest,OLD.owner_digest,OLD.contract_version,OLD.scheme,OLD.recorded_at,OLD.expires_at,OLD.created_xid) THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION 'ref_immutable' USING ERRCODE='23514';
 END $$;
