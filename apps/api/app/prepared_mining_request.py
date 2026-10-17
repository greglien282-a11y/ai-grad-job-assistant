"""Offline-only deterministic request contract. No credentials, ledger or HTTP.

Objects contain ephemeral minimized user text. repr intentionally hides bodies;
this is not anonymization, external-data consent or any paid/send permission.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID
from datetime import datetime

from app.cost_ledger import canonical
from app.mining_context import MiningContext, PRIVATE, within_budget
from app.model_adapter import Adapter, Profile, unique_pairs

ROOT=Path(__file__).resolve().parents[3]
VERSION='deepseek-dynamic-request-v1-offline'
PROMPT_VERSION='dynamic-mining-prompt-v1-offline'
SCHEMA_VERSION='mining-output-v2-wire-v1'
ENDPOINT='https://api.deepseek.com/chat/completions'
PROFILE_SHA='e1601192c9dbf3013c75b171f5bb7d037f639dd3c56831e31b00f290f3ce8218'
PROMPT_FILE_SHA='d9d7b2a4303c58004cbbf97fbc50e57ac195270182b73e760aefb575d8ee5273'
SCHEMA_SHA='a55afacc5c0e570a4c86dc6eaa723f8d8b43e58c455bef0308fe57e8834db736'
SCHEMA_SEPARATOR='\nWire Schema:\n'
CHECKS=('bounded_context','minimized_context','pinned_profile','canonical_utf8')
CREDENTIAL_TEXT=re.compile(r'\bBearer[ \t]+\S+|\bsk-[A-Za-z0-9_-]{8,}|(?:api[_ -]?key|password|authorization)\s*[:=]\s*\S+',re.I)
ERROR_CODES=frozenset('''dynamic_json_invalid dynamic_artifact_mismatch dynamic_context_invalid
dynamic_snapshot_invalid dynamic_business_inactive dynamic_root_invalid dynamic_receipt_unavailable
dynamic_root_already_bound dynamic_metadata_invalid dynamic_fixed_grant_mismatch
dynamic_grant_contract_unavailable dynamic_metadata_missing dynamic_snapshot_unavailable
dynamic_readonly_required dynamic_operation_mismatch dynamic_profile_mismatch dynamic_bytes_invalid
dynamic_wire_invalid dynamic_messages_invalid dynamic_prompt_mismatch dynamic_context_mismatch
dynamic_digest_mismatch dynamic_metadata_mismatch dynamic_contract_invalid'''.split())


class RequestContractError(ValueError):
    """Only locally defined fixed diagnostic codes, never input/exception text."""
    def __init__(self,code):
        super().__init__(code if type(code) is str and code in ERROR_CODES else 'dynamic_contract_invalid')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    try:
        return json.loads(data,object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError,TypeError,UnicodeError):
        raise RequestContractError('dynamic_json_invalid') from None


@dataclass(frozen=True,slots=True,repr=False)
class ArtifactsV1:
    profile: Profile
    profile_bytes: bytes
    prompt_bytes: bytes
    schema_bytes: bytes
    schema_file_sha: str
    system: str


def artifacts_v1():
    # Reviewed version pins, not hashes supplied by a caller. No env/config
    # switch, network download, tokenizer or production provider registration.
    try:
        profile=Profile.model_validate(strict_json((ROOT/'docs/evaluation/m12c2-profile-drafts.json').read_bytes())['profiles'][0])
        profile.check()
        profile_bytes=canonical(profile.safe_snapshot()).encode('utf8')
        prompt=(ROOT/'docs/evaluation/dynamic-mining-prompt-v1.txt').read_bytes()
        raw_schema=(ROOT/'docs/evaluation/provider-wire-output.schema.json').read_bytes()
        schema=canonical(strict_json(raw_schema)).encode('utf8')
        if (sha(profile_bytes),sha(prompt),sha(schema))!=(PROFILE_SHA,PROMPT_FILE_SHA,SCHEMA_SHA):
            raise ValueError()
        return ArtifactsV1(profile,profile_bytes,prompt,schema,sha(raw_schema),
            prompt.decode('utf8')+SCHEMA_SEPARATOR+schema.decode('utf8'))
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        raise RequestContractError('dynamic_artifact_mismatch') from None


def checked_context(context):
    try:
        if type(context) is not MiningContext: raise ValueError()
        # model_copy(update=...) is not a validation boundary; reparse it.
        current=MiningContext.model_validate_json(canonical(context.payload()))
        if not within_budget(current) or current.input_turn_id!=current.user_turns[0].turn_id: raise ValueError()
        if len({t.turn_id for t in current.user_turns})!=len(current.user_turns): raise ValueError()
        if len({q.question_id for q in current.questions})!=len(current.questions): raise ValueError()
        if len({f.fact_id for f in current.facts})!=len(current.facts): raise ValueError()
        if any(q.state in ('hidden','deleted') and q.content is not None for q in current.questions): raise ValueError()
        if any(f.status=='rejected' and f.statement is not None for f in current.facts): raise ValueError()
        texts=[t.content for t in current.user_turns]+[q.content or '' for q in current.questions]+[f.statement or '' for f in current.facts]
        if any(PRIVATE.search(t) or CREDENTIAL_TEXT.search(t) for t in texts): raise ValueError()
        stop=current.stop
        if (stop.user_stopped or stop.session_ended or stop.round_count>=stop.maximum_rounds
            or stop.consecutive_empty_rounds>=2 or min(stop.round_count,stop.consecutive_empty_rounds,
            current.omitted_turns,current.omitted_facts,current.omitted_questions)<0): raise ValueError()
        return current
    except (ValueError,TypeError,UnicodeError):
        raise RequestContractError('dynamic_context_invalid') from None


@dataclass(frozen=True,slots=True,repr=False)
class BusinessSnapshotV1:
    session_id: UUID
    run_id: UUID
    root_run_id: UUID
    receipt_hash: str
    root_request_tag: str
    operation_hash: str
    context: MiningContext
    lease_until: datetime
    # Exact canonical projection read from 0011, not client supplied. No keys,
    # grant approval, policy body or external-data consent in PreparedRequest.
    metadata_bytes: bytes | None = None


@dataclass(frozen=True,slots=True,repr=False)
class PreparedMiningRequestV1:
    contract_version: int
    config_version: str
    run_id: UUID
    root_run_id: UUID
    context_revision: int
    operation_hash: str
    body: bytes
    request_sha: str
    context_sha: str
    provider: str
    model: str
    expected_version: str
    version_policy: str
    endpoint: str
    region: str
    deployment: str
    mode: str
    structured_mode: str
    output_cap: int
    prompt_version: str
    prompt_file_sha: str
    prompt_sha: str  # FULL system message, including canonical wire Schema
    schema_version: str
    schema_sha: str  # canonical embedded wire Schema, not native line endings
    schema_file_sha: str
    profile_bytes: bytes
    profile_sha: str
    preparation_checks: tuple[str,...]


def prepare_request(snapshot):
    if type(snapshot) is not BusinessSnapshotV1: raise RequestContractError('dynamic_snapshot_invalid')
    context=checked_context(snapshot.context)
    bundle=artifacts_v1()
    request=Adapter(bundle.profile,strict_json(bundle.schema_bytes)).build_request(context)
    request['messages'][0]['content']=bundle.system
    body=canonical(request).encode('utf8')
    p=bundle.profile
    return PreparedMiningRequestV1(1,VERSION,snapshot.run_id,snapshot.root_run_id,context.context_revision,
        snapshot.operation_hash,body,sha(body),sha(canonical(context.payload()).encode('utf8')),
        p.provider,p.api_model,p.version,p.version_policy,ENDPOINT,p.region,p.deployment,p.mode,p.structured_mode,
        p.output_cap,PROMPT_VERSION,sha(bundle.prompt_bytes),sha(bundle.system.encode('utf8')),
        SCHEMA_VERSION,sha(bundle.schema_bytes),bundle.schema_file_sha,bundle.profile_bytes,
        sha(bundle.profile_bytes),CHECKS)
