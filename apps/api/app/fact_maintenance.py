"""One top-level local transaction per explicit command. No Provider or repair.

Callers own the transaction. Recovery is a projection of immutable receipts;
it never invokes this writer, takes its advisory locks, or renews deadlines.
"""
import hmac
from uuid import uuid4

from sqlalchemy import select

from app import facts, idempotency as idem
from app.fact_maintenance_models import ConversationOperation, FactChangeSource
from app.maintenance_contract import command_spans, quotes, same_atomic_claim
from app.maintenance_errors import ConversationError
from app.maintenance_guard import rejected_contribution
from app.models import ConversationTurn, ExperienceFact, ExperienceProject, FactChange, MiningRun, utcnow

KIND = 'conversation_maintenance_v1'


def submission_tag(key, token, content):
    # Versioned domain separation; only the original content is retained in Turn.
    return idem.request_tag(key, token, {'submission_contract': 1, 'content': content})


def existing(db, key):
    return db.scalar(select(ConversationOperation).where(ConversationOperation.key_digest == key.digest)
                     .execution_options(populate_existing=True))


def available(row):
    if row.state == 'deleted':
        raise ConversationError(410, 'conversation_resource_deleted')
    if row.expires_at <= utcnow():
        raise ConversationError(410, 'conversation_operation_expired')


def require_contract(row, version=1):
    valid = (row.contract_version == version and (
        (version == 1 and row.decision_contract == 'explicit-target-v1'
         and ((row.kind == 'root' and row.action in ('append', 'correct', 'withdraw', 'disambiguate'))
              or (row.kind == 'resolution' and row.action in ('correct', 'withdraw'))))
        or (version == 2 and row.decision_contract == 'append-batch-v1'
            and row.kind == 'root' and row.action == 'append')))
    if not valid:
        raise ConversationError(409, 'conversation_contract_mismatch')


def view(db, row, *, version=1):
    available(row)
    require_contract(row, version)
    if version == 2:
        from app.fact_append import view as append_view
        return append_view(db, row)
    turn = db.get(ConversationTurn, row.input_turn_id)
    if turn is None or turn.session_id != row.session_id or turn.role != 'user':
        raise ConversationError(410, 'conversation_result_unavailable')
    sources = db.scalars(select(FactChangeSource).where(FactChangeSource.operation_id == row.id)
                         .order_by(FactChangeSource.effect_slot, FactChangeSource.source_role)).all()
    effects = {}
    for source in sources:
        change = db.get(FactChange, source.change_id)
        fact = db.get(ExperienceFact, source.fact_id)
        if (change is None or fact is None or change.session_id != row.session_id
                or change.fact_id != fact.id or change.after.get('version') != source.after_version):
            raise ConversationError(410, 'conversation_result_unavailable')
        effects[source.effect_slot] = dict(fact_id=fact.id, change_id=change.id,
            before_version=source.before_version, after_version=source.after_version,
            applied_status=change.after['status'], current_version=fact.version)
    if len(effects) != row.effect_count:
        raise ConversationError(410, 'conversation_result_unavailable')
    child = db.scalar(select(ConversationOperation.id).where(
        ConversationOperation.parent_operation_id == row.id, ConversationOperation.state != 'deleted'))
    return dict(contract_version=1, operation_id=row.id, input_turn_id=row.input_turn_id,
        state=row.state, action=row.action, outcome=row.outcome_code,
        base_revision=row.base_revision, result_revision=row.result_revision,
        parent_operation_id=row.parent_operation_id, resolved_by=child,
        effects=[effects[k] for k in sorted(effects)], provider_calls=0, mining_run_id=None)


def replay(db, sid, token, key, row, tag=None, *, version=1):
    available(row)
    facts.authorize(db, sid, token)
    if row.session_id != sid:
        raise PermissionError('Resource unavailable')
    require_contract(row, version)
    if tag is not None and not hmac.compare_digest(tag, row.request_tag):
        raise idem.IdempotencyError(409, 'idempotency_payload_mismatch')
    key.fresh()
    return view(db, row, version=version)


def recover(db, sid, token, *, key=None, oid=None, version=1):
    # No locks, expiry cleanup, clock registration, writes or provider access.
    row = existing(db, key) if key else db.get(ConversationOperation, oid)
    if row is None:
        facts.authorize(db, sid, token)
        raise ConversationError(404, 'conversation_operation_not_found')
    if key:
        return replay(db, sid, token, key, row, version=version)
    facts.authorize(db, sid, token)
    if row.session_id != sid:
        raise PermissionError('Resource unavailable')
    return view(db, row, version=version)


def gate(db, session):
    if session.status != 'active':
        raise ConversationError(409, 'session_ended')
    # Keep 0013's conservative unresolved-run contract, including old unknowns.
    if db.scalar(select(MiningRun.id).where(MiningRun.session_id == session.id,
                     MiningRun.state.in_(('reserved', 'running', 'unknown'))).limit(1)):
        raise ConversationError(409, 'mining_result_unresolved')


def target(db, sid, pid, tid, version, revision, session):
    fact = db.scalar(select(ExperienceFact).where(ExperienceFact.id == tid,
        ExperienceFact.session_id == sid, ExperienceFact.project_id == pid).execution_options(populate_existing=True))
    if fact is None:
        raise PermissionError('Resource unavailable')
    if fact.version != version:
        raise facts.VersionConflict()
    if fact.status == 'rejected':
        raise ConversationError(409, 'fact_rejected_immutable')
    if session.context_revision != revision:
        raise ConversationError(409, 'context_conflict')
    return fact


