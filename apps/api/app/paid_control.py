"""C-1A administrative ledger, deliberately disconnected from HTTP dispatch.

The owner/migrator connection is NEVER a business-process credential. Runtime
uses only the schema-qualified SECURITY DEFINER function installed by 0008.
No environment/secret resolution, real tokenizer claim, or funding defaults.
"""
from datetime import datetime
from decimal import Decimal
import re
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import select, text

from app.cost_ledger import canonical, digest, money, tag
from app.deepseek_contract import (Frozen, PriceSnapshot, FxSnapshot, ENDPOINT,
                                   MODEL, VERSION, REGION, ProbeError, SyntheticRequest, synthetic_requests)
from app.models import utcnow
from app.paid_models import PaidFunding, PaidScope, PaidGrant, PaidCall, PaidAudit


class TokenCertificate(Frozen):
    request_sha: str = Field(pattern=r'^[a-f0-9]{64}$')
    input_bound: int = Field(strict=True, gt=0, le=12000)
    evidence_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    # An owner attestation is necessary but does not prove supplier behavior.
    kind: str = 'unverified'
    tokenizer_version: str = Field(min_length=1, max_length=100)
    covers_full_request_and_framing: bool = False
    expires_at: AwareDatetime


class PaidPolicy(Frozen):
    provider: str = 'deepseek_official'
    account_ref: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    secret_ref_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    endpoint: str = ENDPOINT
    model: str = MODEL
    expected_version: str = VERSION
    region: str = REGION
    mode: str = 'chat_non_thinking_json_object'
    output_cap: int = Field(strict=True, gt=0, le=1200)
    price: PriceSnapshot
    price_starts_at: AwareDatetime
    price_currency: str = 'USD'
    price_model: str = MODEL
    price_account_ref: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    calendar_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    cache_rule_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    fx: FxSnapshot
    fx_starts_at: AwareDatetime
    fx_approval_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    certificates: tuple[TokenCertificate, ...] = Field(min_length=1, max_length=24)

    def check(self, now):
        if (self.provider, self.endpoint, self.model, self.expected_version, self.region, self.mode) != (
                'deepseek_official', ENDPOINT, MODEL, VERSION, REGION, 'chat_non_thinking_json_object'):
            raise ProbeError('paid_profile_not_allowlisted')
        if self.price_currency != 'USD' or self.price_model != self.model or self.price_account_ref != self.account_ref:
            raise ProbeError('paid_price_binding_invalid')
        if not self.price_starts_at <= now < self.price.expires_at or not self.fx_starts_at <= now < self.fx.expires_at:
            raise ProbeError('paid_rate_expired')
        allowed = {r.fingerprint for r in synthetic_requests(self.output_cap)}
        hashes = [c.request_sha for c in self.certificates]
        if len(set(hashes)) != len(hashes) or not set(hashes) <= allowed:
            raise ProbeError('paid_synthetic_manifest_required')
        # No shipped certificate satisfies this gate. Only separately reviewed
        # owner evidence may attest a full-request bound; fixtures are not proof.
        if any(c.kind != 'owner_attested_full_request_bound' or not c.covers_full_request_and_framing
               or c.expires_at <= now for c in self.certificates):
            raise ProbeError('paid_token_bound_unproven')


