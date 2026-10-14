"""Public contracts; credential storage fields are deliberately absent."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import FactStatus

TextInput = Annotated[str, StringConstraints(min_length=1, max_length=10000)]
Version = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Blank text is not allowed")
        return value


class CreateSession(Input):
    raw_input: TextInput


class AddTurn(Input):
    content: TextInput


class AddFact(Input):
    statement: TextInput
    source_turn_ids: list[UUID] = Field(min_length=1, max_length=32)


class EditFact(Input):
    action: Literal["edit"]
    expected_version: Version
    statement: TextInput


class ConfirmFact(Input):
    action: Literal["confirm"]
    expected_version: Version


class RejectFact(Input):
    action: Literal["reject"]
    expected_version: Version


class VerifyFact(Input):
    action: Literal["verify_material"]
    expected_version: Version
    material_reference: TextInput
    basis: TextInput


class SetMemory(Input):
    action: Literal['set_memory']
    expected_version: Version
    memory_state: Literal['unspecified','certain','approximate','needs_check']


FactMutation = Annotated[EditFact | ConfirmFact | RejectFact | VerifyFact | SetMemory, Field(discriminator="action")]


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CreatedSession(Output):
    session_id: UUID
    project_id: UUID
    initial_turn_id: UUID
    status: Literal["active", "ended"]
    access_token: str


class ProjectView(Output):
    id: UUID
    session_id: UUID
    raw_input: str
    title: str | None
    created_at: datetime


class AnswerQuestionView(Output):
    question_id: UUID
    question_version: int


class TurnView(Output):
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    answered_questions: list[AnswerQuestionView] = Field(default_factory=list)


class FactView(Output):
    id: UUID
    project_id: UUID
    session_id: UUID
    statement: str
    status: FactStatus
    version: int
    created_at: datetime
    updated_at: datetime
    original_source_turn_ids: list[UUID]
    source_kind: Literal["conversation_turns", "user_edit"]
    source_turn_ids: list[UUID]
    source_change_id: UUID | None
    evidence_id: UUID | None
    origin: Literal['manual','ai_extracted'] = 'manual'
    memory_state: Literal['unspecified','certain','approximate','needs_check'] = 'unspecified'
    ai_run_id: UUID | None = None
    citations: list[dict] = Field(default_factory=list)


class EvidenceView(Output):
    id: UUID
    fact_id: UUID
    material_reference: str
    basis: str
    reviewer: Literal["user"]
    created_at: datetime
    verification_label: str = "用户提供材料并自行核实"


class ChangeView(Output):
    id: UUID
    fact_id: UUID
    action: str
    actor: Literal["user", "system"]
    before: dict | None
    after: dict
    created_at: datetime


class MiningQuestionView(Output):
    id: UUID
    state: Literal['active','skipped','corrected','hidden','deleted']
    version: int
    content: str | None


class MiningRunView(Output):
    id: UUID
    session_id: UUID
    project_id: UUID
    input_turn_id: UUID
    base_revision: int
    reserved_revision: int
    state: Literal['reserved','running','completed','failed','unknown','stale']
    lease_until: datetime
    error_code: str | None
    retry_of: UUID | None
    provider: Literal['scripted']
    synthetic: Literal[True]
    questions: list[MiningQuestionView]
    candidate_fact_ids: list[UUID]
    answered_questions: list[AnswerQuestionView] = Field(default_factory=list)


class ExperienceSummary(Output):
    project_id: UUID
    context_revision: int
    confirmed: list[FactView]
    pending: list[FactView]
    text: str
    incomplete: bool


class SessionView(Output):
    id: UUID
    status: Literal["active", "ended"]
    created_at: datetime
    updated_at: datetime
    context_revision: int = 1
    mining_status: Literal['not_started','active','stopped'] = 'not_started'
    projects: list[ProjectView]
    turns: list[TurnView]
    facts: list[FactView]
    evidence: list[EvidenceView]
    history: list[ChangeView]
    mining_runs: list[MiningRunView] = Field(default_factory=list)


class SessionExport(Output):
    format_version: Literal[1] = 1
    exported_at: datetime
    data: SessionView
