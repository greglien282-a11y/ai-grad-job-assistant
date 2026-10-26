"""Disposable immutable source receipt, NOT an approved retention protocol."""
import hashlib
from dataclasses import asdict
from psycopg import sql
from psycopg.types.json import Jsonb
from research.g3_choice_protocol.runtime import Refused, digest, request_digest


def encode(source):
    return {**asdict(source), 'mac': source.mac.hex()}


def install(x):
    m, g = x.model, x.gate
    schema = g.schema + '_source'
    m.admin.execute(sql.SQL('CREATE SCHEMA {} AUTHORIZATION {}').format(sql.Identifier(schema), sql.Identifier(m.roles['owner'])))
    m.admin.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(m.roles['owner'])))
    try:
        m.admin.execute(sql.SQL('''CREATE TABLE {}(operation_id uuid PRIMARY KEY REFERENCES {}(id) DEFERRABLE INITIALLY DEFERRED,
            session_id uuid NOT NULL, origin_nonce uuid NOT NULL UNIQUE, source_record jsonb NOT NULL CHECK(jsonb_typeof(source_record)='object'),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), created_xid bigint NOT NULL DEFAULT txid_current())''').format(sql.Identifier(schema,'receipts'), sql.Identifier(m.schema,'ref_operations')))
        m.admin.execute(sql.SQL('ALTER TABLE {} ADD CONSTRAINT g4_source_required FOREIGN KEY(id) REFERENCES {}(operation_id) DEFERRABLE INITIALLY DEFERRED').format(sql.Identifier(m.schema,'ref_operations'), sql.Identifier(schema,'receipts')))
        m.admin.execute(sql.SQL('''CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
          BEGIN RAISE EXCEPTION 'source_audit_immutable' USING ERRCODE='23514'; END $$''').format(sql.Identifier(schema,'immutable')))
        m.admin.execute(sql.SQL('CREATE TRIGGER source_immutable BEFORE UPDATE OR DELETE ON {} FOR EACH ROW EXECUTE FUNCTION {}()').format(sql.Identifier(schema,'receipts'),sql.Identifier(schema,'immutable')))
        m.admin.execute(sql.SQL('CREATE TRIGGER source_no_truncate BEFORE TRUNCATE ON {} FOR EACH STATEMENT EXECUTE FUNCTION {}()').format(sql.Identifier(schema,'receipts'),sql.Identifier(schema,'immutable')))
        # Wrap the unchanged graph seal, so the SAME final MAC also covers the
        # actual immutable source row. It is not an unsigned sidecar receipt.
        m.admin.execute(sql.SQL('ALTER FUNCTION {}(uuid) RENAME TO base_seal').format(sql.Identifier(g.schema,'seal')))
        m.admin.execute(sql.SQL('REVOKE ALL ON FUNCTION {}(uuid) FROM {},PUBLIC').format(sql.Identifier(g.schema,'base_seal'),sql.Identifier(m.roles['writer'])))
        m.admin.execute(sql.SQL('''CREATE FUNCTION {}(oid uuid) RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT (({}(oid)::jsonb) || jsonb_build_object('source_receipt',(SELECT to_jsonb(r) FROM {} r WHERE operation_id=oid)))::text $$''').format(sql.Identifier(g.schema,'seal'),sql.Identifier(g.schema,'base_seal'),sql.Identifier(schema,'receipts')))
        m.admin.execute(sql.SQL('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC').format(sql.Identifier(g.schema)))
        m.admin.execute(sql.SQL('GRANT EXECUTE ON FUNCTION {}(uuid) TO {}').format(sql.Identifier(g.schema,'seal'),sql.Identifier(m.roles['writer'])))
        m.admin.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
        m.admin.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
        m.admin.execute(sql.SQL('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
        for role in ('reader','writer'):
            m.admin.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(m.roles[role])))
        m.admin.execute(sql.SQL('GRANT INSERT(operation_id,session_id,origin_nonce,source_record) ON {} TO {}').format(sql.Identifier(schema,'receipts'),sql.Identifier(m.roles['writer'])))
        m.admin.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(sql.Identifier(schema,'receipts'),sql.Identifier(m.roles['reader'])))
    finally:
        m.admin.execute('RESET ROLE')
    g.functions = {r['proname']:hashlib.sha256(r['definition'].encode()).hexdigest() for r in m.admin.execute('SELECT proname,pg_get_functiondef(oid) AS definition FROM pg_proc WHERE pronamespace=%s::regnamespace',(g.schema,))}
    # Capture a finite approved manifest OUTSIDE requests, never learn it live.
    x.audit_schema = schema
    x.audit_manifest = metadata(m.admin, schema)
    original = m.snapshot
    def snapshot():
        result = original()
        result['g4_source_receipts'] = m.admin.execute(sql.SQL('SELECT to_jsonb(r)::text AS row FROM {} r ORDER BY operation_id').format(sql.Identifier(schema,'receipts'))).fetchall()
        return result
    m.snapshot = snapshot


