"""Persistent MOCK accounting. Monetary amounts are CNY simulation, never authority."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import re

from sqlalchemy import select, func
from app.models import CostBudget, CostCall, utcnow


class LedgerError(ValueError):
    """Safe code only; no connection details, payloads or exception forwarding."""


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > Decimal('99999999999999'): raise ValueError()
        return result.quantize(Decimal('.000001'), rounding=ROUND_CEILING)
    except (InvalidOperation, ValueError): raise LedgerError('invalid_money') from None


def tag(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,64}',value): raise LedgerError('invalid_label')
    return value


def priced(usage, rate):
    # Reasoning is a subset of output, not a second charge. Cache is subset input.
    if set(usage) != {'input','cached','output','reasoning'} or any(type(v) is not int or v < 0 for v in usage.values()): raise LedgerError('invalid_usage')
    if usage['cached'] > usage['input'] or usage['reasoning'] > usage['output']: raise LedgerError('invalid_usage')
    if rate.get('currency') != 'CNY_SIMULATED' or set(rate) != {'currency','input','cached','output'}: raise LedgerError('mock_rate_required')
    return money(((usage['input']-usage['cached'])*money(rate['input']) + usage['cached']*money(rate['cached']) + usage['output']*money(rate['output'])) / 1000000)


class Ledger:
    """Each mutation owns a short transaction. Global row lock first everywhere.

    Serializing a namespace is intentional for small evaluation batches. Never
    hold DB locks across transport; no process-local concurrency correctness.
    """
    def __init__(self, factory, namespace):
        self.factory, self.namespace = factory, tag(namespace)

    def configure(self, scopes, call_limit='0.50'):
        # Bootstrap only: no implicit new limits during dispatch or reconciliation.
        with self.factory.begin() as db:
            if db.scalar(select(CostBudget).where(CostBudget.namespace==self.namespace).limit(1)): raise LedgerError('already_configured')
            if ('global','all') not in scopes: raise LedgerError('global_budget_required')
            for (kind,key), ceiling in scopes.items():
                if kind not in ('global','provider','model','session'): raise LedgerError('invalid_scope')
                db.add(CostBudget(namespace=self.namespace,kind=kind,key=tag(key),ceiling=money(ceiling),call_limit=money(call_limit),held=0,spent=0,frozen=False,max_active=1 if kind=='session' else 2))

    def _lock(self, db):
        global_row = db.scalar(select(CostBudget).where(CostBudget.namespace==self.namespace,CostBudget.kind=='global',CostBudget.key=='all').with_for_update())
        if not global_row: raise LedgerError('unconfigured_budget')
        return global_row

    def _scopes(self, db, provider, model, session):
        result=[]
        for kind,key in [('global','all'),('provider',provider),('model',model),('session',session)]:
            row=db.get(CostBudget,(self.namespace,kind,key))
            if row is None: raise LedgerError('unconfigured_scope')
            result.append(row)
        return result

    def _call(self, db, call_id):
        call=db.get(CostCall,call_id)
        if call is None or call.namespace != self.namespace: raise LedgerError('call_not_found')
        return call

    def reserve(self, operation, request_hash, profile, session, amount, rate):
        tag(session); amount=money(amount)
        if not re.fullmatch('[0-9a-f]{64}',request_hash): raise LedgerError('invalid_request_hash')
        if not isinstance(operation,str) or not 1<=len(operation)<=128: raise LedgerError('invalid_operation')
        priced({'input':0,'cached':0,'output':0,'reasoning':0},rate)
        profile.check()
        profile_hash=digest(canonical(profile.safe_snapshot()))
        identity=digest(canonical([request_hash,profile_hash,session,str(amount),rate]))
        with self.factory.begin() as db:
            self._lock(db)
            old=db.scalar(select(CostCall).where(CostCall.namespace==self.namespace,CostCall.operation_hash==digest(operation)))
            if old:
                if old.request_hash != identity: raise LedgerError('idempotency_payload_mismatch')
                return old.id, False
            scopes=self._scopes(db,profile.provider,profile.model,session)
            now=utcnow()
            for scope in scopes:
                filt=[CostCall.namespace==self.namespace]
                if scope.kind!='global': filt.append(getattr(CostCall, {'provider':'provider','model':'model','session':'session_tag'}[scope.kind])==scope.key)
                active=db.scalar(select(func.count()).select_from(CostCall).where(*filt,CostCall.state.in_(['reserved','sent']),CostCall.lease_until>now))
                # Unknown outcomes and expired dispatched intents block the channel.
                uncertain=db.scalar(select(func.count()).select_from(CostCall).where(*filt,((CostCall.state=='unknown') | ((CostCall.state=='sent') & (CostCall.lease_until<=now)))))
                if scope.frozen or uncertain: raise LedgerError('budget_frozen_or_unknown')
                if amount>scope.call_limit or scope.spent+scope.held+amount>scope.ceiling: raise LedgerError('budget_exceeded')
                if active>=scope.max_active: raise LedgerError('concurrency_exceeded')
            call=CostCall(namespace=self.namespace,operation_hash=digest(operation),request_hash=identity,profile_id=profile.id,profile_hash=profile_hash,profile_snapshot=profile.safe_snapshot(),provider=profile.provider,model=profile.model,session_tag=session,transport='mock',reserved=amount,rate=rate,state='reserved',lease_until=now+timedelta(seconds=60))
            db.add(call)
            for scope in scopes: scope.held+=amount
            db.flush()
            return call.id, True

    def sent(self, call_id):
        with self.factory.begin() as db:
            self._lock(db); call=self._call(db,call_id)
            if call.state!='reserved' or call.lease_until<=utcnow(): return False
            call.state='sent'
            return True  # The ONE dispatch permit, durable before transport.

    def received(self, call_id, usage, evidence):
        with self.factory.begin() as db:
            self._lock(db); call=self._call(db,call_id)
            if call.state!='sent': raise LedgerError('invalid_transition')
            call.usage=usage; call.estimated=priced(usage,call.rate); call.model_evidence=evidence
            call.state='unknown' if call.lease_until<=utcnow() else 'response_received'
            if call.estimated>call.reserved:
                for scope in self._scopes(db,call.provider,call.model,call.session_tag): scope.frozen=True

    def unknown(self, call_id, code):
        if code not in {'timeout','crash','cancelled','http_429','http_5xx','protocol_invalid','usage_invalid','refused','truncated','output_invalid'}: raise LedgerError('invalid_error_code')
        with self.factory.begin() as db:
            self._lock(db); call=self._call(db,call_id)
            if call.state=='unknown': return
            if call.state!='sent': raise LedgerError('invalid_transition')
            call.state='unknown'; call.error_code=code

    def recover_expired(self):
        # EXPLICIT maintenance, not GET. No inference/transport, no held refunds.
        with self.factory.begin() as db:
            self._lock(db)
            rows=db.scalars(select(CostCall).where(CostCall.namespace==self.namespace,CostCall.state.in_(['reserved','sent']),CostCall.lease_until<=utcnow())).all()
            for call in rows:
                if call.state=='sent': call.state='unknown'; call.error_code='crash'
                else:
                    # Durable state proves no dispatch permit was issued.
                    self._settle(db,call,money(0),digest('unsent:'+str(call.id)))
            return len(rows)

    def _settle(self, db, call, actual, invoice_hash):
        for scope in self._scopes(db,call.provider,call.model,call.session_tag):
            scope.held-=call.reserved; scope.spent+=actual
            if actual>call.reserved or scope.spent+scope.held>scope.ceiling: scope.frozen=True
        call.actual=actual; call.invoice_key=invoice_hash; call.state='reconciled'

    def reconcile(self, call_id, actual, invoice):
        # Only explicit synthetic invoice in B. Production authority not implemented.
        actual=money(actual); tag(invoice)
        with self.factory.begin() as db:
            self._lock(db); call=self._call(db,call_id)
            hashed=digest(call.provider+':'+invoice)
            if call.state=='reconciled':
                if call.invoice_key!=hashed or call.actual!=actual: raise LedgerError('invoice_mismatch')
                return False
            if call.state not in ('sent','response_received','unknown'): raise LedgerError('invalid_transition')
            if db.scalar(select(CostCall.id).where(CostCall.invoice_key==hashed)): raise LedgerError('invoice_already_used')
            self._settle(db,call,actual,hashed)
            return True

    def get(self, call_id):
        with self.factory() as db:
            call=self._call(db,call_id)
            state=call.state
            if state=='sent' and call.lease_until<=utcnow(): state='unknown'
            return {'call_id':str(call.id),'state':state,'persisted_state':call.state,'transport':call.transport,'profile':call.profile_snapshot,'estimated':str(call.estimated) if call.estimated is not None else None,'reserved':str(call.reserved),'actual':str(call.actual) if call.actual is not None else None,'usage':call.usage,'model_evidence':call.model_evidence,'error_code':call.error_code}

    def report(self):
        with self.factory() as db:
            rows=db.scalars(select(CostCall).where(CostCall.namespace==self.namespace).order_by(CostCall.created_at,CostCall.id)).all()
            totals={}
            for c in rows:
                for dim,key in [('provider',c.provider),('model',c.model),('session',c.session_tag)]:
                    group=totals.setdefault(dim+':'+key,{'calls':0,'unknown_usage_calls':0,'unreconciled_calls':0,'input_tokens_mock':0,'cached_input_tokens_mock':0,'output_tokens_mock':0,'reasoning_tokens_subset_mock':0,'estimated_cny_mock':'0','reconciled_cny_mock':'0','held_cny_mock':'0'})
                    group['calls']+=1
                    group['unknown_usage_calls']+=int(c.usage is None);group['unreconciled_calls']+=int(c.actual is None)
                    group['cached_input_tokens_mock']+=(c.usage or {}).get('cached',0);group['reasoning_tokens_subset_mock']+=(c.usage or {}).get('reasoning',0)
                    group['input_tokens_mock']+=(c.usage or {}).get('input',0);group['output_tokens_mock']+=(c.usage or {}).get('output',0)
                    for target,value in [('estimated_cny_mock',c.estimated or 0),('reconciled_cny_mock',c.actual or 0),('held_cny_mock',0 if c.actual is not None else c.reserved)]: group[target]=str(Decimal(group[target])+value)
            return totals
