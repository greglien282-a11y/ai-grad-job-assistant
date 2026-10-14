"""Synthetic-only boundary. No network SDK, keys, model response or prompt storage."""
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.mining_context import MiningContext


class Citation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    turn_id: UUID
    quote: str = Field(min_length=1, max_length=10000)
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)


class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    citation: Citation


class MiningOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidates: list[Candidate] = Field(max_length=5)
    questions: list[str] = Field(max_length=2)
    tokens_in: int = Field(strict=True, ge=0, le=12000, default=0)
    tokens_out: int = Field(strict=True, ge=0, le=1200, default=0)


@dataclass(frozen=True)
class MiningInput:
    turn_id: UUID
    content: str
    # Legacy synthetic compatibility only. Future adapters must use payload().
    context: MiningContext | None = None

    def payload(self):
        if self.context is None:
            raise ValueError('A bounded context is required')
        return self.context.payload()


class SuggestedQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=500)
    purpose: Literal['contribution', 'detail', 'uncertainty', 'verification', 'correction']
    source_turn_ids: list[UUID] = Field(min_length=1, max_length=2)


class AtomicCitation(Citation):
    quote: str = Field(min_length=1, max_length=500)


class AtomicCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    citation: AtomicCitation


class MiningOutputV2(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[2] = 2
    candidates: list[AtomicCandidate] = Field(max_length=5)
    questions: list[SuggestedQuestion] = Field(max_length=2)
    stop: bool = Field(strict=True, default=False)
    stop_reason: Literal['enough_information', 'user_uncertain', 'no_new_information'] | None = None
    tokens_in: int = Field(strict=True, ge=0, le=12000, default=0)
    tokens_out: int = Field(strict=True, ge=0, le=1200, default=0)

    @model_validator(mode='after')
    def stopping(self):
        if self.stop != (self.stop_reason is not None) or (self.stop and self.questions):
            raise ValueError('Stop requires a reason and no next questions')
        if not self.stop and not self.questions:
            raise ValueError('Continue requires one or two questions')
        return self


@dataclass(frozen=True)
class CostReservation:
    provider: str
    maximum_cost: int  # synthetic minor units, NOT an approved real model price


class Provider(Protocol):
    name: str
    synthetic: bool
    def reserve_cost(self) -> CostReservation: ...
    async def mine(self, context: MiningInput) -> MiningOutput | MiningOutputV2: ...


class ScriptedProvider:
    """Deterministic, visibly synthetic. Never calls any external service."""
    name = 'scripted'
    synthetic = True
    output_contract_version = 1

    def reserve_cost(self):
        return CostReservation('scripted', 0)

    async def mine(self, context):
        return MiningOutput(candidates=[Candidate(citation=Citation(turn_id=context.turn_id,
            quote=context.content, start=0, end=len(context.content)))],
            questions=['你本人实际完成了哪一步？记不清也可以跳过。', '是否有能帮助你核对这段经历的材料？'])
