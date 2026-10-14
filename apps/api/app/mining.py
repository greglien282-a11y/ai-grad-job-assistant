"""Short transaction state machine. A provider never runs inside a DB transaction."""
import asyncio
import hmac
from datetime import timedelta

from sqlalchemy import delete, event, func, select, update

from app import facts, idempotency as idem
from app.models import ConversationTurn, ExperienceFact, ExperienceProject, ExperienceSession, FactSource, MiningCapacity, MiningQuestion, MiningReceipt, MiningRun, utcnow
from app.mining_provider import MiningInput, MiningOutput, Provider

LEASE_SECONDS = 60
CALL_TIMEOUT_SECONDS = 45
ACTIVE = ('reserved', 'running')
RETRYABLE = ('failed', 'unknown', 'stale')


class MiningError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def safe_provider(provider: Provider | None):
    if provider is None:
        raise MiningError(503, 'ai_disabled')
    # Future adapters/prices require another reviewed implementation and authorization.
    reservation = provider.reserve_cost()
    if not provider.synthetic or provider.name != 'scripted' or reservation.provider != 'scripted' or reservation.maximum_cost != 0:
        raise MiningError(503, 'ai_provider_unapproved')


def effective_state(run):
    # Projection only: recovery GET never writes, expires a lease or invokes a provider.
    return 'unknown' if run.state in ACTIVE and run.lease_until <= utcnow() else run.state


def view(db, run):
    questions = db.scalars(select(MiningQuestion).where(MiningQuestion.run_id == run.id).order_by(MiningQuestion.created_at, MiningQuestion.id)).all()
    candidate_ids = db.scalars(select(ExperienceFact.id).where(ExperienceFact.ai_run_id == run.id).order_by(ExperienceFact.id)).all()
    return dict(id=run.id, session_id=run.session_id, project_id=run.project_id, input_turn_id=run.input_turn_id,
        base_revision=run.base_revision, reserved_revision=run.reserved_revision, state=effective_state(run),
        lease_until=run.lease_until, error_code=('lease_expired' if run.state in ACTIVE and effective_state(run)=='unknown' else run.error_code), retry_of=run.retry_of,
        provider=run.provider, synthetic=True, questions=[dict(id=q.id, state=q.state, version=q.version, content=q.content) for q in questions],
        candidate_fact_ids=list(candidate_ids))


def receipt(db, key, tag=None):
    row = db.get(MiningReceipt, key.digest)
    if row is None:
        return None
    if row.state == 'deleted':
        raise MiningError(410, 'mining_resource_deleted')
    if tag is not None and not hmac.compare_digest(row.request_tag, tag):
        raise idem.IdempotencyError(409, 'idempotency_payload_mismatch')
    return db.get(MiningRun, row.run_id)


def get_run(db, sid, token, rid, *, lock=True):
    facts.authorize(db, sid, token, lock=lock)
    run = db.get(MiningRun, rid)
    if run is None or run.session_id != sid:
        raise PermissionError('Resource unavailable')
    return run


def recover(db, sid, token, key):
    facts.authorize(db, sid, token)
    run = receipt(db, key)
    if run is None:
        raise MiningError(404, 'mining_operation_not_found')
    if run.session_id != sid:
        raise PermissionError('Resource unavailable')
    return view(db, run)


