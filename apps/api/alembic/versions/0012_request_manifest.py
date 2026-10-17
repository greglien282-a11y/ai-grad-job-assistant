"""Inert immutable manifest metadata. NO production request body store."""
from alembic import op
import sqlalchemy as sa

revision = '0012_request_manifest'
down_revision = '0011_mining_paid_metadata'
branch_labels = depends_on = None
TABLES = ('mining_request_manifests','mining_request_tombstones')
HASHES = ('operation_hash','receipt_hash','root_request_tag','request_sha','context_sha',
    'prompt_sha','prompt_file_sha','schema_sha','schema_file_sha','profile_sha')
CONFIG = ('config_version','prompt_version','schema_version','provider','model',
    'expected_version','version_policy','endpoint','region','deployment','mode','structured_mode')


def namespace():
    conn = op.get_bind()
    return conn,conn.dialect.identifier_preparer.quote_identifier(conn.scalar(sa.text('SELECT current_schema()')))


def upgrade():
    conn,q = namespace()
    # Maintenance only; no waiting for business/Funding lock chains.
    op.execute('LOCK TABLE '+','.join(f'{q}.{n}' for n in (
        'experience_sessions','ai_mining_runs','mining_paid_plans'))+' IN ACCESS EXCLUSIVE MODE NOWAIT')
    op.create_table(TABLES[0],
        sa.Column('run_id',sa.Uuid(),sa.ForeignKey('ai_mining_runs.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('root_run_id',sa.Uuid(),nullable=False,unique=True),
        sa.Column('session_id',sa.Uuid(),sa.ForeignKey('experience_sessions.id',ondelete='CASCADE'),nullable=False),
        *[sa.Column(n,sa.Integer(),nullable=False) for n in ('context_revision','contract_version','manifest_version','output_cap')],
        *[sa.Column(n,sa.String(64),nullable=False,unique=n=='operation_hash') for n in HASHES],
        *[sa.Column(n,sa.String(256 if n=='endpoint' else 64),nullable=False) for n in CONFIG],
        sa.Column('storage_state',sa.String(24),nullable=False,server_default='metadata_only'),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint('manifest_version=1 AND contract_version=1 AND context_revision>=0 AND output_cap=1200',name='ck_mrm_versions'),
        sa.CheckConstraint(' AND '.join(f"{n} ~ '^[a-f0-9]{{64}}$'" for n in HASHES),name='ck_mrm_hashes'),
        sa.CheckConstraint("storage_state='metadata_only'",name='ck_mrm_inert'),
        sa.CheckConstraint('expires_at>created_at',name='ck_mrm_expiry'),
        sa.CheckConstraint("provider='deepseek_official' AND model='deepseek-flash' AND endpoint='https://api.deepseek.com/chat/completions' AND mode='non_thinking' AND structured_mode='json_object'",name='ck_mrm_target'))
    op.create_table(TABLES[1],
        sa.Column('root_digest',sa.String(64),primary_key=True),
        sa.Column('operation_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('request_sha',sa.String(64),nullable=False),
        sa.Column('erased_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("root_digest ~ '^[a-f0-9]{64}$' AND operation_hash ~ '^[a-f0-9]{64}$' AND request_sha ~ '^[a-f0-9]{64}$'",name='ck_mrt_hashes'),
        sa.CheckConstraint("expires_at=erased_at+interval '24 hours'",name='ck_mrt_expiry'))
    op.execute(f'''CREATE FUNCTION {q}.request_manifest_guard() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
      DECLARE s {q}.experience_sessions%ROWTYPE; r {q}.ai_mining_runs%ROWTYPE;
        p {q}.mining_paid_plans%ROWTYPE; t timestamptz;
      BEGIN
        IF TG_OP='TRUNCATE' THEN RAISE EXCEPTION 'manifest_immutable'; END IF;
        IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'manifest_immutable'; END IF;
        IF TG_OP='DELETE' THEN
          IF EXISTS(SELECT 1 FROM {q}.ai_mining_runs WHERE id=OLD.run_id)
            AND EXISTS(SELECT 1 FROM {q}.experience_sessions WHERE id=OLD.session_id)
            THEN RAISE EXCEPTION 'manifest_immutable'; END IF;
          t:=clock_timestamp();
          INSERT INTO {q}.mining_request_tombstones VALUES(
            encode(sha256(convert_to(OLD.root_run_id::text,'UTF8')),'hex'),
            OLD.operation_hash,OLD.request_sha,t,t+interval '24 hours');
          RETURN OLD;
        END IF;
        -- Never acquire Funding: Session -> Run -> Manifest only. No paid_* writes.
        SELECT * INTO s FROM {q}.experience_sessions WHERE id=NEW.session_id FOR UPDATE;
        SELECT * INTO r FROM {q}.ai_mining_runs WHERE id=NEW.run_id FOR KEY SHARE;
        SELECT * INTO p FROM {q}.mining_paid_plans WHERE run_id=NEW.run_id;
        IF s.id IS NULL OR s.status<>'active' OR s.mining_status<>'active'
          OR r.id IS NULL OR r.session_id<>s.id OR r.state<>'running'
          OR r.lease_until<=clock_timestamp() OR s.context_revision<>r.reserved_revision
          OR NEW.context_revision<>r.reserved_revision THEN RAISE EXCEPTION 'manifest_business_inactive'; END IF;
        IF p.run_id IS NULL OR (NEW.root_run_id,NEW.operation_hash,NEW.receipt_hash,
            NEW.request_sha,NEW.context_sha,NEW.prompt_sha,NEW.schema_sha,NEW.config_version,
            NEW.prompt_version,NEW.schema_version,NEW.provider,NEW.model)
          IS DISTINCT FROM (p.root_run_id,p.operation_hash,p.receipt_hash,p.request_sha,
            p.context_sha,p.prompt_sha,p.schema_sha,p.config_version,p.prompt_version,
            p.schema_version,p.provider,p.model)
          OR p.session_id<>s.id OR NOT EXISTS(SELECT 1 FROM {q}.ai_mining_receipts
            WHERE run_id=NEW.root_run_id AND session_id=s.id AND state='live'
              AND expires_at>clock_timestamp() AND key_digest=NEW.receipt_hash
              AND request_tag=NEW.root_request_tag)
          THEN RAISE EXCEPTION 'manifest_plan_mismatch'; END IF;
        IF EXISTS(SELECT 1 FROM {q}.mining_request_tombstones
          WHERE root_digest=encode(sha256(convert_to(NEW.root_run_id::text,'UTF8')),'hex')
            OR operation_hash=NEW.operation_hash) THEN RAISE EXCEPTION 'manifest_erased'; END IF;
        NEW.created_at:=clock_timestamp();
        NEW.expires_at:=r.lease_until;
        RETURN NEW;
      END $$''')
    op.execute(f'''CREATE FUNCTION {q}.request_manifest_tombstone_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog AS $$
      BEGIN
        IF TG_OP='INSERT' AND pg_trigger_depth()>1 THEN RETURN NEW; END IF;
        IF TG_OP='DELETE' AND OLD.expires_at<=clock_timestamp() THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'manifest_tombstone_immutable';
      END $$''')
    op.execute(f'CREATE TRIGGER request_manifest_guard BEFORE INSERT OR UPDATE OR DELETE ON {q}.{TABLES[0]} FOR EACH ROW EXECUTE FUNCTION {q}.request_manifest_guard()')
    op.execute(f'CREATE TRIGGER request_manifest_truncate BEFORE TRUNCATE ON {q}.{TABLES[0]} FOR EACH STATEMENT EXECUTE FUNCTION {q}.request_manifest_guard()')
    op.execute(f'CREATE TRIGGER request_manifest_tombstone_guard BEFORE INSERT OR UPDATE OR DELETE ON {q}.{TABLES[1]} FOR EACH ROW EXECUTE FUNCTION {q}.request_manifest_tombstone_guard()')
    op.execute(f'CREATE TRIGGER request_manifest_tombstone_truncate BEFORE TRUNCATE ON {q}.{TABLES[1]} FOR EACH STATEMENT EXECUTE FUNCTION {q}.request_manifest_tombstone_guard()')
    # Strip even inherited default grants. Roles/Broker deployment is NOT approved.
    quote=conn.dialect.identifier_preparer.quote_identifier
    for kind,targets,catalog,acl,owner,default in (
        ('TABLE',TABLES,'pg_class','relacl','relowner','r'),
        ('FUNCTION',('request_manifest_guard()','request_manifest_tombstone_guard()'),'pg_proc','proacl','proowner','f')):
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
    conn,q=namespace()
    op.execute('LOCK TABLE '+','.join(f'{q}.{n}' for n in (
        'experience_sessions','ai_mining_runs',*TABLES))+' IN ACCESS EXCLUSIVE MODE NOWAIT')
    if any(conn.scalar(sa.text(f'SELECT EXISTS(SELECT 1 FROM {q}.{t})')) for t in TABLES):
        raise RuntimeError('manifest_nonempty_downgrade_blocked')
    for trigger,table in (('request_manifest_guard',TABLES[0]),('request_manifest_truncate',TABLES[0]),
        ('request_manifest_tombstone_guard',TABLES[1]),('request_manifest_tombstone_truncate',TABLES[1])):
        op.execute(f'DROP TRIGGER {trigger} ON {q}.{table}')
    for fn in ('request_manifest_guard()','request_manifest_tombstone_guard()'):
        op.execute(f'DROP FUNCTION {q}.{fn}')
    for table in reversed(TABLES): op.drop_table(table)
