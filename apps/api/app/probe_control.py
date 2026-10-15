"""C-0 preflight ledger, strictly OFFLINE fixtures. No real approvals can exist.

All batches/grants share singleton funding row 1; there is NO namespace budget.
The paid ledger protocol is proposed in docs; this is its executable zero-fee
control proof, not an enabled financial authorization system.
"""
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select, func

from app.cost_ledger import canonical, digest, money, tag
from app.deepseek_contract import ProbePolicy, ProbeError, check_request
from app.models import ProbeFunding, ProbeGrant, ProbeAttempt, utcnow


class ProbeControl:
    def __init__(self,factory):self.factory=factory

    def setup_fixture_pool(self,ceiling):
        with self.factory.begin() as db:
            if db.get(ProbeFunding,1):raise ProbeError('pool_already_exists')
            db.add(ProbeFunding(id=1,approved_real_cny=0,fixture_ceiling=money(ceiling),held=0,spent=0,frozen=False))

    def add_fixture_grant(self,policy,starts_at,expires_at,fixture_limit,calls_limit=1,mode='offline_fixture'):
        if mode not in ('draft','offline_fixture','revoked'):raise ProbeError('real_grant_unavailable_c0')
        policy.check(utcnow())
        with self.factory.begin() as db:
            self._lock(db)
            grant=ProbeGrant(pool_id=1,mode=mode,approved_real_cny=0,starts_at=starts_at,expires_at=expires_at,
                             fixture_limit=money(fixture_limit),calls_limit=calls_limit,policy=policy.model_dump(mode='json'))
            db.add(grant);db.flush();return grant.id

    def _lock(self,db):
        row=db.scalar(select(ProbeFunding).where(ProbeFunding.id==1).with_for_update())
        if row is None or row.approved_real_cny!=0:raise ProbeError('zero_authority_pool_required')
        return row

    def _grant(self,db,gid,now):
        grant=db.get(ProbeGrant,gid)
        if (grant is None or grant.mode!='offline_fixture' or grant.approved_real_cny!=0
            or grant.starts_at>now or grant.expires_at<=now):raise ProbeError('grant_missing_or_expired')
        try:policy=ProbePolicy.model_validate(grant.policy);policy.check(now)
        except ProbeError:raise
        except Exception:raise ProbeError('policy_invalid') from None
        return grant,policy

    def _attempt(self,db,aid):
        row=db.get(ProbeAttempt,aid)
        if row is None:raise ProbeError('attempt_missing')
        return row

    def prepare(self,gid,request,operation,batch_tag,expected_policy_hash=None):
        if not isinstance(operation,str) or not 1<=len(operation)<=128:raise ProbeError('operation_invalid')
        tag(batch_tag)
        with self.factory.begin() as db:
            pool=self._lock(db);now=utcnow();grant,policy=self._grant(db,gid,now)
            check_request(request,policy,now)
            if expected_policy_hash is not None and expected_policy_hash!=digest(canonical(policy.model_dump(mode='json'))):raise ProbeError('policy_changed')
            identity=digest(canonical([str(gid),request.fingerprint,batch_tag,digest(canonical(policy.model_dump(mode='json')))]))
            previous=db.scalar(select(ProbeAttempt).where(ProbeAttempt.operation_hash==digest(operation)))
            if previous:
                if previous.request_hash!=identity:raise ProbeError('idempotency_payload_mismatch')
                return previous.id,False
            amount=policy.reservation()
            uncertain=db.scalar(select(func.count()).select_from(ProbeAttempt).where(
                (ProbeAttempt.state=='unknown')|((ProbeAttempt.state=='sent')&(ProbeAttempt.lease_until<=now))))
            if pool.frozen or uncertain:raise ProbeError('pool_frozen_or_unknown')
            used=db.scalar(select(func.coalesce(func.sum(func.coalesce(ProbeAttempt.actual,ProbeAttempt.reserved)),0)).where(ProbeAttempt.grant_id==gid))
            count=db.scalar(select(func.count()).select_from(ProbeAttempt).where(ProbeAttempt.grant_id==gid))
            active=db.scalar(select(func.count()).select_from(ProbeAttempt).where(ProbeAttempt.state.in_(['reserved','sent']),ProbeAttempt.lease_until>now))
            if active>=2:raise ProbeError('concurrency_exceeded')
            if count>=grant.calls_limit:raise ProbeError('call_count_exceeded')
            if pool.spent+pool.held+amount>pool.fixture_ceiling or used+amount>grant.fixture_limit:raise ProbeError('budget_exceeded')
            item=ProbeAttempt(grant_id=gid,operation_hash=digest(operation),request_hash=identity,batch_tag=batch_tag,
                              policy_snapshot=policy.model_dump(mode='json'),
                              execution='offline_http_fixture',state='reserved',reserved=amount,lease_until=now+timedelta(seconds=60))
            db.add(item);pool.held+=amount;db.flush();return item.id,True

    def permit_fixture_send(self,aid,request):
        # No transferable token to a live network path. Root serialization, once.
        with self.factory.begin() as db:
            pool=self._lock(db);item=self._attempt(db,aid)
            if item.state!='reserved':return False
            now=utcnow();_,policy=self._grant(db,item.grant_id,now)
            check_request(request,policy,now)
            identity=digest(canonical([str(item.grant_id),request.fingerprint,item.batch_tag,digest(canonical(policy.model_dump(mode='json')))]))
            if identity!=item.request_hash:raise ProbeError('idempotency_payload_mismatch')
            if item.lease_until<=now or pool.frozen:raise ProbeError('send_not_permitted')
            if db.scalar(select(ProbeAttempt.id).where((ProbeAttempt.state=='unknown')|((ProbeAttempt.state=='sent')&(ProbeAttempt.lease_until<=now))).limit(1)):
                raise ProbeError('pool_frozen_or_unknown')
            item.state='sent';return True

    def fixture_policy(self,gid):
        # Checked anew immediately before key binding / send. No environment read.
        with self.factory() as db:return self._grant(db,gid,utcnow())[1]

    def received(self,aid,usage):
        with self.factory.begin() as db:
            self._lock(db);row=self._attempt(db,aid)
            if row.state!='sent':raise ProbeError('invalid_transition')
            row.usage=usage
            row.state='response_received' if row.lease_until>utcnow() else 'unknown'

    def unknown(self,aid,code):
        allowed={'timeout','cancelled','transport_error','http_4xx','http_429','http_5xx','redirect_refused','body_too_large',
                 'model_drift','refused','truncated','unexpected_mode','usage_exceeded','response_invalid','crash'}
        if code not in allowed:code='response_invalid'
        with self.factory.begin() as db:
            self._lock(db);row=self._attempt(db,aid)
            if row.state=='unknown':return
            if row.state!='sent':raise ProbeError('invalid_transition')
            row.state='unknown';row.error_code=code

    def get(self,aid):
        with self.factory() as db:
            row=self._attempt(db,aid)
            state='unknown' if row.state=='sent' and row.lease_until<=utcnow() else row.state
            return {'id':str(row.id),'state':state,'persisted_state':row.state,'reserved_fixture_cny':str(row.reserved),
                    'actual_fixture_cny':str(row.actual) if row.actual is not None else None,'error_code':row.error_code,
                    'usage_fixture':row.usage,'approved_real_cny':'0.000000'}

    def recover_expired(self):
        with self.factory.begin() as db:
            pool=self._lock(db)
            rows=db.scalars(select(ProbeAttempt).where(ProbeAttempt.state.in_(['reserved','sent']),ProbeAttempt.lease_until<=utcnow())).all()
            for row in rows:
                if row.state=='sent':row.state='unknown';row.error_code='crash'
                else:
                    pool.held-=row.reserved;row.actual=0;row.state='reconciled';row.invoice_hash=digest('provably-unsent:'+str(row.id))
            return len(rows)

    def reconcile_fixture(self,aid,actual,invoice_reference):
        # No real invoice fetch, no paid billing approval or refund API in C-0.
        actual=money(actual);tag(invoice_reference);invoice=digest(invoice_reference)
        with self.factory.begin() as db:
            pool=self._lock(db);row=self._attempt(db,aid)
            if row.state=='reconciled':
                if row.invoice_hash!=invoice or row.actual!=actual:raise ProbeError('invoice_mismatch')
                return False
            if row.state not in ('sent','unknown','response_received'):raise ProbeError('invalid_transition')
            if db.scalar(select(ProbeAttempt.id).where(ProbeAttempt.invoice_hash==invoice)):raise ProbeError('invoice_already_used')
            pool.held-=row.reserved;pool.spent+=actual
            if actual>row.reserved or pool.spent+pool.held>pool.fixture_ceiling:pool.frozen=True
            row.actual=actual;row.invoice_hash=invoice;row.state='reconciled';return True

    def unfreeze_fixture(self,review_reference):
        # Explicit operator action, no reconciliation shortcut or automatic reset.
        tag(review_reference)
        with self.factory.begin() as db:
            pool=self._lock(db)
            if db.scalar(select(ProbeAttempt.id).where(ProbeAttempt.actual.is_(None)).limit(1)) or pool.spent>pool.fixture_ceiling:
                raise ProbeError('manual_review_unresolved')
            pool.frozen=False;pool.last_review_digest=digest(review_reference)
