"""Nonpersistent research protocol. Existing M2 diagnostics remain unchanged.

Callers arrange synthetic history; this module proves neither completeness nor
identity. No decision here permits persistence, including after an explanation.
"""
from dataclasses import dataclass, field, replace
from overnight_research.r03 import Claim, Record, assess

CONTRACT = 'r03-clarification-simulation-v1'


@dataclass(frozen=True)
class HistoricalFact:
    fact_id: str
    version: int
    record: Record


@dataclass(frozen=True)
class Conflict:
    fact_id: str
    version: int
    rejected_statements: tuple[str, ...]
    labels: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Explanation:
    text: str
    evidence_description: str


@dataclass(frozen=True)
class Flow:
    candidate: Claim
    history: tuple[HistoricalFact, ...]
    conflicts: tuple[Conflict, ...]
    explanations: tuple[Explanation, ...] = ()
    revision: int = 1
    state: str = 'requires_review'
    contract: str = field(default=CONTRACT, init=False)
    evidence_class: str = field(default='SIMULATED_NOT_SAVED', init=False)
    history_completeness_verified: bool = field(default=False, init=False)
    semantic_independence: str = field(default='NOT_PROVEN', init=False)
    truth_verified: bool = field(default=False, init=False)
    persistence_authorized: bool = field(default=False, init=False)


def begin(candidate: Claim, history: tuple[HistoricalFact, ...], *, contract=CONTRACT):
    if contract != CONTRACT:
        raise ValueError('clarification_version_unsupported')
    if type(history) is not tuple or any(type(h) is not HistoricalFact for h in history):
        raise ValueError('synthetic_history_invalid')
    if (any(type(h.fact_id) is not str or not h.fact_id or type(h.version) is not int or h.version < 1 for h in history)
            or len({h.fact_id for h in history}) != len(history)):
        raise ValueError('synthetic_history_invalid')
    # Validate even empty history/candidate using the reviewed diagnostic.
    assess(candidate, tuple(h.record for h in history))
    conflicts = []
    for h in history:
        diagnostic = assess(candidate, (h.record,))
        rejected = tuple(dict.fromkeys(
            ([h.record.statement] if h.record.status == 'rejected' else []) +
            [text for text, status in h.record.snapshots if status == 'rejected']))
        if diagnostic.conservative_block or len(diagnostic.labels) > 1:
            related = any(label in diagnostic.labels for label in
                          ('EXACT_REUSE', 'SOURCE_REUSE', 'SEMANTICALLY_SUSPECTED'))
            conflicts.append(Conflict(h.fact_id, h.version, rejected, diagnostic.labels,
                'possible_reassertion_not_proven' if related else 'unrelated_blocked_by_rejected_history'))
    return Flow(candidate, history, tuple(conflicts))


def explain(flow: Flow, *, expected_revision: int, text: str, evidence_description: str):
    if type(flow) is not Flow or flow.contract != CONTRACT:
        raise ValueError('clarification_state_invalid')
    if (flow.conflicts != begin(flow.candidate, flow.history).conflicts
            or type(flow.explanations) is not tuple or flow.revision != len(flow.explanations) + 1
            or flow.state != ('requires_review' if not flow.explanations else 'awaiting_independent_review')):
        raise ValueError('clarification_state_invalid')
    if type(expected_revision) is not int or expected_revision != flow.revision:
        raise ValueError('clarification_revision_conflict')
    # User text stays verbatim, including uncertainty; nothing is fetched or
    # interpreted as verified evidence. Attachments/URLs are not dereferenced.
    for value in (text, evidence_description):
        if type(value) is not str or not value.strip() or len(value) > 2000 or '\0' in value:
            raise ValueError('clarification_explanation_invalid')
        try:
            value.encode('utf8', errors='strict')
        except UnicodeError:
            raise ValueError('clarification_explanation_invalid') from None
    return replace(flow, explanations=flow.explanations + (Explanation(text, evidence_description),),
                   revision=flow.revision + 1, state='awaiting_independent_review')


def request_save(flow: Flow):
    """There is deliberately no successful transition or approval override."""
    if type(flow) is not Flow:
        raise ValueError('clarification_state_invalid')
    return {'status': 'not_saved', 'code': 'transaction_review_and_policy_approval_required',
            'semantic_independence': 'NOT_PROVEN', 'truth_verified': False,
            'persistence_authorized': False}
