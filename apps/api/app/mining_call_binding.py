"""Versioned metadata contract only. No ORM registration, IO or paid admission.

The executable PostgreSQL prototype lives under tests and is not a migration.
Scopes are service-issued pseudonyms, not assertions of a real person's identity.
"""
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SHA = r'^[a-f0-9]{64}$'


class MiningCallBindingV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    contract_version: Literal[1]
    run_id: UUID
    root_run_id: UUID
    operation_hash: str = Field(pattern=SHA)
    receipt_hash: str = Field(pattern=SHA)
    actor_scope: str = Field(pattern=SHA)
    session_scope: str = Field(pattern=SHA)
    ledger_id: UUID
    call_id: UUID
    grant_id: UUID
    provider: Literal['deepseek_official']
    model: Literal['deepseek-flash']
    profile_version: Literal['fixed-fixture-binding-v1']
    request_sha: str = Field(pattern=SHA)
    policy_sha: str = Field(pattern=SHA)
    context_sha: str = Field(pattern=SHA)
    prompt_sha: str = Field(pattern=SHA)
    schema_sha: str = Field(pattern=SHA)
    binding_state: Literal['bound', 'tombstoned']
    created_at: AwareDatetime
    tombstoned_at: AwareDatetime | None

    @model_validator(mode='after')
    def tombstone_time(self):
        if (self.binding_state == 'tombstoned') != (self.tombstoned_at is not None):
            raise ValueError('binding_tombstone_time_invalid')
        if self.tombstoned_at is not None and self.tombstoned_at < self.created_at:
            raise ValueError('binding_tombstone_time_invalid')
        return self