def metadata(db, schema):
    return {
        'functions': db.execute('SELECT pg_get_functiondef(oid) AS definition,proacl::text FROM pg_proc WHERE pronamespace=%s::regnamespace ORDER BY proname',(schema,)).fetchall(),
        'triggers': db.execute('SELECT pg_get_triggerdef(oid) AS definition,tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND NOT tgisinternal ORDER BY tgname',(schema+'.receipts',)).fetchall(),
        'acl': db.execute('SELECT relacl::text,relowner FROM pg_class WHERE oid=%s::regclass',(schema+'.receipts',)).fetchall(),
        'fk': db.execute('SELECT pg_get_constraintdef(oid) AS definition,convalidated,condeferrable,condeferred FROM pg_constraint WHERE conrelid=%s::regclass ORDER BY conname',(schema+'.receipts',)).fetchall(),
        'reverse_fk': db.execute('SELECT pg_get_constraintdef(oid) AS definition,convalidated,condeferrable,condeferred FROM pg_constraint WHERE confrelid=%s::regclass AND conname=\'g4_source_required\'',(schema+'.receipts',)).fetchall(),
        'schema': db.execute('SELECT nspowner,nspacl::text FROM pg_namespace WHERE oid=%s::regnamespace',(schema,)).fetchall(),
    }


def admit(db, x, mode):
    if metadata(db, x.audit_schema) != x.audit_manifest:
        raise Refused('source_audit_unavailable')
    rows = db.execute('''SELECT attname,has_column_privilege(attrelid,attnum,'SELECT') AS sel,
       has_column_privilege(attrelid,attnum,'INSERT') AS ins,has_column_privilege(attrelid,attnum,'UPDATE') AS upd
       FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped''',(x.audit_schema+'.receipts',)).fetchall()
    if len(rows) != 6 or any((r['sel'],r['ins'],r['upd']) != (mode=='reader',mode=='writer' and r['attname'] in ('operation_id','session_id','origin_nonce','source_record'),False) for r in rows):
        raise Refused('source_audit_acl_unapproved')
    bad = db.execute("SELECT has_table_privilege(%s,'DELETE,TRUNCATE,TRIGGER,REFERENCES') AS bad,has_schema_privilege(%s,'CREATE') AS create",(x.audit_schema+'.receipts',x.audit_schema)).fetchone()
    if any(bad.values()): raise Refused('source_audit_acl_unapproved')


def insert(db, x, oid, sid, source):
    db.execute(sql.SQL('INSERT INTO {}(operation_id,session_id,origin_nonce,source_record) VALUES(%s,%s,%s,%s)').format(sql.Identifier(x.audit_schema,'receipts')),(oid,sid,source.nonce,Jsonb(encode(source))))


def read(db, x, b, key, operation_id):
    admit(db, x, 'reader')
    r = db.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s AND session_id=%s').format(sql.Identifier(x.audit_schema,'receipts')),(operation_id,b.sid)).fetchone()
    op = db.execute('SELECT * FROM ref_operations WHERE id=%s',(operation_id,)).fetchone()
    if not r or not op: raise Refused('source_audit_incomplete')
    source = r['source_record']; body = source['body']
    if source['key_digest'] != digest(key) or source['bearer_digest'] != digest(b.token) or body['session_id'] != str(b.sid) or body['project_id'] != str(b.pid) or request_digest(db,body) != op['request_digest'] or source['subject'] != str(b.subject) or r['created_xid'] != op['created_xid']:
        raise Refused('source_audit_incomplete')
    from research.g4_source_binding.binding import canonical
    return dict(receipt_contract='g4-source-audit-read-ref-v1', operation_id=operation_id,
        origin_nonce=str(r['origin_nonce']), source_body_sha256=hashlib.sha256(canonical(body).encode()).hexdigest(),
        selection_ids=[item['selection_id'] for item in body['items']], expires_epoch=source['expires'],
        ingress_binding='exact_candidate_request', retention_policy='DISPOSABLE_ONLY_UNAPPROVED', semantic_independence='NOT_PROVEN')
