"""Route B: one risk-accepted synthetic experiment, not a hard-bound policy.

No environment key lookup, startup hook, balance client or UI registration.
Administrative functions are for an independent owner process only.
"""
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import re
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select, text

from app.cost_ledger import canonical, digest, money
from app.deepseek_contract import Frozen, ENDPOINT, MODEL, VERSION, REGION, ProbeError
from app.deepseek_bridge import synthetic_request
from app.billing_boundary import PROBE_SHA
from app.models import utcnow
from app.paid_control import PaidAdmin, approved_limit, evidence
from app.paid_models import PaidFunding, PaidCall, PaidAudit
from app.controlled_probe_models import ControlledProbe

RISK_ACCEPTANCE = 'I accept uncertain supplier charges; this is an internal plan, not a guaranteed loss cap.'
TOKENIZER_ARCHIVE_SHA = 'e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495'


class ExperimentPolicy(Frozen):
    mode: str = 'controlled_live_probe'
    execution: str  # offline_mock fixtures must NEVER become real executions
    provider: str = 'deepseek_official'
    endpoint: str = ENDPOINT
    model: str = MODEL
    expected_version: str = VERSION
    region: str = REGION
    api_mode: str = 'chat_non_thinking_json_object'
    request_sha: str = PROBE_SHA
    output_cap: int = Field(strict=True, default=256)
    account_ref: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    currency: str
    currency_evidence_sha: str = Field(pattern=r'^[a-f0-9]{64}$')
    secret_ref: str = Field(pattern=r'^Pathwise/DeepSeek/[a-zA-Z0-9_-]{1,64}$')
    secret_revision: int = Field(strict=True, gt=0)
    ledger_id: UUID
    operation_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    approver: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    approval_sha: str = Field(pattern=r'^[a-f0-9]{64}$')
    starts_at: AwareDatetime
    expires_at: AwareDatetime
    price_expires_at: AwareDatetime
    price_evidence_sha: str = Field(pattern=r'^[a-f0-9]{64}$')
    peak_input_miss_cny_per_million: Decimal = Field(gt=0)
    peak_output_cny_per_million: Decimal = Field(gt=0)
    tokenizer_archive_sha: str
    estimate_method: str = 'official_tokenizer_raw_request_json_not_server_framing'
    estimated_input_tokens: int = Field(strict=True, gt=0, le=1000000)
    planned_cny: Decimal = Field(gt=0, le=Decimal('0.10'))
    risk_acceptance: str

    @model_validator(mode='after')
    def valid(self):
        if (self.mode, self.provider, self.endpoint, self.model, self.expected_version, self.region,
            self.api_mode, self.request_sha, self.output_cap) != ('controlled_live_probe','deepseek_official',
            ENDPOINT,MODEL,VERSION,REGION,'chat_non_thinking_json_object',PROBE_SHA,256):
            raise ValueError('controlled_fixed_profile_required')
        if self.execution not in ('offline_mock','controlled_live_probe') or self.currency != 'CNY':
            raise ValueError('controlled_cny_only')
        if self.secret_ref != 'Pathwise/DeepSeek/'+self.account_ref:
            raise ValueError('controlled_secret_binding')
        if self.tokenizer_archive_sha != TOKENIZER_ARCHIVE_SHA or self.estimate_method != 'official_tokenizer_raw_request_json_not_server_framing':
            raise ValueError('controlled_estimate_evidence_required')
        if self.estimated_input_tokens != 812:
            raise ValueError('controlled_fixed_estimate_changed')
        if self.peak_input_miss_cny_per_million!=Decimal('2') or self.peak_output_cny_per_million!=Decimal('8'):
            raise ValueError('controlled_reviewed_peak_prices_required')
        if self.risk_acceptance != RISK_ACCEPTANCE or not self.starts_at < self.expires_at <= self.price_expires_at:
            raise ValueError('controlled_risk_or_window_invalid')
        if self.expires_at-self.starts_at > timedelta(hours=1):
            raise ValueError('controlled_window_max_one_hour')
        if self.planned_cny != money(self.planned_cny) or self.planned_cny < self.estimate_cny():
            raise ValueError('controlled_plan_below_estimate')
        return self

    def estimate_cny(self):
        return money((Decimal(self.estimated_input_tokens)*self.peak_input_miss_cny_per_million
                      + Decimal(256)*self.peak_output_cny_per_million)/Decimal(1000000))

    def sha(self): return digest(canonical(self.model_dump(mode='json')))


def verify_bytes(body):
    if type(body) is not bytes or hashlib.sha256(body).hexdigest() != PROBE_SHA or body != synthetic_request().body:
        raise ProbeError('controlled_request_changed')


