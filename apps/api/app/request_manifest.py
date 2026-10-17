"""Inert manifest metadata + pure verification of recovered bytes.

No production body storage, secrets, transport, fees, retries or API entry.
The only persistence helper requires an already trusted transaction dependency.
"""
from dataclasses import dataclass,field
from datetime import datetime
from uuid import UUID
from sqlalchemy import select,delete,func
from app.models import ExperienceSession,MiningRun,utcnow
from app.mining_context import MiningContext
from app.cost_ledger import canonical
from app.prepared_mining_request import (PreparedMiningRequestV1,BusinessSnapshotV1,
    artifacts_v1,strict_json,sha,CHECKS)
from app.mining_request_admission import validate_prepared
from app.request_manifest_models import RequestManifest,RequestManifestTombstone,IDENTITY_FIELDS

ERRORS=frozenset(('manifest_invalid','manifest_conflict','manifest_unavailable',
    'manifest_business_inactive','manifest_bytes_unavailable','manifest_verification_failed'))
PROJECTION=('run_id','root_run_id','operation_hash','receipt_hash','request_sha','context_sha',
    'prompt_sha','schema_sha','config_version','prompt_version','schema_version','provider','model')


class ManifestError(ValueError):
    def __init__(self,code):
        super().__init__(code if type(code) is str and code in ERRORS else 'manifest_invalid')


@dataclass(frozen=True,slots=True,repr=False)
class RequestManifestV1:
    # Canonical metadata only, never a request body, account, grant or secret.
    metadata_bytes: bytes
    created_at: datetime
    expires_at: datetime
    storage_state: str = 'metadata_only'


@dataclass(frozen=True,slots=True,repr=False)
class RecoveredRequestV1:
    request: PreparedMiningRequestV1
    manifest_sha: str
    recovered_and_verified: bool = field(default=True,init=False)
    paid_authorized: bool = field(default=False,init=False)
    dispatch_permitted: bool = field(default=False,init=False)
    # No offline_contract_valid: continued business needs admit_offline fresh.


def metadata_values(current,prepared):
    values={name:getattr(prepared,name) for name in IDENTITY_FIELDS if hasattr(prepared,name)}
    values.update(manifest_version=1,session_id=current.session_id,
        receipt_hash=current.receipt_hash,root_request_tag=current.root_request_tag)
    return values


def manifest_record(row):
    values={n:(str(getattr(row,n)) if n.endswith('_id') else getattr(row,n)) for n in IDENTITY_FIELDS}
    return RequestManifestV1(canonical(values).encode('utf8'),row.created_at,row.expires_at,row.storage_state)


def persist_metadata(db,current,prepared):
    """Caller owns transaction. No commit, body write or financial lock here.

    Session -> Run -> Manifest; NEVER then Funding. 0011 plan must be committed
    beforehand by a separately reviewed writer. Current is trusted server data.
    """
    try:
        session=db.scalar(select(ExperienceSession).where(
            ExperienceSession.id==current.session_id).with_for_update().execution_options(populate_existing=True))
        run=db.scalar(select(MiningRun).where(MiningRun.id==current.run_id)
            .with_for_update(read=True,key_share=True).execution_options(populate_existing=True))
        if (session is None or run is None or run.session_id!=session.id
            or session.status!='active' or session.mining_status!='active' or run.state!='running'
            or run.lease_until<=utcnow() or session.context_revision!=run.reserved_revision
            or run.reserved_revision!=current.context.context_revision):
            raise ManifestError('manifest_business_inactive')
        validate_prepared(prepared,current)
        values=metadata_values(current,prepared)
        existing=db.scalar(select(RequestManifest).where(RequestManifest.root_run_id==current.root_run_id))
        if existing is not None:
            if existing.expires_at<=utcnow(): raise ManifestError('manifest_unavailable')
            if any(getattr(existing,k)!=v for k,v in values.items()): raise ManifestError('manifest_conflict')
            return existing
        row=RequestManifest(**values,expires_at=run.lease_until)
        db.add(row);db.flush();db.refresh(row)
        return row
    except ManifestError: raise
    except Exception:
        # Transaction rollback belongs to caller; never log DB/input exceptions.
        raise ManifestError('manifest_verification_failed') from None


def purge_expired_tombstones(db):
    """Explicit maintenance transaction only, NOT registered/scheduled anywhere.

    Caller must be an independently approved metadata maintainer. Database guard
    refuses early removal. Expired roots are already absent from business data;
    this never creates an operation, changes funding, or grants send eligibility.
    """
    return db.execute(delete(RequestManifestTombstone)
        .where(RequestManifestTombstone.expires_at<=func.clock_timestamp())).rowcount


def verify_recovered(manifest,body,*,lookup):
    """Verify original stored bytes; NEVER call Adapter, prepare or build_context.

    This is a pure offline archive check, not current business/fee/send approval.
    Body storage and its authenticated read ACL are independent prerequisites.
    """
    try:
        if type(manifest) is not RequestManifestV1 or manifest.storage_state!='metadata_only': raise ValueError()
        if manifest.created_at>=manifest.expires_at or manifest.expires_at<=utcnow(): raise ValueError()
        if type(body) is not bytes or not 0<len(body)<=192000: raise ValueError()
        values=strict_json(manifest.metadata_bytes)
        if set(values)!=set(IDENTITY_FIELDS) or canonical(values).encode('utf8')!=manifest.metadata_bytes: raise ValueError()
        if type(values['manifest_version']) is not int or values['manifest_version']!=1: raise ValueError()
        if sha(body)!=values['request_sha']: raise ValueError()
        for name in ('run_id','root_run_id','session_id'): values[name]=UUID(values[name])
        # Independent caller lookup, not identities echoed from the stored DTO.
        if (values['session_id'],values['run_id'],values['root_run_id'],values['operation_hash'])!=lookup:
            raise ValueError()
        raw=strict_json(body)
        context=MiningContext.model_validate_json(raw['messages'][1]['content'])
        fields={n:values[n] for n in PreparedMiningRequestV1.__dataclass_fields__ if n in values}
        bundle=artifacts_v1()
        request=PreparedMiningRequestV1(**fields,body=body,profile_bytes=bundle.profile_bytes,preparation_checks=CHECKS)
        metadata=canonical({n:str(values[n]) for n in PROJECTION}).encode('utf8')
        snapshot=BusinessSnapshotV1(values['session_id'],values['run_id'],values['root_run_id'],
            values['receipt_hash'],values['root_request_tag'],values['operation_hash'],context,manifest.expires_at,metadata)
        validate_prepared(request,snapshot)
        digest=sha(canonical(dict(metadata=strict_json(manifest.metadata_bytes),
            created_at=manifest.created_at.isoformat(),expires_at=manifest.expires_at.isoformat(),
            storage_state=manifest.storage_state)).encode('utf8'))
        return RecoveredRequestV1(request,digest)
    except Exception:
        raise ManifestError('manifest_verification_failed') from None
