"""Explicit read-only contracts. No aliases to legacy FactView or write DTOs."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import ProjectView, TurnView, EvidenceView


class StrictView(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Classification(StrictView):
    fact_kind: Literal['legacy_unspecified','personal_action','plan','background','boundary']
    progress_stage: Literal['legacy_unknown','in_progress','completed','planned','not_applicable']
    classification_contract: Literal['legacy-v0','unclassified-v1','explicit-typed-v1']

    @model_validator(mode='after')
    def finite_pair(self):
        if self.fact_kind=='legacy_unspecified':
            valid=self.progress_stage=='legacy_unknown' and self.classification_contract in ('legacy-v0','unclassified-v1')
        else:
            valid=self.classification_contract=='explicit-typed-v1' and self.progress_stage in {
                'personal_action':('in_progress','completed'), 'plan':('planned','in_progress'),
                'background':('not_applicable',),'boundary':('not_applicable',)}[self.fact_kind]
        if not valid:raise ValueError('Unsupported classification')
        return self


class Citation(StrictView):
    turn_id: UUID
    start: int = Field(strict=True,ge=0)
    end: int = Field(strict=True,gt=0)
    quote: str
    change_id: UUID
    fact_version: int = Field(strict=True,gt=0)
    source_kind: Literal['original_source','conversation_change']


class FactV3(Classification):
    fact_contract_version: Literal[3] = 3
    provenance_version: Literal[3] = 3
    id: UUID
    session_id: UUID
    project_id: UUID
    statement: str
    status: Literal['pending','user_confirmed','evidence_supported','rejected']
    version: int = Field(strict=True,gt=0)
    created_at: datetime
    updated_at: datetime
    origin: Literal['manual','ai_extracted']
    memory_state: Literal['unspecified','certain','approximate','needs_check']
    ai_run_id: UUID | None
    evidence_id: UUID | None
    original_source_turn_ids: list[UUID]
    current_statement_source_turn_ids: list[UUID]
    current_statement_citations: list[Citation]
    classification_citations: list[Citation] = Field(max_length=0)
    classification_basis_status: Literal['legacy_unclassified','not_recorded']
    source_kind: Literal['conversation_turns','user_edit']
    source_change_id: UUID | None


Reason = Literal['classification_unreviewed','action_in_progress','plan_not_contribution',
                 'background_context','boundary_limitation']


class Excluded(StrictView):
    fact: FactV3
    reason: Reason


class SummaryV2(StrictView):
    summary_contract_version: Literal[2] = 2
    project_id: UUID
    context_revision: int = Field(strict=True,gt=0)
    confirmed: list[FactV3]
    pending: list[FactV3]
    reviewed_non_contributions: list[Excluded]
    text: str
    incomplete: bool


class SnapshotClassification(Classification):
    interpretation: Literal['legacy_missing_keys','explicit_fields']


class ChangeBackup(StrictView):
    id: UUID
    session_id: UUID
    fact_id: UUID
    action: Literal['created','edited','status_changed','memory_changed']
    actor: Literal['user','system']
    before: dict | None
    after: dict
    before_classification: SnapshotClassification | None
    after_classification: SnapshotClassification
    created_at: datetime


class SessionBackup(StrictView):
    id: UUID
    status: Literal['active','ended']
    created_at: datetime
    updated_at: datetime
    context_revision: int
    mining_status: Literal['not_started','active','stopped']
    projects: list[ProjectView]
    turns: list[TurnView]
    facts: list[FactV3]
    evidence: list[EvidenceView]
    history: list[ChangeBackup]
    fact_sources: list[dict]
    fact_change_sources: list[dict]
    conversation_operations: list[dict]
    mining_runs: list[dict]
    mining_questions: list[dict]
    answer_questions: list[dict]


class ExportV2(StrictView):
    format_version: Literal[2] = 2
    exported_at: datetime
    data: SessionBackup
