"""Shared exact-match protections. These are not semantic classifiers.

Call only after authorizing/locking the Session, and after receipt recovery.
No raw text hashes, receipts, model calls, or new transaction boundaries here.
"""
from sqlalchemy import select, text

from app.fact_maintenance_models import ConversationOperation
from app.maintenance_errors import ConversationError
from app.models import ConversationTurn, ExperienceFact, FactChange, FactSource


def input_consumed(db, sid, *, content=None, turn_ids=()):
    # Old migration compatibility: no maintenance receipt can exist before
    # 0013. The new API separately refuses missing tables/functions/role setup.
    if db.scalar(text("SELECT to_regclass('conversation_operations')")) is None:
        return
    query = select(ConversationOperation.id).join(
        ConversationTurn, ConversationTurn.id == ConversationOperation.input_turn_id
    ).where(ConversationOperation.session_id == sid, ConversationOperation.state != 'deleted')
    if content is not None:
        query = query.where(ConversationTurn.content == content)
    else:
        if not turn_ids:
            return
        query = query.where(ConversationTurn.id.in_(turn_ids))
    if db.scalar(query.limit(1)) is not None:
        raise ConversationError(409, 'conversation_input_already_submitted')


def rejected_contribution(db, sid, statement, source_turn_ids=(), *, exclude=None):
    """Reject exact current/history text or reused rejected origin turns.

    Turn-level exclusion is deliberately conservative for legacy sources without
    precise citations. Reworded semantic identity is not proved by this guard.
    """
    query = select(ExperienceFact).where(
        ExperienceFact.session_id == sid, ExperienceFact.status == 'rejected')
    if exclude is not None:
        query = query.where(ExperienceFact.id != exclude)
    for fact in db.scalars(query):
        statements = {fact.statement}
        for change in db.scalars(select(FactChange).where(FactChange.fact_id == fact.id)):
            for snapshot in (change.before, change.after):
                if isinstance(snapshot, dict) and isinstance(snapshot.get('statement'), str):
                    statements.add(snapshot['statement'])
        source_ids = set(db.scalars(select(FactSource.turn_id).where(FactSource.fact_id == fact.id)))
        if statement in statements or source_ids.intersection(source_turn_ids):
            raise ConversationError(409, 'fact_rejected_immutable')
