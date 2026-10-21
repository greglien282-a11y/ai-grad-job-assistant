"""SIMULATED diagnostics over caller-arranged synthetic history, not admission.

The finite family lists are adversarial hints, NOT semantic equivalence classes
or an expansion of c3a's accepted language. No I/O, database or source binding.
"""
from dataclasses import dataclass

LABELS = frozenset({'EXACT_REUSE','SOURCE_REUSE','HISTORY_RISK',
    'SEMANTICALLY_SUSPECTED','INDEPENDENCE_NOT_PROVEN','NEEDS_HUMAN_DECISION'})
_FAMILIES = (
    frozenset({'我测试了3个导出按钮。','我测试了三个导出按钮。','我验证了3个导出按钮。',
        '我测试了4个导出按钮。','我们测试了3个导出按钮。','我计划测试3个导出按钮。',
        '我没有测试3个导出按钮。','我测试了3个导出按钮，但不是独立完成。'}),
    frozenset({'我整理了27条缺失记录。','我整理了28条缺失记录。','我们整理了27条缺失记录。',
        '我没有整理27条缺失记录。','我整理了27条缺失记录，可能有重复。'}),
    frozenset({'我部署了服务。','我们部署了服务。','我计划部署服务。','我正在部署服务。',
        '我没有部署服务。','如果我部署服务。','我可能部署过服务。'}),
)


@dataclass(frozen=True)
class Source:
    turn: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class Claim:
    statement: str
    source: Source


@dataclass(frozen=True)
class Record:
    statement: str
    status: str
    snapshots: tuple[tuple[str,str], ...] = ()
    sources: tuple[Source, ...] = ()


@dataclass(frozen=True)
class Assessment:
    labels: tuple[str, ...]
    source_relations: tuple[str, ...]
    conservative_block: bool
    evidence_class: str = 'SIMULATED'
    source_binding: str = 'NOT_CHECKED'
    semantic_independence: str = 'NOT_PROVEN'
    truth_verified: bool = False
    persistence_authorized: bool = False


def assess(claim: Claim, history: tuple[Record, ...]) -> Assessment:
    """Describe risk, never return semantic identity or permission to write."""
    def source_valid(source):
        return (type(source) is Source and type(source.turn) is str and bool(source.turn)
            and ((source.start is None and source.end is None)
                 or (type(source.start) is int and type(source.end) is int
                     and 0 <= source.start < source.end)))
    def statement_valid(value):return type(value) is str and bool(value.strip())
    states={'pending','user_confirmed','evidence_supported','rejected'}
    if (type(claim) is not Claim or not statement_valid(claim.statement)
            or not source_valid(claim.source) or type(history) is not tuple):
        raise ValueError('synthetic_input_invalid')
    labels={'INDEPENDENCE_NOT_PROVEN'};relations=set();rejected=False
    for row in history:
        if (type(row) is not Record or not statement_valid(row.statement) or row.status not in states
                or type(row.snapshots) is not tuple or type(row.sources) is not tuple
                or any(type(s) is not tuple or len(s)!=2 or not statement_valid(s[0]) or s[1] not in states for s in row.snapshots)
                or not all(source_valid(s) for s in row.sources)):
            raise ValueError('synthetic_history_invalid')
        texts={row.statement,*(s[0] for s in row.snapshots)}
        rejected |= row.status=='rejected' or any(s[1]=='rejected' for s in row.snapshots)
        if claim.statement in texts:labels.add('EXACT_REUSE')
        if any(claim.statement in family and bool((texts-{claim.statement}) & family) for family in _FAMILIES):
            labels.add('SEMANTICALLY_SUSPECTED')
        for old in row.sources:
            if old.turn!=claim.source.turn:continue
            if old.start is None or claim.source.start is None:
                relations.add('same_turn_unknown_range');labels.add('SOURCE_REUSE')
            elif max(old.start,claim.source.start)<min(old.end,claim.source.end):
                relations.add('overlap');labels.add('SOURCE_REUSE')
            else:relations.add('same_turn_disjoint')
    if rejected:labels.add('HISTORY_RISK')
    if len(labels)>1:labels.add('NEEDS_HUMAN_DECISION')
    return Assessment(tuple(sorted(labels)),tuple(sorted(relations)),bool(rejected))
