"""Explicit-target v1: local, bounded syntax; no free-language interpretation."""
import re
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app import schemas
from app.maintenance_errors import ConversationError
from app.mining_validation import atomic, sentence_spans


class Span(schemas.Input):
    start: int = Field(strict=True, ge=0, le=10000)
    end: int = Field(strict=True, gt=0, le=10000)
    quote: schemas.TextInput


class UserInput(schemas.Input):
    content: schemas.TextInput


class Target(schemas.Input):
    fact_id: UUID
    expected_version: schemas.Version


class Command(schemas.Input):
    contract_version: int = Field(strict=True, ge=1, le=1)
    base_revision: schemas.Version
    action: Literal['correct', 'withdraw', 'disambiguate']
    input: UserInput
    target: Target | None = None
    intent_span: Span
    statements: list[Span] = Field(default_factory=list, max_length=1)
    proposed_action: Literal['correct', 'withdraw'] | None = None
    progress_stage: None = None

    @model_validator(mode='after')
    def shape(self):
        if self.action == 'disambiguate':
            if self.target is not None or self.proposed_action is None:
                raise ValueError('Invalid disambiguation')
        elif self.target is None or self.proposed_action is not None:
            raise ValueError('Explicit target required')
        if len(self.statements) != (1 if (self.proposed_action or self.action) == 'correct' else 0):
            raise ValueError('Invalid statement count')
        return self


class Resolution(schemas.Input):
    contract_version: int = Field(strict=True, ge=1, le=1)
    base_revision: schemas.Version
    selected_fact_id: UUID
    expected_version: schemas.Version


INTENTS = {
    'correct': frozenset(('纠正上一条。', '更正这条事实。', '更正数量。')),
    'withdraw': frozenset(('撤回上一条。', '撤回这条事实。')),
}
NUMBER = re.compile(r'[0-9]+(?:\.[0-9]+)?')
COUNT_CLAIM = re.compile(r'(?P<head>.+了)(?P<count>[0-9]+)(?P<unit>个|条|张|次)(?P<object>[^0-9]+)')


def quotes(content, spans, action):
    """Spans must cover all non-whitespace input, with complete statements.

    Never discard a negation/hypothesis outside a selected subspan. Explicit
    intent templates are intentionally finite and must occupy the first span.
    """
    try:
        content.encode('utf-8')
    except UnicodeEncodeError:
        raise ConversationError(422, 'conversation_source_invalid') from None
    if action not in INTENTS:
        raise ConversationError(422, 'correction_intent_invalid')
    expected_roles = ['intent', 'statement'] if action == 'correct' else ['intent']
    if [s['role'] for s in spans] != expected_roles:
        raise ConversationError(422, 'conversation_source_invalid')
    result = []
    cursor = 0
    for span in spans:
        start, end = span['start'], span['end']
        if (type(start) is not int or type(end) is not int or start < cursor
                or start >= end or end > len(content) or content[cursor:start].strip()):
            raise ConversationError(422, 'conversation_source_invalid')
        result.append(content[start:end])
        cursor = end
    if content[cursor:].strip():
        raise ConversationError(422, 'conversation_source_invalid')
    intent = result[0]
    if '撤回' in intent and any(word in content for word in ('新增', '补充', '改为另一职责')):
        raise ConversationError(422, 'composite_operation_not_supported')
    if intent not in INTENTS[action]:
        raise ConversationError(422, 'correction_intent_invalid')
    if action == 'correct':
        start, end = spans[1]['start'], spans[1]['end']
        if (not atomic(result[1]) or (start, end, result[1]) not in set(sentence_spans(content))):
            raise ConversationError(422, 'conversation_source_invalid')
    return result


def command_spans(body):
    spans = [dict(role='intent', start=body.intent_span.start, end=body.intent_span.end)]
    spans += [dict(role='statement', start=s.start, end=s.end) for s in body.statements]
    result = quotes(body.input.content, spans, body.proposed_action or body.action)
    supplied = [body.intent_span.quote] + [s.quote for s in body.statements]
    if result != supplied:
        raise ConversationError(422, 'conversation_source_invalid')
    return spans


def same_atomic_claim(old, new):
    """Supported identity contract: one explicit cardinal count differs.

    The count must immediately follow 了 and precede a known classifier.
    Ordinals, identifiers, dates, decimals or additional numbers are not this
    contract. This preserves every other code point; it is not general NLP.
    """
    a, b = COUNT_CLAIM.fullmatch(old), COUNT_CLAIM.fullmatch(new)
    return (old != new and atomic(old) and atomic(new) and a is not None and b is not None
            and len(NUMBER.findall(old)) == len(NUMBER.findall(new)) == 1
            and (a['head'], a['unit'], a['object']) == (b['head'], b['unit'], b['object']))
