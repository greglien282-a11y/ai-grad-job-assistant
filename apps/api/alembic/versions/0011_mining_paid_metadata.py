"""Inert mining/paid metadata candidate: no grants, budget, runtime or dispatch."""
from alembic import op
import sqlalchemy as sa

revision = '0011_mining_paid_metadata'
down_revision = '0010_response_diagnostics'
branch_labels = depends_on = None
TABLES = ('mining_paid_identities','mining_paid_limits','mining_paid_plans','mining_paid_bindings')
HASHES = ('operation_hash','receipt_hash','request_sha','policy_sha','context_sha','prompt_sha','schema_sha','account_sha')
VERSIONS = ('config_version','prompt_version','schema_version')


def common(prefix):
    return [sa.Column('root_run_id',sa.Uuid(),nullable=False,unique=True),
        sa.Column('ledger_id',sa.Uuid(),sa.ForeignKey('paid_funding.ledger_id',ondelete='RESTRICT'),nullable=False),
        sa.Column('grant_id',sa.Uuid(),sa.ForeignKey('paid_grants.id',ondelete='RESTRICT'),nullable=False),
        *[sa.Column(n,sa.String(64),nullable=False,unique=n=='operation_hash') for n in HASHES],
        sa.Column('provider',sa.String(32),nullable=False),sa.Column('model',sa.String(64),nullable=False),
        *[sa.Column(n,sa.String(64),nullable=False) for n in VERSIONS],
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint(' AND '.join(f"{n} ~ '^[a-f0-9]{{64}}$'" for n in HASHES),name=f'ck_{prefix}_hashes'),
        sa.CheckConstraint("provider='deepseek_official' AND model='deepseek-flash'",name=f'ck_{prefix}_model'),
        sa.CheckConstraint(' AND '.join(f'length({n}) BETWEEN 1 AND 64' for n in VERSIONS),name=f'ck_{prefix}_versions')]


def namespace():
    conn=op.get_bind()
    return conn,conn.dialect.identifier_preparer.quote_identifier(conn.scalar(sa.text('SELECT current_schema()')))