def reserve(factory, sid, token, key, body):
    """Key + answer + reserved run commit once; replay never changes revision."""
    with factory() as db, db.begin():
        idem.lock(db, key)
        # Global DB mutex makes concurrency and per-session admission atomic.
        if db.scalar(select(MiningCapacity).where(MiningCapacity.id == 1).with_for_update()) is None:
            raise MiningError(503, 'mining_capacity_unavailable')
        session = facts.authorize(db, sid, token, lock=True)
        tag = idem.request_tag(key, token, body.model_dump(mode='json'))
        existing = receipt(db, key, tag)
        if existing:
            return existing.id, False
        if session.status != 'active' or session.mining_status == 'stopped':
            raise MiningError(409, 'mining_stopped')
        if session.context_revision != body.base_revision:
            raise MiningError(409, 'context_conflict')
        project = db.get(ExperienceProject, body.project_id)
        if project is None or project.session_id != sid:
            raise PermissionError('Resource unavailable')
        # Lease reclamation is a WRITE operation; expiry never permits a late worker.
        db.execute(update(MiningRun).where(MiningRun.state.in_(ACTIVE), MiningRun.lease_until <= utcnow())
                   .values(state='unknown', error_code='lease_expired'))
        if db.scalar(select(func.count()).select_from(MiningRun).where(MiningRun.session_id == sid, MiningRun.state.in_(ACTIVE))):
            raise MiningError(409, 'mining_busy')
        if db.scalar(select(func.count()).select_from(MiningRun).where(MiningRun.state.in_(ACTIVE))) >= 2:
            raise MiningError(429, 'mining_capacity')
        if db.scalar(select(func.count()).select_from(MiningRun).where(MiningRun.session_id == sid)) >= 12:
            raise MiningError(429, 'mining_attempt_limit')
        latest = db.scalars(select(MiningRun).where(MiningRun.session_id == sid).order_by(MiningRun.created_at.desc(), MiningRun.id.desc()).limit(1)).first()
        if latest is not None and latest.state in RETRYABLE and not body.retry_of:
            raise MiningError(409, 'mining_retry_requires_confirmation')
        retries = None
        if body.retry_of:
            previous = get_run(db, sid, token, body.retry_of)
            if not body.confirm_retry or effective_state(previous) not in RETRYABLE:
                raise MiningError(409, 'mining_retry_requires_confirmation')
            if db.scalar(select(MiningRun.id).where(MiningRun.retry_of == previous.id)):
                raise MiningError(409, 'mining_retry_superseded')
            turn = db.get(ConversationTurn, previous.input_turn_id)
            if previous.project_id != body.project_id:
                raise PermissionError('Resource unavailable')
            retries = previous.id
        elif body.input_turn_id:
            turn = db.get(ConversationTurn, body.input_turn_id)
            # Initial mining only: existing submitted answers must use explicit retry.
            if db.scalar(select(func.count()).select_from(MiningRun).where(MiningRun.input_turn_id == body.input_turn_id)):
                raise MiningError(409, 'mining_input_already_submitted')
        else:
            # A new key cannot conceal a lost committed answer. Use recovery/retry.
            duplicate = db.scalar(select(MiningRun.id).join(ConversationTurn, ConversationTurn.id == MiningRun.input_turn_id)
                .where(MiningRun.session_id == sid, ConversationTurn.content == body.content))
            if duplicate:
                raise MiningError(409, 'mining_input_already_submitted')
            turn = facts.add_turn(db, sid, token, body.content)
        if turn is None or turn.session_id != sid or turn.role != 'user':
            raise MiningError(422, 'mining_invalid_source')
        if session.mining_status == 'not_started':
            session.mining_status = 'active'
            db.flush()
        db.refresh(session)
        # Count distinct input rounds, not retries. An admission cap is not "success".
        rounds = db.scalar(select(func.count(func.distinct(MiningRun.input_turn_id))).where(MiningRun.session_id == sid))
        if rounds >= 6 and not retries:
            raise MiningError(409, 'mining_round_limit')
        run = MiningRun(session_id=sid, project_id=project.id, input_turn_id=turn.id,
            base_revision=body.base_revision, reserved_revision=session.context_revision, state='reserved',
            lease_until=min(key.expires_at, utcnow()+timedelta(seconds=LEASE_SECONDS)), retry_of=retries)
        db.add(run); db.flush()
        db.add(MiningReceipt(key_digest=key.digest, state='live', expires_at=key.expires_at,
            session_id=sid, run_id=run.id, request_tag=tag))
        return run.id, True


def claim(factory, sid, token, rid):
    with factory() as db, db.begin():
        run = get_run(db, sid, token, rid)
        session = db.get(ExperienceSession, sid)
        if run.state != 'reserved':
            return None
        if run.lease_until <= utcnow():
            run.state, run.error_code = 'unknown', 'lease_expired'
            return None
        if session.status != 'active' or session.mining_status != 'active' or session.context_revision != run.reserved_revision:
            run.state, run.error_code = 'stale', 'context_changed'
            return None
        run.state = 'running'
        turn = db.get(ConversationTurn, run.input_turn_id)
        return MiningInput(turn.id, turn.content)