class ExperimentAdmin:
    """Owner only. No HTTP or secret resolution; never used by execute."""
    def __init__(self, factory): self.factory = factory

    def authorize(self, policy):
        if type(policy) is not ExperimentPolicy: raise ProbeError('controlled_policy_required')
        with self.factory.begin() as db:
            pool = db.scalar(select(PaidFunding).where(PaidFunding.id==1).with_for_update())
            if (str(pool.ledger_id) != str(policy.ledger_id) or pool.frozen or pool.held != 0 or pool.spent != 0
                    or db.get(ControlledProbe,1) is not None or db.scalar(select(PaidCall.id).limit(1)) is not None):
                raise ProbeError('controlled_exclusive_unused_ledger_required')
            # This is explicit owner approval, NOT a startup default or new pool.
            # Do not silently replace a separately approved central amount.
            if pool.ceiling not in (Decimal(0), policy.planned_cny):
                raise ProbeError('controlled_total_approval_conflict')
            if not policy.starts_at <= utcnow() < policy.expires_at:
                raise ProbeError('controlled_inactive')
            pool.ceiling = policy.planned_cny; pool.approval_digest = policy.approval_sha
            row = ControlledProbe(id=1,pool_id=1,grant_id=uuid4(),policy_hash=policy.sha(),
                policy=policy.model_dump(mode='json'),revoked=False,state='approved',reserved=policy.planned_cny)
            db.add(row)
            db.add(PaidAudit(action='controlled_authorize',evidence_digest=policy.approval_sha,
                detail={'currency':'CNY','risk_accepted':True,'plan_not_loss_cap':True,'policy_hash':policy.sha()}))
            db.flush();return row.grant_id

    def revoke(self, proof):
        with self.factory.begin() as db:
            db.scalar(select(PaidFunding).where(PaidFunding.id==1).with_for_update())
            row=db.get(ControlledProbe,1)
            if row is None:raise ProbeError('controlled_approval_missing')
            row.revoked=True
            db.add(PaidAudit(action='controlled_revoke',evidence_digest=evidence(proof),detail={}))

    def reconcile(self, actual_cny, invoice_sha, review_sha):
        if not isinstance(actual_cny,(str,Decimal)):raise ProbeError('controlled_decimal_required')
        actual=Decimal(actual_cny)
        if not actual.is_finite() or actual<0 or actual>=Decimal('1e12') or actual!=actual.quantize(Decimal('0.000000000001')):
            raise ProbeError('controlled_invoice_invalid')
        evidence(invoice_sha); evidence(review_sha)
        with self.factory.begin() as db:
            pool=db.scalar(select(PaidFunding).where(PaidFunding.id==1).with_for_update())
            row=db.get(ControlledProbe,1)
            if row is None or row.policy['execution']!='controlled_live_probe':
                raise ProbeError('controlled_real_invoice_requires_live_record')
            if row.state=='reconciled':
                if row.actual_cny!=actual or row.invoice_hash!=invoice_sha:raise ProbeError('controlled_invoice_conflict')
                return False
            if row.state not in ('sent','response_received','unknown'):raise ProbeError('controlled_transition_invalid')
            if db.scalar(select(PaidCall.id).where(PaidCall.invoice_hash==invoice_sha)):
                raise ProbeError('controlled_invoice_reused')
            row.state='reconciled';row.actual_cny=actual;row.invoice_hash=invoice_sha
            pool.held-=row.reserved;pool.spent+=money(actual)
            # No automatic unfreeze, even when the bill is below plan.
            pool.frozen=True
            db.add(PaidAudit(action='controlled_reconcile',evidence_digest=review_sha,
                detail={'currency':'CNY','actual_cny':str(actual),'invoice_sha':invoice_sha,'over_plan':actual>row.reserved}))
            return True

    def provision_runtime(self, schema, role):
        PaidAdmin(self.factory).provision_runtime_role(schema,role)
        with self.factory.begin() as db:
            db.execute(text(f'GRANT SELECT ON "{schema}".controlled_probe TO "{role}"'))
            db.execute(text(f'GRANT EXECUTE ON FUNCTION "{schema}".controlled_runtime(text,text,text,jsonb) TO "{role}"'))

    def close_unsent(self, proof):
        with self.factory.begin() as db:
            pool=db.scalar(select(PaidFunding).where(PaidFunding.id==1).with_for_update())
            row=db.get(ControlledProbe,1)
            if row is None or row.state not in ('approved','reserved'):raise ProbeError('controlled_not_provably_unsent')
            if row.state=='reserved':pool.held-=row.reserved
            row.state='reconciled';row.actual_cny=0;row.invoice_hash=digest('controlled-unsent:'+str(row.grant_id))
            db.add(PaidAudit(action='controlled_close_unsent',evidence_digest=evidence(proof),detail={}))