def evidence(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ProbeError('paid_evidence_digest_required')
    return value


def approved_limit(value):
    """Never round an owner's ceiling upward or accept binary float inputs."""
    if not isinstance(value, (Decimal, str)):
        raise ProbeError('paid_decimal_required')
    rounded = money(value)
    if Decimal(value) != rounded:
        raise ProbeError('paid_limit_precision_invalid')
    return rounded


class PaidAdmin:
    """Offline owner operations. Do NOT install this factory in the web app."""
    def __init__(self, factory): self.factory = factory

    def _pool(self, db):
        pool = db.scalar(select(PaidFunding).where(PaidFunding.id == 1).with_for_update())
        if pool is None: raise ProbeError('paid_pool_missing')
        return pool

    def _audit(self, db, action, proof, **detail):
        db.add(PaidAudit(action=action, evidence_digest=evidence(proof), detail=detail))

    def approve_total(self, amount, proof):
        amount = approved_limit(amount)
        with self.factory.begin() as db:
            pool = self._pool(db)
            if amount < pool.ceiling: raise ProbeError('paid_total_cannot_decrease')
            self._audit(db, 'approve_total', proof, old=str(pool.ceiling), new=str(amount))
            pool.ceiling = amount; pool.approval_digest = proof

    def approve_scope(self, kind, key, amount, proof):
        if kind not in ('provider', 'model'): raise ProbeError('paid_scope_invalid')
        tag(key); amount = approved_limit(amount)
        with self.factory.begin() as db:
            pool = self._pool(db)
            if amount > pool.ceiling: raise ProbeError('paid_scope_exceeds_total')
            row = db.get(PaidScope, (kind, key))
            if row is None: db.add(PaidScope(kind=kind, key=key, ceiling=amount, approval_digest=evidence(proof)))
            else: row.ceiling = amount; row.approval_digest = evidence(proof)
            self._audit(db, 'approve_scope', proof, kind=kind, key=key, ceiling=str(amount))

    def authorize(self, policy: PaidPolicy, approver, proof, starts_at, expires_at, ceiling, call_limit, calls_limit):
        if type(policy) is not PaidPolicy: raise ProbeError('paid_policy_required')
        tag(approver); evidence(proof); policy.check(utcnow())
        if not isinstance(starts_at, datetime) or not isinstance(expires_at, datetime) or not starts_at.tzinfo or not expires_at.tzinfo:
            raise ProbeError('paid_aware_window_required')
        if not starts_at < expires_at or type(calls_limit) is not int or calls_limit <= 0:
            raise ProbeError('paid_grant_limits_invalid')
        ceiling, call_limit = approved_limit(ceiling), approved_limit(call_limit)
        snapshot = policy.model_dump(mode='json')
        with self.factory.begin() as db:
            pool = self._pool(db)
            if ceiling > pool.ceiling or call_limit > ceiling: raise ProbeError('paid_grant_exceeds_total')
            for kind, key in [('provider', policy.provider), ('model', policy.model)]:
                scope = db.get(PaidScope, (kind, key))
                if scope is None or ceiling > scope.ceiling: raise ProbeError('paid_scope_unapproved')
            row = PaidGrant(pool_id=1, approver=approver, approval_digest=proof, starts_at=starts_at,
                            expires_at=expires_at, revoked=False, ceiling=ceiling, call_limit=call_limit,
                            calls_limit=calls_limit, policy_hash=digest(canonical(snapshot)), policy=snapshot)
            db.add(row); db.flush()
            self._audit(db, 'authorize', proof, grant_id=str(row.id), policy_hash=row.policy_hash)
            return row.id

    def revoke(self, grant_id, proof):
        with self.factory.begin() as db:
            self._pool(db)
            row = db.get(PaidGrant, grant_id)
            if row is None: raise ProbeError('paid_grant_missing')
            row.revoked = True
            self._audit(db, 'revoke', proof, grant_id=str(grant_id))

    def reconcile(self, call_id, usd, invoice_digest, review_digest):
        # Original USD is never rounded down into the CNY reserve. Invoice
        # identifiers are GLOBAL to the ledger, not scoped by batch/account.
        if not isinstance(usd, (Decimal, str)):
            raise ProbeError('paid_decimal_required')
        usd = Decimal(usd)
        if not usd.is_finite() or usd < 0 or usd != usd.quantize(Decimal('0.000000000001')) or usd >= Decimal('1e12'):
            raise ProbeError('paid_invoice_amount_invalid')
        evidence(invoice_digest); evidence(review_digest)
        with self.factory.begin() as db:
            pool = self._pool(db); row = db.get(PaidCall, call_id)
            if row is None: raise ProbeError('paid_call_missing')
            if row.state == 'reconciled':
                if row.invoice_hash != invoice_digest or row.actual_usd != usd: raise ProbeError('paid_invoice_conflict')
                return False
            if row.state not in ('sent', 'response_received', 'unknown'): raise ProbeError('paid_transition_invalid')
            if db.scalar(select(PaidCall.id).where(PaidCall.invoice_hash == invoice_digest)):
                raise ProbeError('paid_invoice_already_used')
            grant = db.get(PaidGrant, row.grant_id)
            fx = Decimal(grant.policy['fx']['cny_per_usd'])
            actual = money(usd * fx)
            row.actual_usd = usd; row.actual = actual; row.invoice_hash = invoice_digest; row.state = 'reconciled'
            pool.held -= row.reserved; pool.spent += actual
            # Any reserve overrun freezes the entire pool, including other grants.
            if actual > row.reserved or pool.spent + pool.held > pool.ceiling: pool.frozen = True
            self._audit(db, 'reconcile', review_digest, call_id=str(call_id), usd=str(usd), cny=str(actual), invoice=invoice_digest)
            return True

    def unfreeze(self, proof):
        with self.factory.begin() as db:
            pool = self._pool(db)
            if db.scalar(select(PaidCall.id).where(PaidCall.actual.is_(None)).limit(1)) or pool.spent > pool.ceiling:
                raise ProbeError('paid_review_unresolved')
            # Scope overruns also require explicit approved scope correction.
            for scope in db.scalars(select(PaidScope)):
                col = PaidCall.provider if scope.kind == 'provider' else PaidCall.model
                used = sum((c.actual or Decimal(0)) for c in db.scalars(select(PaidCall).where(col == scope.key)))
                if used > scope.ceiling: raise ProbeError('paid_review_unresolved')
            pool.frozen = False; self._audit(db, 'unfreeze', proof)

    def close_unsent(self, call_id, proof):
        """Owner-only release, with durable evidence no send permit was issued."""
        with self.factory.begin() as db:
            pool = self._pool(db); row = db.get(PaidCall, call_id)
            if row is None or row.state != 'reserved' or row.lease_until > utcnow():
                raise ProbeError('paid_not_provably_unsent')
            row.state = 'reconciled'; row.actual = 0; row.actual_usd = 0
            row.invoice_hash = digest('unsent:' + str(row.id)); pool.held -= row.reserved
            self._audit(db, 'close_unsent', proof, call_id=str(call_id))

    def provision_runtime_role(self, schema, role):
        """Explicit DBA provisioning of an existing restricted role; no secrets.

        No role creation; never called by migrations or application startup.
        Role must not inherit the owner, create databases/roles or this schema.
        """
        for value in (schema, role):
            if not re.fullmatch('[a-z][a-z0-9_]{0,62}', value): raise ProbeError('paid_identifier_invalid')
        with self.factory.begin() as db:
            restricted = db.scalar(text('''SELECT NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolbypassrls
                OR pg_has_role(r.oid,(SELECT oid FROM pg_roles WHERE rolname=current_user),'MEMBER')
                OR has_database_privilege(r.oid,current_database(),'CREATE')
                OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_temp_%'
                    AND has_schema_privilege(r.oid,n.oid,'CREATE'))
                OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname=:schema AND c.relname IN ('paid_funding','paid_scopes','paid_grants','paid_calls','paid_audit')
                    AND has_table_privilege(r.oid,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')))
                FROM pg_roles r WHERE rolname=:role'''), {'role':role, 'schema':schema})
            if restricted is not True: raise ProbeError('paid_runtime_role_not_restricted')
            db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            for table in ('paid_funding','paid_scopes','paid_grants','paid_calls','paid_audit'):
                db.execute(text(f'GRANT SELECT ON "{schema}".{table} TO "{role}"'))
            db.execute(text(f'GRANT EXECUTE ON FUNCTION "{schema}".paid_runtime(text,text,jsonb) TO "{role}"'))


class PaidControl:
    """Runtime's only mutation path. Fixed schema + deployment ledger UUID.

    No namespace parameter; caller cannot create funding or authorizations.
    The process role only gets SELECT plus EXECUTE on paid_runtime().
    """
    def __init__(self, engine, schema, ledger_id):
        if not re.fullmatch('[a-z][a-z0-9_]{0,62}', schema): raise ProbeError('paid_schema_invalid')
        self.engine, self.schema, self.ledger_id = engine, schema, str(UUID(str(ledger_id)))

    def _invoke(self, action, payload):
        # All calls bind values; schema is validated then quoted, never supplied
        # by an HTTP caller. No automatic DB/HTTP retry loop.
        with self.engine.begin() as conn:
            return conn.scalar(text(f'SELECT "{self.schema}".paid_runtime(:ledger, :action, CAST(:payload AS jsonb))'),
                               dict(ledger=self.ledger_id, action=action, payload=canonical(payload)))

    def reserve(self, grant_id, request, operation, batch_tag, policy_hash):
        if type(request) is not SyntheticRequest: raise ProbeError('paid_synthetic_request_required')
        import json
        try: cap = json.loads(request.body)['max_tokens']
        except Exception: raise ProbeError('paid_synthetic_request_required') from None
        if request.fingerprint not in {r.fingerprint for r in synthetic_requests(cap)}:
            raise ProbeError('paid_synthetic_request_required')
        if not isinstance(operation, str) or not 1 <= len(operation) <= 128: raise ProbeError('paid_operation_invalid')
        tag(batch_tag); evidence(policy_hash)
        return self._invoke('reserve', dict(id=str(uuid4()), grant=str(grant_id), operation=digest(operation),
                            request=request.fingerprint, batch=batch_tag, policy=policy_hash))

    def transition(self, call_id, action, request_sha=None, policy_hash=None, usage=None):
        if action not in ('permit', 'received', 'unknown'): raise ProbeError('paid_action_invalid')
        return self._invoke(action, dict(id=str(call_id), request=request_sha, policy=policy_hash, usage=usage))

    def recover(self): return self._invoke('recover', {})

    def get(self, call_id):
        with self.engine.connect() as conn:
            actual_id = conn.scalar(text(f'SELECT ledger_id FROM "{self.schema}".paid_funding WHERE id=1'))
            if str(actual_id) != self.ledger_id: raise ProbeError('paid_ledger_identity_mismatch')
            # Read-only recovery, no function/maintenance/send side effects.
            return dict(conn.execute(text(f'''SELECT id, state AS persisted_state,
                CASE WHEN state='sent' AND lease_until<=clock_timestamp() THEN 'unknown' ELSE state END AS state,
                reserved, actual, actual_usd, usage FROM "{self.schema}".paid_calls WHERE id=:id'''), {'id':call_id}).mappings().one())

    def totals(self):
        """Read-only CNY holds/actuals and original USD, grouped independently."""
        with self.engine.connect() as conn:
            if str(conn.scalar(text(f'SELECT ledger_id FROM "{self.schema}".paid_funding WHERE id=1'))) != self.ledger_id:
                raise ProbeError('paid_ledger_identity_mismatch')
            result = {}
            for group in ('provider', 'model'):
                result[group] = [dict(r) for r in conn.execute(text(f'''SELECT {group},count(*) AS calls,
                    coalesce(sum(reserved) FILTER (WHERE actual IS NULL),0) AS held_cny,
                    coalesce(sum(actual),0) AS actual_cny,coalesce(sum(actual_usd),0) AS actual_usd,
                    sum((usage->>'input_tokens')::bigint) AS input_tokens,
                    sum((usage->>'output_tokens')::bigint) AS output_tokens
                    FROM "{self.schema}".paid_calls GROUP BY {group}''')).mappings()]
            return result