def validate_output(db, run, output):
    validated = MiningOutput.model_validate(output)
    for question in validated.questions:
        if not question.strip() or len(question) > 500:
            raise ValueError('Invalid question')
    for candidate in validated.candidates:
        citation = candidate.citation
        turn = db.get(ConversationTurn, citation.turn_id)
        # Extractive v1 intentionally accepts ONLY the full submitted user turn.
        # Sentence fragments can drop negation, team scope or uncertainty. No paraphrase.
        if (turn is None or turn.id != run.input_turn_id or turn.session_id != run.session_id or turn.role != 'user'
            or citation.start != 0 or citation.end != len(turn.content) or citation.quote != turn.content
            or turn.content[citation.start:citation.end] != citation.quote):
            raise ValueError('Invalid source span')
    return validated


def fail(factory, sid, token, rid, state, code):
    try:
        with factory() as db, db.begin():
            run = get_run(db, sid, token, rid)
            if run.state in ACTIVE:
                run.state, run.error_code = state, code
    except PermissionError:
        pass  # Session deleted; never recreate it.


def complete(factory, sid, token, rid, output):
    with factory() as db, db.begin():
        run = get_run(db, sid, token, rid)
        session = db.get(ExperienceSession, sid)
        if run.state != 'running':
            return
        if run.lease_until <= utcnow():
            run.state, run.error_code = 'unknown', 'lease_expired'
            return
        if session.status != 'active' or session.mining_status != 'active' or session.context_revision != run.reserved_revision:
            run.state, run.error_code = 'stale', 'context_changed'
            return
        validated = validate_output(db, run, output)
        def guard_commit(db_session):
            if utcnow() >= run.lease_until:
                raise MiningError(409, 'mining_lease_expired')
        event.listen(db, 'before_commit', guard_commit, once=True)
        added = 0
        for candidate in validated.candidates:
            citation = candidate.citation
            # Include rejected/manual facts: a rejection cannot be bypassed by re-extraction.
            if db.scalar(select(ExperienceFact.id).where(ExperienceFact.project_id == run.project_id,
                                                       ExperienceFact.statement == citation.quote)) or db.scalar(
                select(FactSource.fact_id).where(FactSource.session_id == sid,
                    FactSource.citations.contains([{'quote': citation.quote}]))):
                continue
            facts.add_fact(db, run.project_id, token, citation.quote, [citation.turn_id], origin='ai_extracted',
                ai_run_id=run.id, citations=[citation.model_dump(mode='json')])
            db.flush()
            added += 1
        prior = db.scalars(select(MiningRun).where(MiningRun.session_id == sid, MiningRun.state == 'completed').order_by(MiningRun.created_at.desc(), MiningRun.id.desc()).limit(1)).first()
        prior_empty = prior is not None and db.scalar(select(func.count()).select_from(ExperienceFact).where(ExperienceFact.ai_run_id == prior.id)) == 0
        stop = added == 0 and prior_empty
        round_count = db.scalar(select(func.count(func.distinct(MiningRun.input_turn_id))).where(MiningRun.session_id == sid))
        stop = stop or round_count >= 6
        if stop:
            session.mining_status = 'stopped'
        else:
            for question in validated.questions:
                db.add(MiningQuestion(session_id=sid, run_id=rid, content=question))
        # Question text is stored exactly ONCE, never copied into assistant/history blobs.
        assistant = ConversationTurn(session_id=sid, role='assistant', content='Synthetic provider: candidate review available.')
        db.add(assistant); db.flush()
        run.assistant_turn_id, run.state = assistant.id, 'completed'
        run.tokens_in, run.tokens_out = validated.tokens_in, validated.tokens_out


async def execute(factory, provider, sid, token, rid):
    context = claim(factory, sid, token, rid)
    if context is None:
        return
    try:
        output = await asyncio.wait_for(provider.mine(context), timeout=CALL_TIMEOUT_SECONDS)
        complete(factory, sid, token, rid, output)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        fail(factory, sid, token, rid, 'unknown', 'provider_outcome_unknown')
        if asyncio.current_task().cancelling():
            raise
    except PermissionError:
        pass
    except ValueError:
        fail(factory, sid, token, rid, 'failed', 'provider_output_invalid')
    except Exception:
        # SQL failure may have uncertain commit outcome; do not pretend non-execution.
        fail(factory, sid, token, rid, 'unknown', 'provider_or_storage_unknown')


def erase_receipts(db, sid):
    db.execute(update(MiningReceipt).where(MiningReceipt.session_id == sid).values(
        state='deleted', session_id=None, run_id=None, request_tag=None))


def cleanup(db):
    return db.execute(delete(MiningReceipt).where(MiningReceipt.expires_at <= utcnow())).rowcount
