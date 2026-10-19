"""append-batch-v1 / append-personal-v1: extractive local commands only."""
import re
from typing import Literal
from uuid import UUID

from pydantic import Field

from app import schemas
from app.maintenance_contract import Span, UserInput
from app.maintenance_errors import ConversationError
from app.mining_validation import COMPOSITE, UNCLEAR, sentence_spans


class AppendCommand(schemas.Input):
    contract_version: int = Field(strict=True, ge=2, le=2)
    base_revision: schemas.Version
    action: Literal['append']
    input: UserInput
    statements: list[Span] = Field(min_length=1, max_length=5)


class AppendEffect(schemas.Input):
    effect_slot: int = Field(strict=True, ge=1, le=5)
    fact_id: UUID
    change_id: UUID
    before_version: None
    after_version: Literal[1]
    applied_status: Literal['pending']
    current_version: schemas.Version


class AppendResult(schemas.Input):
    contract_version: Literal[2]
    operation_id: UUID
    input_turn_id: UUID
    state: Literal['applied']
    action: Literal['append']
    outcome: Literal['created']
    base_revision: schemas.Version
    result_revision: schemas.Version
    effect_count: int = Field(strict=True, ge=1, le=5)
    effects: list[AppendEffect] = Field(min_length=1, max_length=5)
    provider_calls: Literal[0]
    mining_run_id: None


# Finite positive grammar, stricter than the historical atomic() heuristic.
# Requiring explicit 了 avoids interpreting an intention as an accomplished act.
ACTION = re.compile(r'^(?:我|本人)(?:实现|设计|开发|测试|部署|制作|编写|优化|搭建|维护|验证|完成|整理)了[^。！？!?\r\n]+[。！？!?]$')
UNSAFE = re.compile(r'不|没|未|无|否|别|莫|勿|将|要|准备|希望|想|拟|正在|曾否|听说|据说|声称|所谓|[“”"「」『』<>]|(?:\bnot\b|\bnever\b)', re.I)
ACTION_WORD = re.compile(r'实现|设计|开发|测试|部署|制作|编写|优化|搭建|维护|验证|完成|整理|负责|做')


def personal_v1(quote):
    return (len(quote) <= 500 and bool(ACTION.fullmatch(quote))
            and len(ACTION_WORD.findall(quote)) == 1
            and not COMPOSITE.search(quote) and not UNCLEAR.search(quote)
            and not UNSAFE.search(quote))


def append_spans(body):
    content = body.input.content
    try:
        content.encode('utf-8')
    except UnicodeEncodeError:
        raise ConversationError(422, 'append_source_invalid') from None
    if '\x00' in content:
        raise ConversationError(422, 'append_source_invalid')
    sentences = set(sentence_spans(content))
    cursor, seen, result = 0, set(), []
    for span in body.statements:
        start, end, quote = span.start, span.end, span.quote
        if (start < cursor or start >= end or end > len(content)
                or content[cursor:start].strip() or content[start:end] != quote
                or (start, end, quote) not in sentences or not personal_v1(quote)):
            raise ConversationError(422, 'append_source_invalid')
        if quote in seen:
            raise ConversationError(422, 'append_duplicate_statement')
        seen.add(quote)
        result.append(dict(role='statement', start=start, end=end))
        cursor = end
    if content[cursor:].strip():
        raise ConversationError(422, 'append_source_invalid')
    return result
