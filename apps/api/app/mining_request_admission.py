"""Independent OFFLINE contract check. No builder call or dispatch capability."""
from dataclasses import dataclass,field
from uuid import UUID

from app.cost_ledger import canonical
from app.models import utcnow
from app.prepared_mining_request import (PreparedMiningRequestV1,BusinessSnapshotV1,RequestContractError,
    artifacts_v1,checked_context,strict_json,sha,VERSION,PROMPT_VERSION,SCHEMA_VERSION,ENDPOINT,CHECKS)


@dataclass(frozen=True,slots=True)
class SnapshotContractMatchV1:
    snapshot_contract_matches: bool = field(default=True,init=False)
    metadata_mapping_valid: bool = field(default=True,init=False)
    paid_authorized: bool = field(default=False,init=False)
    dispatch_permitted: bool = field(default=False,init=False)
    scope: str = field(default='0011_projection_only_not_financial_authority',init=False)


@dataclass(frozen=True,slots=True)
class OfflineContractCheckV1(SnapshotContractMatchV1):
    # Only the fresh read wrapper returns this point-in-time observation.
    offline_contract_valid: bool = field(default=True,init=False)


def validate_prepared(prepared,current):
    """Verify final bytes against independent reviewed artifacts/current sources.

    `current` is trusted server read evidence, never a client DTO. Production
    callers must use admit_offline() for a fresh read. No proof survives future
    mutations; a future final permit must recheck under its own transaction.
    """
    try:
        if type(prepared) is not PreparedMiningRequestV1 or type(current) is not BusinessSnapshotV1:
            raise RequestContractError('dynamic_snapshot_invalid')
        if current.lease_until<=utcnow(): raise RequestContractError('dynamic_business_inactive')
        context=checked_context(current.context)
        expected_operation=sha(canonical(dict(version=VERSION,session_id=str(current.session_id),
            root_run_id=str(current.root_run_id),receipt_hash=current.receipt_hash,
            root_request_tag=current.root_request_tag)).encode('utf8'))
        if (prepared.run_id,prepared.root_run_id,prepared.context_revision,prepared.operation_hash)!=(
            current.run_id,current.root_run_id,context.context_revision,expected_operation) or current.operation_hash!=expected_operation:
            raise RequestContractError('dynamic_operation_mismatch')
        if not all(type(v) is UUID for v in (prepared.run_id,prepared.root_run_id)):
            raise RequestContractError('dynamic_operation_mismatch')
        bundle=artifacts_v1();profile=bundle.profile
        actual_fields=(prepared.contract_version,prepared.config_version,prepared.provider,prepared.model,
            prepared.expected_version,prepared.version_policy,prepared.endpoint,prepared.region,
            prepared.deployment,prepared.mode,prepared.structured_mode,prepared.output_cap,
            prepared.prompt_version,prepared.schema_version,prepared.preparation_checks)
        expected_fields=(1,VERSION,profile.provider,profile.api_model,profile.version,profile.version_policy,
            ENDPOINT,profile.region,profile.deployment,profile.mode,profile.structured_mode,profile.output_cap,
            PROMPT_VERSION,SCHEMA_VERSION,CHECKS)
        if (actual_fields!=expected_fields or type(prepared.contract_version) is not int
            or type(prepared.output_cap) is not int or type(prepared.context_revision) is not int):
            raise RequestContractError('dynamic_profile_mismatch')
        if type(prepared.body) is not bytes or not 0<len(prepared.body)<=192000:
            raise RequestContractError('dynamic_bytes_invalid')
        raw=strict_json(prepared.body)
        if (not isinstance(raw,dict) or set(raw)!={'model','messages','max_tokens','stream','temperature','response_format','thinking'}
            or canonical(raw).encode('utf8')!=prepared.body): raise RequestContractError('dynamic_wire_invalid')
        if (raw['model']!=profile.api_model or type(raw['max_tokens']) is not int or raw['max_tokens']!=profile.output_cap
            or raw['stream'] is not False or type(raw['temperature']) is not int or raw['temperature']!=0
            or raw['response_format']!={'type':'json_object'} or raw['thinking']!={'type':'disabled'}):
            raise RequestContractError('dynamic_wire_invalid')
        messages=raw['messages']
        if not isinstance(messages,list) or len(messages)!=2 or any(
            not isinstance(m,dict) or set(m)!={'role','content'} for m in messages):
            raise RequestContractError('dynamic_messages_invalid')
        if messages[0]!={'role':'system','content':bundle.system}:
            raise RequestContractError('dynamic_prompt_mismatch')
        expected_context=canonical(context.payload())
        if messages[1]!={'role':'user','content':expected_context}:
            raise RequestContractError('dynamic_context_mismatch')
        if (prepared.request_sha!=sha(prepared.body) or prepared.context_sha!=sha(expected_context.encode('utf8'))
            or prepared.prompt_file_sha!=sha(bundle.prompt_bytes) or prepared.prompt_sha!=sha(bundle.system.encode('utf8'))
            or prepared.schema_sha!=sha(bundle.schema_bytes) or prepared.schema_file_sha!=bundle.schema_file_sha
            or prepared.profile_bytes!=bundle.profile_bytes or prepared.profile_sha!=sha(bundle.profile_bytes)):
            raise RequestContractError('dynamic_digest_mismatch')
        if current.metadata_bytes is None: raise RequestContractError('dynamic_metadata_missing')
        metadata=strict_json(current.metadata_bytes)
        expected_metadata=dict(run_id=str(current.run_id),root_run_id=str(current.root_run_id),
            operation_hash=expected_operation,receipt_hash=current.receipt_hash,request_sha=sha(prepared.body),
            context_sha=sha(expected_context.encode('utf8')),prompt_sha=sha(bundle.system.encode('utf8')),
            schema_sha=sha(bundle.schema_bytes),config_version=VERSION,prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,provider=profile.provider,model=profile.api_model)
        if metadata!=expected_metadata: raise RequestContractError('dynamic_metadata_mismatch')
        return SnapshotContractMatchV1()
    except RequestContractError: raise
    except Exception:
        raise RequestContractError('dynamic_contract_invalid') from None


def admit_offline(factory,sid,token,rid,prepared):
    # Import only read evidence, never PaidControl/SecretResolver/Transport.
    from app.mining_request_snapshot import read_snapshot
    validate_prepared(prepared,read_snapshot(factory,sid,token,rid,require_metadata=True))
    return OfflineContractCheckV1()