class ExperimentControl:
    def __init__(self, engine, schema, ledger_id):
        if not re.fullmatch('[a-z][a-z0-9_]{0,62}',schema):raise ProbeError('controlled_schema_invalid')
        self.engine,self.schema,self.ledger_id=engine,schema,str(UUID(str(ledger_id)))

    def check_role(self, *, live):
        u=self.engine.url
        if u.get_backend_name()!='postgresql' or u.host not in ('localhost','127.0.0.1'):
            raise ProbeError('controlled_local_database_required')
        if live:
            if (u.database,self.schema,u.port or 5432)!=('pathwise_probe','public',5432):raise ProbeError('controlled_live_database_required')
        elif u.database not in ('pathwise_test','pathwise_e2e') or not re.fullmatch('test_(?:eval_)?[a-f0-9]{32}',self.schema):
            raise ProbeError('controlled_test_database_required')
        with self.engine.connect() as conn:
            ok=conn.scalar(text('''SELECT current_user=session_user AND NOT
                (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolbypassrls
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
                OR has_database_privilege(r.oid,current_database(),'CREATE')
                OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_temp_%'
                    AND has_schema_privilege(r.oid,n.oid,'CREATE'))
                OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname=:s AND c.relkind='r' AND has_table_privilege(r.oid,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER')))
                FROM pg_roles r WHERE rolname=current_user'''),{'s':self.schema})
            if ok is not True:raise ProbeError('controlled_restricted_login_required')

    def read(self):
        with self.engine.connect() as conn:
            row=conn.execute(text(f'''SELECT p.policy,p.policy_hash,p.grant_id,p.state,p.revoked,p.reserved,
                p.actual_cny,p.diagnostic,p.lease_until,f.ledger_id,f.ceiling,f.held,f.spent,f.frozen,clock_timestamp() AS now
                FROM "{self.schema}".paid_funding f LEFT JOIN "{self.schema}".controlled_probe p ON p.id=1 WHERE f.id=1''')).mappings().one()
            if str(row['ledger_id'])!=self.ledger_id:raise ProbeError('controlled_ledger_mismatch')
            return dict(row)

    def policy(self, execution):
        row=self.read()
        if row['policy'] is None:raise ProbeError('controlled_approval_missing')
        p=ExperimentPolicy.model_validate(row['policy'])
        if (p.execution!=execution or p.sha()!=row['policy_hash'] or str(p.ledger_id)!=self.ledger_id
            or row['revoked'] or not p.starts_at<=row['now']<p.expires_at or row['now']>=p.price_expires_at):
            raise ProbeError('controlled_approval_inactive_or_wrong_mode')
        if row['state'] in ('approved','reserved','sent'):
            needed=p.planned_cny if row['state']=='approved' else Decimal(0)
            if (row['held']+row['spent']+needed>row['ceiling']
                or (row['state']!='approved' and row['held']<row['reserved'])
                or (row['state']!='sent' and row['frozen'])):
                raise ProbeError('controlled_budget_unavailable')
        return p

    def action(self, p, action, diagnostic=None):
        payload=diagnostic if diagnostic is not None else {'request_sha':PROBE_SHA,'operation':p.operation_hash}
        with self.engine.begin() as conn:
            return conn.scalar(text(f'SELECT "{self.schema}".controlled_runtime(:l,:p,:a,CAST(:v AS jsonb))'),
                {'l':self.ledger_id,'p':p.sha(),'a':action,'v':canonical(payload)})

    def report(self):
        row=self.read();p=row['policy'];state=row['state']
        if state=='sent' and row['lease_until']<=row['now']:state='unknown'
        usage=(row['diagnostic'] or {}).get('usage')
        usage_estimate=None
        if p and usage:
            usage_estimate=str(money((Decimal(usage['prompt_tokens'])*Decimal(p['peak_input_miss_cny_per_million'])
                +Decimal(usage['completion_tokens'])*Decimal(p['peak_output_cny_per_million']))/Decimal(1000000)))
        return {'mode':'controlled_live_probe','execution':p['execution'] if p else None,'state':state,
            'account_currency':p['currency'] if p else None,'approved_plan_cny':str(row['reserved']) if p else None,
            'plan_is_guaranteed_loss_cap':False,'estimated_cost_cny':str(ExperimentPolicy.model_validate(p).estimate_cny()) if p else None,
            'usage_estimated_cost_cny':usage_estimate,
            'actual_cny':str(row['actual_cny']) if row['actual_cny'] is not None else None,
            'held_cny':str(row['held']),'spent_cny':str(row['spent']),'frozen':row['frozen'],
            'diagnostic':row['diagnostic'],'automatic_retry':False}
