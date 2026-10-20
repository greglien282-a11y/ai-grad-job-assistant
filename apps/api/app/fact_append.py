"""Local all-new batch writer. Call inside a single top-level transaction."""
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import or_, select

from app import facts, fact_maintenance as maintenance, idempotency as idem
from app.append_contract import AppendResult, append_spans
from app.fact_maintenance_models import ConversationOperation, FactChangeSource
from app.maintenance_errors import ConversationError
from app.models import ConversationTurn, ExperienceFact, ExperienceProject, FactChange, FactSource, utcnow


def unavailable():
    raise ConversationError(410, 'conversation_result_unavailable')


def view(db, row):
    """Read immutable after snapshots, never compare them to a later statement."""
    maintenance.available(row)
    maintenance.require_contract(row, 2)
    turn = db.get(ConversationTurn, row.input_turn_id)
    if (turn is None or turn.role != 'user' or turn.session_id != row.session_id
            or row.state != 'applied' or row.outcome_code != 'created'
            or not isinstance(row.proposal_spans, list)
            or row.effect_count != len(row.proposal_spans)):
        unavailable()
    sources = db.scalars(select(FactChangeSource).where(FactChangeSource.operation_id == row.id)
                         .order_by(FactChangeSource.effect_slot)).all()
    if len(sources) != row.effect_count:
        unavailable()
    effects, fact_ids, change_ids = [], set(), set()
    for slot, (source, span) in enumerate(zip(sources, row.proposal_spans), 1):
        change = db.get(FactChange, source.change_id)
        fact = db.get(ExperienceFact, source.fact_id)
        citation = dict(turn_id=str(turn.id), quote=source.quote, start=source.start_cp, end=source.end_cp)
        originals = db.scalars(select(FactSource).where(FactSource.fact_id == source.fact_id)).all()
        if (source.effect_slot != slot or source.source_role != 'statement' or source.reason != 'addition'
                or source.session_id != row.session_id or source.turn_id != turn.id
                or span != dict(role='statement', start=source.start_cp, end=source.end_cp)
                or not 0 <= source.start_cp < source.end_cp <= len(turn.content)
                or source.quote != turn.content[source.start_cp:source.end_cp]
                or source.before_version is not None or source.after_version != 1
                or change is None or fact is None or not isinstance(change.after, dict)
                or change.session_id != row.session_id or fact.session_id != row.session_id
                or change.fact_id != fact.id or change.action != 'created' or change.actor != 'system'
                or change.before is not None or change.after.get('version') != 1
                or change.after.get('status') != 'pending' or change.after.get('statement') != source.quote
                or change.after.get('evidence_id') is not None or change.after.get('origin') != 'manual'
                or change.after.get('ai_run_id') is not None or fact.version < 1
                or len(originals) != 1 or originals[0].session_id != row.session_id
                or originals[0].turn_id != turn.id or originals[0].citations != [citation]
                or change.after.get('citations') != [citation]
                or change.after.get('original_source_turn_ids') != [str(turn.id)]
                or fact.id in fact_ids or change.id in change_ids):
            unavailable()
        fact_ids.add(fact.id); change_ids.add(change.id)
        effects.append(dict(effect_slot=slot, fact_id=fact.id, change_id=change.id,
            before_version=None, after_version=1, applied_status='pending', current_version=fact.version))
    try:
        return AppendResult(contract_version=row.contract_version, operation_id=row.id,
            input_turn_id=turn.id, state=row.state, action=row.action, outcome=row.outcome_code,
            base_revision=row.base_revision, result_revision=row.result_revision,
            effect_count=row.effect_count, effects=effects, provider_calls=0, mining_run_id=None).model_dump()
    except ValidationError:
        unavailable()


def apply(db, sid, token, key, body):
    if db.in_nested_transaction():
        raise ConversationError(503, 'conversation_top_level_required')
    tag = idem.request_tag(key, token, body.model_dump(mode='json'))
    idem.lock(db, key)
    row = maintenance.existing(db, key)
    if row is not None:
        return maintenance.replay(db, sid, token, key, row, tag, version=2), False
    if key.expires_at > utcnow() + idem.WINDOW:
        raise idem.IdempotencyError(422, 'idempotency_clock_skew')
    session = facts.authorize(db, sid, token, lock=True)
    facts.require_legacy(db, sid)
    maintenance.gate(db, session)
    project = db.scalar(select(ExperienceProject).where(ExperienceProject.session_id == sid))
    if project is None:
        raise PermissionError('Resource unavailable')
    if session.context_revision != body.base_revision:
        raise ConversationError(409, 'context_conflict')
    spans = append_spans(body)
    # Temporary D3 restriction includes legacy facts restored after rejection.
    # Neither current status nor a later edit erases a rejected snapshot.
    if db.scalar(select(ExperienceFact.id).where(ExperienceFact.session_id == sid,
                 ExperienceFact.status == 'rejected').limit(1)) or db.scalar(
            select(FactChange.id).where(FactChange.session_id == sid, or_(
                FactChange.before['status'].as_string() == 'rejected',
                FactChange.after['status'].as_string() == 'rejected')).limit(1)):
        raise ConversationError(409, 'append_requires_clarification')
    content = body.input.content
    if db.scalar(select(ConversationTurn.id).where(ConversationTurn.session_id == sid,
                 ConversationTurn.role == 'user', ConversationTurn.content == content).limit(1)):
        raise ConversationError(409, 'conversation_input_already_submitted')
    for statement in body.statements:
        if db.scalar(select(ExperienceFact.id).where(ExperienceFact.session_id == sid,
                     ExperienceFact.statement == statement.quote).limit(1)):
            raise ConversationError(409, 'fact_already_exists')
    turn = facts.add_turn(db, sid, token, content)
    effects = []
    for statement in body.statements:
        citation = dict(turn_id=str(turn.id), quote=statement.quote, start=statement.start, end=statement.end)
        fact = facts.add_fact(db, project.id, token, statement.quote, [turn.id], citations=[citation])
        change = db.scalar(select(FactChange).where(FactChange.fact_id == fact.id, FactChange.action == 'created'))
        if change is None:
            raise ConversationError(500, 'conversation_integrity_failed')
        effects.append((fact, change, statement))
    db.refresh(session)
    row = ConversationOperation(id=uuid4(), contract_version=2, key_digest=key.digest,
        state='applied', session_id=sid, input_turn_id=turn.id, kind='root', action='append',
        submission_tag=maintenance.submission_tag(key, token, content), request_tag=tag,
        proposal_spans=spans, base_revision=body.base_revision, result_revision=session.context_revision,
        effect_count=len(effects), outcome_code='created', decision_contract='append-batch-v1',
        expires_at=key.expires_at)
    db.add(row); db.flush()
    for slot, (fact, change, statement) in enumerate(effects, 1):
        db.add(FactChangeSource(id=uuid4(), operation_id=row.id, effect_slot=slot,
            change_id=change.id, fact_id=fact.id, session_id=sid, turn_id=turn.id,
            source_role='statement', reason='addition', start_cp=statement.start, end_cp=statement.end,
            quote=statement.quote, before_version=None, after_version=1))
    db.flush()
    return view(db, row), True