def identity(fact, action, values):
    if action == 'correct' and not same_atomic_claim(fact.statement, values[1]):
        raise ConversationError(422, 'correction_identity_unresolved')


def apply(db, sid, token, key, body, *, parent_id=None):
    if db.in_nested_transaction():
        raise ConversationError(503, 'conversation_top_level_required')
    canonical = body.model_dump(mode='json')
    if parent_id is not None:
        canonical = dict(resolution=canonical, parent_operation_id=str(parent_id))
    tag = idem.request_tag(key, token, canonical)
    idem.lock(db, key)
    row = existing(db, key)
    if row is not None:
        return replay(db, sid, token, key, row, tag), False
    if key.expires_at > utcnow() + idem.WINDOW:
        # 0013 also limits a receipt to 24h after its server creation. A key
        # minted in the future is not eligible for a new write yet.
        raise idem.IdempotencyError(422, 'idempotency_clock_skew')
    session = facts.authorize(db, sid, token, lock=True)
    facts.require_legacy(db, sid)
    gate(db, session)
    project = db.scalar(select(ExperienceProject).where(ExperienceProject.session_id == sid))
    if project is None:
        raise PermissionError('Resource unavailable')
    parent = None
    if parent_id is not None:
        parent = db.scalar(select(ConversationOperation).where(ConversationOperation.id == parent_id,
            ConversationOperation.session_id == sid).with_for_update())
        if parent is None:
            raise PermissionError('Resource unavailable')
        available(parent)
        require_contract(parent)
        if parent.kind != 'root' or parent.state != 'needs_clarification':
            raise ConversationError(409, 'conversation_resolution_invalid')
        if db.scalar(select(ConversationOperation.id).where(ConversationOperation.parent_operation_id == parent.id)):
            raise ConversationError(409, 'conversation_resolution_already_applied')
        turn = db.get(ConversationTurn, parent.input_turn_id)
        if turn is None or turn.session_id != sid or turn.role != 'user':
            raise ConversationError(410, 'conversation_result_unavailable')
        content, spans, action = turn.content, parent.proposal_spans, parent.proposed_action
        values = quotes(content, spans, action)
        fact = target(db, sid, project.id, body.selected_fact_id, body.expected_version, body.base_revision, session)
        identity(fact, action, values)
    else:
        content, action = body.input.content, body.proposed_action or body.action
        # Target authorization/version priority precedes context/source errors.
        fact = None
        if body.target is not None:
            fact = target(db, sid, project.id, body.target.fact_id, body.target.expected_version, body.base_revision, session)
        elif session.context_revision != body.base_revision:
            raise ConversationError(409, 'context_conflict')
        spans = command_spans(body)
        values = quotes(content, spans, action)
        if fact is not None:
            identity(fact, action, values)
        else:
            candidates = db.scalars(select(ExperienceFact).where(ExperienceFact.project_id == project.id,
                ExperienceFact.status != 'rejected')).all()
            if action == 'correct':
                candidates = [f for f in candidates if same_atomic_claim(f.statement, values[1])]
            if len(candidates) < 2:
                raise ConversationError(422, 'correction_identity_unresolved')
        if db.scalar(select(ConversationTurn.id).where(ConversationTurn.session_id == sid,
                         ConversationTurn.role == 'user', ConversationTurn.content == content).limit(1)):
            raise ConversationError(409, 'conversation_input_already_submitted')
        if action == 'correct':
            rejected_contribution(db, sid, values[1], exclude=fact.id if fact else None)
        # No writes before all input/ownership/version/identity checks pass.
        turn = facts.add_turn(db, sid, token, content)
    if action == 'correct':
        rejected_contribution(db, sid, values[1], exclude=fact.id if fact else None)
    change = None
    if fact is not None:
        version = fact.version
        if action == 'correct':
            facts.change_fact(db, fact.id, token, statement=values[1], expected_version=version)
        else:
            facts.change_fact(db, fact.id, token, status='rejected', expected_version=version, withdraw=True)
        change = db.scalar(select(FactChange).where(FactChange.fact_id == fact.id,
            FactChange.after['version'].as_integer() == fact.version))
        if change is None:
            raise ConversationError(500, 'conversation_integrity_failed')
    db.refresh(session)
    row = ConversationOperation(id=uuid4(), key_digest=key.digest,
        state='applied' if fact else 'needs_clarification', session_id=sid, input_turn_id=turn.id,
        kind='resolution' if parent else 'root', action=action if fact else 'disambiguate',
        parent_operation_id=parent.id if parent else None,
        submission_tag=None if parent else submission_tag(key, token, content), request_tag=tag,
        proposed_action=None if fact else action, proposal_spans=spans,
        base_revision=body.base_revision, result_revision=session.context_revision,
        target_fact_id=fact.id if fact else None, target_version=version if fact else None,
        effect_count=1 if fact else 0, outcome_code=('corrected' if action == 'correct' else 'withdrawn') if fact else 'target_ambiguous',
        decision_contract='explicit-target-v1', expires_at=key.expires_at)
    db.add(row); db.flush()
    if fact:
        for span, quote in zip(spans, values):
            db.add(FactChangeSource(id=uuid4(), operation_id=row.id, effect_slot=1,
                change_id=change.id, fact_id=fact.id, session_id=sid, turn_id=turn.id,
                source_role=span['role'], reason='explicit_correction' if action == 'correct' else 'explicit_withdrawal',
                start_cp=span['start'], end_cp=span['end'], quote=quote,
                before_version=version, after_version=fact.version))
    db.flush()
    # Deferred checks still run at the top-level COMMIT, before HTTP success.
    return view(db, row), True
