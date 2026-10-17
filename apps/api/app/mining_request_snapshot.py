"""Read-only fresh business evidence for OFFLINE request checks, not admission.

No API registration or writes. No PaidControl, resolver, adapter or transport.
A snapshot is a point-in-time observation, not a future dispatch permission.
"""
from sqlalchemy import select,text
from app import facts
from app.models import ExperienceSession,MiningRun,MiningReceipt,utcnow
from app.mining_context import build_context
from app.mining_paid_models import MiningPaidPlan,MiningPaidIdentity,MiningPaidBinding
from app.paid_models import PaidGrant,PaidFunding
from app.cost_ledger import canonical
from app.prepared_mining_request import BusinessSnapshotV1,RequestContractError,sha,VERSION


def operation_identity(session_id,root_id,receipt_hash,request_tag):
    return sha(canonical(dict(version=VERSION,session_id=str(session_id),root_run_id=str(root_id),
        receipt_hash=receipt_hash,root_request_tag=request_tag)).encode('utf8'))


def read_snapshot(factory,sid,token,rid,*,require_metadata=False):
    # The factory is a trusted server dependency. No URL/ledger/user identifier
    # is accepted from a frontend. Tests enforce the dedicated DB/schema guard.
    try:
        with factory() as db,db.begin():
            db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            if db.execute(text("SELECT current_setting('transaction_read_only'),current_setting('transaction_isolation')")).one()!=('on','repeatable read'):
                raise RequestContractError('dynamic_readonly_required')
            session=facts.authorize(db,sid,token)
            run=db.get(MiningRun,rid)
            if (run is None or run.session_id!=session.id or run.state!='running'
                or run.lease_until<=utcnow() or session.status!='active' or session.mining_status!='active'
                or session.context_revision!=run.reserved_revision):
                raise RequestContractError('dynamic_business_inactive')
            context=build_context(db,run,session)
            root=run;visited=set()
            while root.retry_of is not None:
                if root.id in visited or len(visited)>=64: raise RequestContractError('dynamic_root_invalid')
                visited.add(root.id);root=db.get(MiningRun,root.retry_of)
                if root is None or root.session_id!=sid: raise RequestContractError('dynamic_root_invalid')
            receipt=db.scalar(select(MiningReceipt).where(MiningReceipt.run_id==root.id))
            if receipt is None or receipt.session_id!=sid or receipt.state!='live' or receipt.expires_at<=utcnow():
                raise RequestContractError('dynamic_receipt_unavailable')
            operation=operation_identity(sid,root.id,receipt.key_digest,receipt.request_tag)
            plan=db.scalar(select(MiningPaidPlan).where(MiningPaidPlan.root_run_id==root.id))
            metadata=None
            if plan is not None:
                if plan.run_id!=run.id: raise RequestContractError('dynamic_root_already_bound')
                identity=db.get(MiningPaidIdentity,sid)
                grant=db.get(PaidGrant,plan.grant_id)
                funding=db.get(PaidFunding,1)
                if (plan.config_version!=VERSION or plan.session_id!=sid or identity is None
                    or funding is None or funding.ledger_id!=plan.ledger_id or grant is None
                    or grant.policy_hash!=plan.policy_sha or sha(canonical(grant.policy).encode('utf8'))!=plan.policy_sha
                    or plan.receipt_hash!=receipt.key_digest
                    or plan.operation_hash!=operation or grant.policy.get('provider')!=plan.provider
                    or grant.policy.get('model')!=plan.model
                    or sha(str(grant.policy.get('account_ref','')).encode('utf8'))!=plan.account_sha):
                    raise RequestContractError('dynamic_metadata_invalid')
                # A fixed SyntheticRequest certificate can never be silently
                # repurposed to authorize dynamic bytes. Zero, explicit fixture
                # policies prove projection only; NOT PaidPolicy/paid authority.
                certs=grant.policy.get('certificates')
                if certs:
                    if not any(c.get('request_sha')==plan.request_sha for c in certs):
                        raise RequestContractError('dynamic_fixed_grant_mismatch')
                elif not (grant.ceiling==0 and grant.policy.get('execution')=='offline_contract_fixture_v1'):
                    raise RequestContractError('dynamic_grant_contract_unavailable')
                binding=db.get(MiningPaidBinding,rid)
                fields=('run_id','root_run_id','operation_hash','receipt_hash','request_sha','context_sha',
                    'prompt_sha','schema_sha','config_version','prompt_version','schema_version','provider','model')
                projection={f:str(getattr(plan,f)) for f in fields}
                if binding is not None and (binding.binding_state!='bound' or any(
                    str(getattr(binding,f))!=v for f,v in projection.items()) or any(
                    getattr(binding,f)!=getattr(plan,f) for f in ('ledger_id','grant_id','policy_sha','account_sha'))
                    or (binding.actor_scope,binding.session_scope)!=(identity.actor_scope,identity.session_scope)):
                    raise RequestContractError('dynamic_metadata_invalid')
                metadata=canonical(projection).encode('utf8')
            elif require_metadata: raise RequestContractError('dynamic_metadata_missing')
            return BusinessSnapshotV1(sid,rid,root.id,receipt.key_digest,receipt.request_tag,operation,context,run.lease_until,metadata)
    except RequestContractError: raise
    except Exception:
        # No SQL/credentials/unknown exception text at this boundary.
        raise RequestContractError('dynamic_snapshot_unavailable') from None
