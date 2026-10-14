"""Synthetic-only boundary. No network SDK, keys, model response or prompt storage."""
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    # Only the selected immutable user turn goes to this phase's provider.


@dataclass(frozen=True)
class CostReservation:
    provider: str
    maximum_cost: int  # synthetic minor units, NOT an approved real model price


class Provider(Protocol):
    name: str
    synthetic: bool
    def reserve_cost(self) -> CostReservation: ...
    async def mine(self, context: MiningInput) -> MiningOutput: ...


class ScriptedProvider:
    """Deterministic, visibly synthetic. Never calls any external service."""
    name = 'scripted'
    synthetic = True

    def reserve_cost(self):
        return CostReservation('scripted', 0)

    async def mine(self, context):
        return MiningOutput(candidates=[Candidate(citation=Citation(turn_id=context.turn_id,
            quote=context.content, start=0, end=len(context.content)))],
            questions=['你本人实际完成了哪一步？记不清也可以跳过。', '是否有能帮助你核对这段经历的材料？'])
