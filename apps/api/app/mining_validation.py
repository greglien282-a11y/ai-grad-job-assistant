"""Conservative v2 extractive guard. This is not a general semantic classifier."""
import re
import unicodedata

from sqlalchemy import select
from app.mining_context import PRIVATE, build_context
from app.mining_provider import MiningOutputV2
from app.models import ConversationTurn, ExperienceSession, FactSource, MiningQuestion

# Whole simple sentence only: never cut away a qualifier/negation/team clause.
SENTENCE = re.compile(r'[^。！？!?\n]+[。！？!?]?(?:\n|$)|[^。！？!?\n]+[。！？!?]')
COMPOSITE = re.compile(r'[,，;；、]|以及|并|同时|然后|(?:\band\b|\bthen\b)|和|及|与', re.I)
UNCLEAR = re.compile(r'团队|我们|如果|假如|假设|计划|打算|可能|也许|猜|估计|似乎|大概|记不清|不确定|忘记|\b(?:team|we|if|would|maybe|forgot|unsure|guess)\b', re.I)
PERSONAL = re.compile(r'^(?:合成[：:]\s*)?(?:我|本人|I\b)', re.I)


def sentence_spans(content):
    # finditer preserves Python Unicode code-point positions, including emoji.
    for match in SENTENCE.finditer(content):
        text = match.group().strip()
        if text:
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            yield start, start + len(text), text


def atomic(text):
    actions = re.findall(r'实现|设计|开发|测试|部署|制作|编写|优化|搭建|维护|验证|完成|做|负责|\b(?:built|implemented|tested|deployed|designed|wrote)\b', text, re.I)
    if len(actions) > 1: actions = [a for a in actions if a not in ('负责', '做')]
    return len(text) <= 500 and len(actions) == 1 and bool(PERSONAL.search(text)) and not COMPOSITE.search(text) and not UNCLEAR.search(text)


def question_key(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def validate_context_v2(context, output, previous_questions=()):
    """Pure snapshot checks shared by DB mining and the offline HTTP bridge.

    Does not grant publication: live mining additionally checks real DB user
    turns, project ownership, revisions, lease and session state in complete().
    """
    result = MiningOutputV2.model_validate(output)
    included = {t.turn_id: t for t in context.user_turns}
    seen = set()
    for candidate in result.candidates:
        c = candidate.citation
        turn = included.get(c.turn_id)
        if (turn is None or c.end > len(turn.content) or c.start >= c.end
            or turn.content[c.start:c.end] != c.quote or PRIVATE.search(c.quote)
            or (c.start, c.end, c.quote) not in set(sentence_spans(turn.content)) or not atomic(c.quote)):
            raise ValueError('Invalid atomic source')
        identity = (c.turn_id, c.start, c.end)
        if identity in seen: raise ValueError('Repeated candidate')
        seen.add(identity)
    previous = set(previous_questions) | {question_key(q.content) for q in context.questions if q.content}
    keys = set()
    for q in result.questions:
        key = question_key(q.text)
        if (not key or PRIVATE.search(q.text) or len(set(q.source_turn_ids)) != len(q.source_turn_ids)
            or any(tid not in included for tid in q.source_turn_ids)):
            raise ValueError('Invalid clarification')
        if key in previous or key in keys: raise ValueError('Repeated clarification')
        supported_numbers = set(re.findall(r'\d+(?:\.\d+)?', ' '.join(included[tid].content for tid in q.source_turn_ids)))
        if not set(re.findall(r'\d+(?:\.\d+)?', q.text)) <= supported_numbers:
            raise ValueError('Unsupported number in clarification')
        keys.add(key)
    return result


def validate_v2(db, run, output, context=None):
    result = MiningOutputV2.model_validate(output)
    context = context or build_context(db, run, db.get(ExperienceSession, run.session_id))
    if context.project_id != run.project_id or context.input_turn_id != run.input_turn_id or context.context_revision != run.reserved_revision:
        raise ValueError('Invalid snapshot identity')
    included = {t.turn_id: t for t in context.user_turns}
    for candidate in result.candidates:
        c = candidate.citation
        turn = db.get(ConversationTurn, c.turn_id)
        if (c.turn_id not in included or turn is None or turn.session_id != run.session_id or turn.role != 'user'
            or c.end > len(turn.content) or c.start >= c.end or turn.content[c.start:c.end] != c.quote
            or included[c.turn_id].content[c.start:c.end] != c.quote or PRIVATE.search(c.quote)
            or (c.start, c.end, c.quote) not in set(sentence_spans(turn.content)) or not atomic(c.quote)):
            raise ValueError('Invalid atomic source')
    # Suppress repeat questions (including skipped/hidden/current corrections).
    # Deleted wording is gone: never resurrect it in a snapshot or hash cache.
    previous = {question_key(q.content) for q in db.scalars(select(MiningQuestion).where(MiningQuestion.session_id == run.session_id)) if q.content}
    return validate_context_v2(context, result, previous)


def source_already_used(db, run, citation):
    # Overlap also blocks re-extracting part of an edited/rejected legacy turn.
    for source in db.scalars(select(FactSource).where(FactSource.session_id == run.session_id, FactSource.turn_id == citation.turn_id)):
        if not source.citations:
            return True  # Manual turn provenance has no reliable finer span.
        for previous in source.citations:
            if previous['turn_id'] == str(citation.turn_id) and citation.start < previous['end'] and previous['start'] < citation.end:
                return True
    return False