def upgrade():
    conn,q=namespace()
    # Maintenance candidate only: acquire all existing FK/trigger targets
    # without waiting, before any DDL. Busy deployments must stop and review.
    op.execute('LOCK TABLE '+','.join(f'{q}.{n}' for n in (
        'experience_sessions','ai_mining_runs','paid_funding','paid_grants','paid_calls'))+
        ' IN ACCESS EXCLUSIVE MODE NOWAIT')
    op.create_table(TABLES[0],
        sa.Column('session_id',sa.Uuid(),sa.ForeignKey('experience_sessions.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('actor_scope',sa.String(64),nullable=False),sa.Column('session_scope',sa.String(64),nullable=False,unique=True),
        sa.Column('issuer_version',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint("actor_scope ~ '^[a-f0-9]{64}$' AND session_scope ~ '^[a-f0-9]{64}$'",name='ck_mpi_scopes'),
        sa.CheckConstraint('length(issuer_version) BETWEEN 1 AND 64',name='ck_mpi_issuer'))
    op.create_table(TABLES[1],
        sa.Column('ledger_id',sa.Uuid(),sa.ForeignKey('paid_funding.ledger_id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('kind',sa.String(16),primary_key=True),sa.Column('scope',sa.String(64),primary_key=True),
        sa.Column('currency',sa.String(3),nullable=False,server_default='CNY'),
        sa.Column('ceiling',sa.Numeric(20,6),nullable=False,server_default='0'),
        sa.Column('calls_limit',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('concurrent_limit',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('evidence_sha',sa.String(64),nullable=False),
        sa.CheckConstraint("kind IN ('user','session') AND currency='CNY'",name='ck_mpl_scope'),
        sa.CheckConstraint("scope ~ '^[a-f0-9]{64}$' AND evidence_sha ~ '^[a-f0-9]{64}$'",name='ck_mpl_hashes'),
        sa.CheckConstraint('ceiling>=0 AND calls_limit>=0 AND concurrent_limit>=0',name='ck_mpl_limits'))
    op.create_table(TABLES[2],
        sa.Column('run_id',sa.Uuid(),sa.ForeignKey('ai_mining_runs.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('session_id',sa.Uuid(),sa.ForeignKey('mining_paid_identities.session_id',ondelete='CASCADE'),nullable=False),*common('mpp'))
    op.create_table(TABLES[3],sa.Column('run_id',sa.Uuid(),primary_key=True),
        sa.Column('call_id',sa.Uuid(),sa.ForeignKey('paid_calls.id',ondelete='RESTRICT'),nullable=False,unique=True),
        sa.Column('contract_version',sa.Integer(),nullable=False,server_default='1'),
        sa.Column('actor_scope',sa.String(64),nullable=False),sa.Column('session_scope',sa.String(64),nullable=False),
        sa.Column('binding_state',sa.String(16),nullable=False,server_default='bound'),
        sa.Column('tombstoned_at',sa.DateTime(timezone=True)),*common('mpb'),
        sa.CheckConstraint('contract_version=1',name='ck_mpb_version'),
        sa.CheckConstraint("actor_scope ~ '^[a-f0-9]{64}$' AND session_scope ~ '^[a-f0-9]{64}$'",name='ck_mpb_scopes'),
        sa.CheckConstraint("(binding_state='bound' AND tombstoned_at IS NULL) OR (binding_state='tombstoned' AND tombstoned_at IS NOT NULL AND tombstoned_at>=created_at)",name='ck_mpb_tombstone'))
    # NO reserve/permit/runtime function. These guards can only reject metadata
    # or preserve tombstones. They never write any original paid_* table.
    op.execute(f'''CREATE FUNCTION {q}.mining_paid_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    DECLARE p {q}.mining_paid_plans%ROWTYPE; c {q}.paid_calls%ROWTYPE;
      i {q}.mining_paid_identities%ROWTYPE; r {q}.ai_mining_runs%ROWTYPE; l uuid;
    BEGIN
      IF TG_OP<>'INSERT' THEN
        IF TG_OP='DELETE' THEN
          IF TG_TABLE_NAME='mining_paid_identities' THEN
            IF NOT EXISTS(SELECT 1 FROM {q}.experience_sessions WHERE id=OLD.session_id) THEN RETURN OLD; END IF;
          ELSIF TG_TABLE_NAME='mining_paid_plans' THEN
            IF NOT EXISTS(SELECT 1 FROM {q}.ai_mining_runs WHERE id=OLD.run_id)
              OR NOT EXISTS(SELECT 1 FROM {q}.experience_sessions WHERE id=OLD.session_id) THEN RETURN OLD; END IF;
          END IF;
        END IF;
        IF TG_TABLE_NAME='mining_paid_bindings' THEN
         IF TG_OP='UPDATE' AND OLD.binding_state='bound'
          AND NEW.binding_state='tombstoned' AND NEW.tombstoned_at IS NOT NULL
          AND (to_jsonb(NEW)-'binding_state'-'tombstoned_at')=(to_jsonb(OLD)-'binding_state'-'tombstoned_at')
          AND NOT EXISTS(SELECT 1 FROM {q}.ai_mining_runs WHERE id=OLD.run_id) THEN RETURN NEW; END IF;
        END IF;
        RAISE EXCEPTION 'mining_paid_immutable';
      END IF;
      SELECT ledger_id INTO l FROM {q}.paid_funding WHERE id=1 FOR UPDATE;
      IF l IS DISTINCT FROM NEW.ledger_id THEN RAISE EXCEPTION 'mining_paid_ledger_mismatch'; END IF;
      IF EXISTS(SELECT 1 FROM {q}.controlled_probe) THEN RAISE EXCEPTION 'mining_paid_experimental_ledger_blocked'; END IF;
      IF TG_TABLE_NAME='mining_paid_plans' THEN
        PERFORM 1 FROM {q}.experience_sessions WHERE id=NEW.session_id FOR UPDATE;
        SELECT * INTO r FROM {q}.ai_mining_runs WHERE id=NEW.run_id FOR KEY SHARE;
        IF r.id IS NULL OR r.session_id<>NEW.session_id OR NOT EXISTS(
          WITH RECURSIVE chain AS (
            SELECT id,session_id,retry_of FROM {q}.ai_mining_runs WHERE id=NEW.run_id
            UNION SELECT a.id,a.session_id,a.retry_of FROM {q}.ai_mining_runs a JOIN chain x ON a.id=x.retry_of
          ) SELECT 1 FROM chain WHERE id=NEW.root_run_id AND session_id=NEW.session_id AND retry_of IS NULL
            AND NOT EXISTS(SELECT 1 FROM chain bad WHERE bad.session_id<>NEW.session_id)
        ) THEN RAISE EXCEPTION 'mining_paid_run_mismatch'; END IF;
        IF NOT EXISTS(SELECT 1 FROM {q}.ai_mining_receipts WHERE run_id=NEW.root_run_id
          AND session_id=NEW.session_id AND key_digest=NEW.receipt_hash)
          THEN RAISE EXCEPTION 'mining_paid_receipt_mismatch'; END IF;
        IF NOT EXISTS(SELECT 1 FROM {q}.paid_grants g WHERE g.id=NEW.grant_id AND g.policy_hash=NEW.policy_sha
          AND g.policy->>'provider'=NEW.provider AND g.policy->>'model'=NEW.model
          AND encode(sha256(convert_to(g.policy->>'account_ref','UTF8')),'hex')=NEW.account_sha)
          THEN RAISE EXCEPTION 'mining_paid_grant_mismatch'; END IF;
        NEW.created_at:=clock_timestamp();
        RETURN NEW;
      END IF;
      SELECT * INTO p FROM {q}.mining_paid_plans WHERE run_id=NEW.run_id;
      PERFORM 1 FROM {q}.experience_sessions WHERE id=p.session_id FOR UPDATE;
      SELECT * INTO r FROM {q}.ai_mining_runs WHERE id=NEW.run_id FOR KEY SHARE;
      IF r.id IS NULL THEN RAISE EXCEPTION 'mining_paid_run_mismatch'; END IF;
      SELECT * INTO i FROM {q}.mining_paid_identities WHERE session_id=p.session_id;
      SELECT * INTO c FROM {q}.paid_calls WHERE id=NEW.call_id;
      IF p.run_id IS NULL OR i.session_id IS NULL OR c.id IS NULL OR NEW.binding_state<>'bound' OR NEW.tombstoned_at IS NOT NULL
        OR (to_jsonb(NEW)-'call_id'-'contract_version'-'actor_scope'-'session_scope'-'binding_state'-'tombstoned_at'-'created_at')
           IS DISTINCT FROM (to_jsonb(p)-'session_id'-'created_at')
        OR (NEW.actor_scope,NEW.session_scope) IS DISTINCT FROM (i.actor_scope,i.session_scope)
        OR (NEW.grant_id,NEW.operation_hash,NEW.request_sha,NEW.policy_sha,NEW.provider,NEW.model)
           IS DISTINCT FROM (c.grant_id,c.operation_hash,c.request_hash,c.policy_hash,c.provider,c.model)
        THEN RAISE EXCEPTION 'mining_paid_binding_mismatch'; END IF;
      IF EXISTS(SELECT 1 FROM {q}.paid_calls pc WHERE pc.id<>NEW.call_id AND NOT EXISTS(
          SELECT 1 FROM {q}.mining_paid_bindings b WHERE b.call_id=pc.id))
        THEN RAISE EXCEPTION 'mining_paid_unattributed_call'; END IF;
      NEW.created_at:=clock_timestamp();
      RETURN NEW;
    END $$''')
    for table in (TABLES[0],TABLES[2]):
        op.execute(f'CREATE TRIGGER mining_paid_immutable BEFORE UPDATE OR DELETE ON {q}.{table} FOR EACH ROW EXECUTE FUNCTION {q}.mining_paid_guard()')
    op.execute(f'CREATE TRIGGER mining_paid_plan_check BEFORE INSERT ON {q}.{TABLES[2]} FOR EACH ROW EXECUTE FUNCTION {q}.mining_paid_guard()')
    op.execute(f'CREATE TRIGGER mining_paid_binding_check BEFORE INSERT OR UPDATE OR DELETE ON {q}.{TABLES[3]} FOR EACH ROW EXECUTE FUNCTION {q}.mining_paid_guard()')
    op.execute(f'''CREATE FUNCTION {q}.mining_paid_erasure() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
      UPDATE {q}.mining_paid_bindings SET binding_state='tombstoned',tombstoned_at=clock_timestamp()
        WHERE run_id=OLD.id AND binding_state='bound';
      RETURN OLD;
    END $$''')
    op.execute(f'''CREATE FUNCTION {q}.mining_paid_audit_ok(ledger uuid) RETURNS boolean LANGUAGE sql
      STABLE SET search_path=pg_catalog AS $$
      SELECT EXISTS(SELECT 1 FROM {q}.paid_funding WHERE id=1 AND ledger_id=ledger)
        AND NOT EXISTS(SELECT 1 FROM {q}.controlled_probe)
        AND NOT EXISTS(SELECT 1 FROM {q}.paid_calls c WHERE NOT EXISTS(SELECT 1 FROM {q}.mining_paid_bindings b WHERE b.call_id=c.id))
    $$''')
    # NOWAIT makes concurrent writers a deployment stop, not a lock-order gamble.
    op.execute(f'LOCK TABLE {q}.ai_mining_runs IN SHARE ROW EXCLUSIVE MODE NOWAIT')
    op.execute(f'CREATE TRIGGER mining_paid_erasure AFTER DELETE ON {q}.ai_mining_runs FOR EACH ROW EXECUTE FUNCTION {q}.mining_paid_erasure()')
    # Strip inherited ALTER DEFAULT PRIVILEGES as well as PUBLIC defaults.
    # No LOGIN, membership, runtime grants or funding rows are created/changed.
    quote=conn.dialect.identifier_preparer.quote_identifier
    for table in TABLES:
        rows=conn.execute(sa.text('''SELECT DISTINCT a.grantee FROM pg_class c CROSS JOIN LATERAL
          aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a WHERE c.oid=CAST(:target AS regclass) AND a.grantee<>c.relowner'''),
          dict(target=f'{q}.{table}')).scalars().all()
        op.execute(f'REVOKE ALL ON TABLE {q}.{table} FROM PUBLIC')
        for oid in rows:
            if oid: op.execute(f'REVOKE ALL ON TABLE {q}.{table} FROM {quote(conn.scalar(sa.text("SELECT rolname FROM pg_roles WHERE oid=:oid"),dict(oid=oid)))}')
    for signature in ('mining_paid_guard()','mining_paid_erasure()','mining_paid_audit_ok(uuid)'):
        rows=conn.execute(sa.text('''SELECT DISTINCT a.grantee FROM pg_proc p CROSS JOIN LATERAL
          aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=CAST(:target AS regprocedure) AND a.grantee<>p.proowner'''),
          dict(target=f'{q}.{signature}')).scalars().all()
        op.execute(f'REVOKE ALL ON FUNCTION {q}.{signature} FROM PUBLIC')
        for oid in rows:
            if oid: op.execute(f'REVOKE ALL ON FUNCTION {q}.{signature} FROM {quote(conn.scalar(sa.text("SELECT rolname FROM pg_roles WHERE oid=:oid"),dict(oid=oid)))}')


def downgrade():
    conn,q=namespace()
    # Quiescent maintenance only. Fail immediately if any conflicting lock is
    # held; transactional DDL rollback preserves the whole candidate on failure.
    names=['experience_sessions','ai_mining_runs','paid_funding',*TABLES]
    op.execute('LOCK TABLE '+','.join(f'{q}.{n}' for n in names)+' IN ACCESS EXCLUSIVE MODE NOWAIT')
    if any(conn.scalar(sa.text(f'SELECT EXISTS(SELECT 1 FROM {q}.{t})')) for t in TABLES):
        raise RuntimeError('mining_paid_nonempty_downgrade_blocked')
    op.execute(f'DROP TRIGGER mining_paid_erasure ON {q}.ai_mining_runs')
    for fn in ('mining_paid_erasure()','mining_paid_guard()','mining_paid_audit_ok(uuid)'):
        # Guard still has dependent triggers; drop those explicitly, never CASCADE.
        if fn=='mining_paid_guard()':
            for trigger,table in [('mining_paid_immutable',TABLES[0]),('mining_paid_immutable',TABLES[2]),('mining_paid_plan_check',TABLES[2]),('mining_paid_binding_check',TABLES[3])]:
                op.execute(f'DROP TRIGGER {trigger} ON {q}.{table}')
        op.execute(f'DROP FUNCTION {q}.{fn}')
    for table in reversed(TABLES): op.drop_table(table)
