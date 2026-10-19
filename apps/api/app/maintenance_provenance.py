"""Additive v2 DTO only. Never mutate frozen FactChange snapshots or trust."""
from sqlalchemy import select, text

from app.fact_maintenance_models import FactChangeSource
from app.models import FactChange


def provenance(db, fact, snapshot):
    empty = dict(provenance_version=2, edit_method='legacy_manual' if snapshot['source_change_id'] else None,
                 current_citations=[], withdrawal_basis=[], maintenance_history_sources=[])
    if db.scalar(text("SELECT to_regclass('fact_change_sources')")) is None:
        return empty
    sources = db.scalars(select(FactChangeSource).where(FactChangeSource.fact_id == fact.id)
        .order_by(FactChangeSource.after_version, FactChangeSource.source_role, FactChangeSource.id)).all()
    def citation(s):
        return dict(turn_id=s.turn_id, start=s.start_cp, end=s.end_cp, quote=s.quote,
            change_id=s.change_id, fact_version=s.after_version, source_role=s.source_role)
    edited_id = snapshot['source_change_id']
    current = [s for s in sources if str(s.change_id) == edited_id and s.source_role == 'statement']
    # Confirmation/memory changes preserve the latest edit's provenance, whereas
    # a later legacy edit replaces it and truthfully has no conversational quote.
    withdrawal = []
    if fact.status == 'rejected':
        rejected_change = db.scalar(select(FactChange).where(FactChange.fact_id == fact.id,
            FactChange.action == 'status_changed', FactChange.after['status'].astext == 'rejected')
            .order_by(FactChange.after['version'].as_integer().desc()).limit(1))
        if rejected_change:
            withdrawal = [s for s in sources if s.change_id == rejected_change.id and s.reason == 'explicit_withdrawal']
    return dict(provenance_version=2,
        edit_method=('conversation_correction' if current else 'legacy_manual') if edited_id else None,
        current_citations=[citation(s) for s in current] if fact.status != 'rejected' else [],
        withdrawal_basis=[citation(s) for s in withdrawal],
        maintenance_history_sources=[citation(s) for s in sources])
