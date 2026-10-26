-- Disposable extension of the unchanged G3 reference graph, NOT a migration.
-- __G__ graph schema, __S__ private gate schema; owner is synthetic NOLOGIN.
CREATE TABLE __S__.policy(mode text NOT NULL CHECK(mode IN ('broker','credential')),
 secret bytea NOT NULL CHECK(length(secret)=32), validator_hash text NOT NULL);
CREATE TABLE __S__.permits(
 operation_id uuid PRIMARY KEY REFERENCES __G__.ref_operations(id) DEFERRABLE INITIALLY DEFERRED,
 mode text NOT NULL, seal text NOT NULL, nonce uuid NOT NULL UNIQUE,
 expires_epoch bigint NOT NULL, validator_hash text NOT NULL, mac bytea,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
-- Every operation MUST have an authorized permit, even direct SQL at COMMIT.
ALTER TABLE __G__.ref_operations ADD CONSTRAINT g4_permit_required
 FOREIGN KEY(id) REFERENCES __S__.permits(operation_id) DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION __S__.seal(oid uuid) RETURNS text LANGUAGE sql STABLE
 SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('domain','g4-disposable-proof-v1','schema','__G__',
 'session',(SELECT to_jsonb(s) FROM __G__.ref_sessions s WHERE s.id=o.session_id),
 'operation',to_jsonb(o),
 'turns',(SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id) FROM __G__.ref_turns t WHERE t.operation_id=oid),
 'facts',(SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id) FROM __G__.ref_facts t WHERE t.operation_id=oid),
 'changes',(SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id) FROM __G__.ref_changes t WHERE t.operation_id=oid),
 'sources',(SELECT jsonb_agg(to_jsonb(t) ORDER BY t.fact_id) FROM __G__.ref_sources t WHERE t.operation_id=oid),
 'fcs',(SELECT jsonb_agg(to_jsonb(t) ORDER BY t.effect_slot) FROM __G__.ref_fcs t WHERE t.operation_id=oid),
 'choices',(SELECT jsonb_agg(to_jsonb(t) ORDER BY t.effect_slot) FROM __G__.ref_choices t WHERE t.operation_id=oid),
 'auth',(SELECT to_jsonb(t) FROM __G__.ref_auth_contexts t WHERE t.operation_id=oid))::text
 FROM __G__.ref_operations o WHERE o.id=oid $$;

-- RFC 2104 HMAC-SHA256 using built-in sha256(bytea); no extension installation.
-- Private and never granted to a request identity. RFC test vectors in tests.
CREATE FUNCTION __S__.hmac256(msg bytea, k bytea) RETURNS bytea
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
 DECLARE pad bytea; ip bytea; op bytea; n integer;
 BEGIN
 IF length(k)>64 THEN k:=sha256(k); END IF;
 pad:=k || decode(repeat('00',64-length(k)),'hex'); ip:=pad; op:=pad;
 FOR n IN 0..63 LOOP
 ip:=set_byte(ip,n,get_byte(pad,n)#54); op:=set_byte(op,n,get_byte(pad,n)#92);
 END LOOP;
 RETURN sha256(op||sha256(ip||msg));
 END $$;

CREATE FUNCTION __S__.check_permit() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog AS $$
 DECLARE p __S__.policy%ROWTYPE; expected bytea; diff integer:=0; n integer; msg text;
 BEGIN
 SELECT * INTO STRICT p FROM __S__.policy;
 IF session_user<>'__WRITER__' OR NEW.mode IS DISTINCT FROM p.mode
 OR NEW.validator_hash IS DISTINCT FROM p.validator_hash
 OR NEW.expires_epoch<=extract(epoch FROM clock_timestamp())
 OR NEW.expires_epoch>extract(epoch FROM clock_timestamp())+300
 OR NEW.seal IS DISTINCT FROM encode(sha256(convert_to(__S__.seal(NEW.operation_id),'UTF8')),'hex') THEN
 RAISE EXCEPTION 'g4_boundary_refused' USING ERRCODE='23514'; END IF;
 PERFORM __G__.ref_validate(NEW.operation_id);
 IF p.mode='broker' THEN
 IF NEW.mac IS NOT NULL THEN RAISE EXCEPTION 'g4_boundary_refused' USING ERRCODE='23514'; END IF;
 ELSE
 msg:='g4-proof-v1'||chr(10)||NEW.validator_hash||chr(10)||NEW.expires_epoch::text||chr(10)||NEW.nonce::text||chr(10)||NEW.seal;
 expected:=__S__.hmac256(convert_to(msg,'UTF8'),p.secret);
 IF NEW.mac IS NULL OR length(NEW.mac)<>32 THEN
 RAISE EXCEPTION 'g4_boundary_refused' USING ERRCODE='23514'; END IF;
 FOR n IN 0..31 LOOP diff:=diff | (get_byte(expected,n)#get_byte(NEW.mac,n)); END LOOP;
 IF diff<>0 THEN RAISE EXCEPTION 'g4_boundary_refused' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
 END $$;
CREATE TRIGGER verify_permit BEFORE INSERT ON __S__.permits
 FOR EACH ROW EXECUTE FUNCTION __S__.check_permit();
CREATE CONSTRAINT TRIGGER verify_at_commit AFTER INSERT ON __S__.permits
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.check_permit();
CREATE FUNCTION __S__.deny_permit_mutation() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog AS $$
 BEGIN RAISE EXCEPTION 'g4_permit_immutable' USING ERRCODE='23514'; END $$;
CREATE TRIGGER immutable_permit BEFORE UPDATE OR DELETE ON __S__.permits
 FOR EACH ROW EXECUTE FUNCTION __S__.deny_permit_mutation();
CREATE TRIGGER no_truncate_permit BEFORE TRUNCATE ON __S__.permits
 FOR EACH STATEMENT EXECUTE FUNCTION __S__.deny_permit_mutation();
REVOKE ALL ON ALL TABLES IN SCHEMA __S__ FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA __S__ FROM PUBLIC;
