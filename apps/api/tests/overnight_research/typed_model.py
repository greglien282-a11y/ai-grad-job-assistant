"""SIMULATED ONLY: immutable in-memory candidate graph and receipt transitions.

No database, HTTP, clocks, providers, credentials, filesystem or runtime factory.
Toy principal/key symbols are NOT authentication or HMAC implementations. A
returned state is a mathematical model value, never a durable database commit.
"""
from dataclasses import dataclass, replace, asdict
import hashlib
import json

from pydantic import ValidationError
from app.read_contract import Classification
from app.typed_semantic_spike import CONTRACT as LANGUAGE_CONTRACT, validate_candidate
from .r03 import Claim, Source, Record, assess

CONTRACT = 'SIMULATED-typed-append-candidate-v1'
WINDOW = 24*60*60
FAULTS = ('before_turn','after_turn','after_facts','after_history','after_sources',
          'after_receipt','before_commit','after_commit')


@dataclass(frozen=True)
class Item:
    fact_kind: str
    progress_stage: str
    classification_contract: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True)
class Command:
    session: str
    project: str
    key_symbol: str
    issued_at: int
    base_revision: int
    content: str
    items: tuple[Item, ...]
    contract_version: int = 3
    decision_contract: str = CONTRACT


@dataclass(frozen=True)
class SimSession:
    id: str
    project: str
    principal: str
    revision: int = 1
    active: bool = True
    mode: str = 'typed_model'
    worker_state: str = 'none'


@dataclass(frozen=True)
class Snapshot:
    statement: str
    fact_kind: str
    progress_stage: str
    classification_contract: str
    status: str = 'pending'
    version: int = 1
    memory_state: str = 'unspecified'
    origin: str = 'manual'
    ai_run_id: str | None = None
    evidence_id: str | None = None


@dataclass(frozen=True)
class SimTurn:
    id: str
    session: str
    content: str
    role: str = 'user'


@dataclass(frozen=True)
class SimFact:
    id: str
    session: str
    project: str
    current: Snapshot


@dataclass(frozen=True)
class SimChange:
    id: str
    session: str
    fact: str
    before: Snapshot | None
    after: Snapshot
    action: str = 'created'
    actor: str = 'system'


@dataclass(frozen=True)
class SimSource:
    fact: str
    session: str
    turn: str
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class SimAudit:
    operation: str
    slot: int
    fact: str
    change: str
    source: SimSource


@dataclass(frozen=True)
class SimBasis:
    id: str
    operation: str
    slot: int
    fact: str
    change: str
    source: SimSource
    fact_kind: str
    progress_stage: str
    classification_contract: str
    validation_contract: str = LANGUAGE_CONTRACT
    evidence_class: str = 'SIMULATED_DECLARATION_ONLY'


@dataclass(frozen=True)
class SimReceipt:
    id: str
    key_digest: str
    scope_digest: str
    principal_digest: str
    contract_version: int
    decision_contract: str
    request_tag: str | None
    expires_at: int
    session: str | None = None
    turn: str | None = None
    facts: tuple[str, ...] = ()
    changes: tuple[str, ...] = ()
    bases: tuple[str, ...] = ()
    result_revision: int | None = None
    state: str = 'applied'
    opaque_legacy: bool = False


@dataclass(frozen=True)
class State:
    sessions: tuple[SimSession, ...]
    turns: tuple[SimTurn, ...] = ()
    facts: tuple[SimFact, ...] = ()
    changes: tuple[SimChange, ...] = ()
    sources: tuple[SimSource, ...] = ()
    audits: tuple[SimAudit, ...] = ()
    bases: tuple[SimBasis, ...] = ()
    receipts: tuple[SimReceipt, ...] = ()
    next_id: int = 1


@dataclass(frozen=True)
class Outcome:
    code: str
    operation: str | None = None
    facts: tuple[str, ...] = ()
    revision: int | None = None
    evidence_class: str = 'SIMULATED'
    source_binding: str = 'SIMULATED_ONLY'
    semantic_independence: str = 'NOT_PROVEN'
    transaction_review_required: bool = True
    truth_verified: bool = False
    persistence_authorized: bool = False


class ModelInvalid(ValueError):
    pass


class SimulatedCrash(Exception):
    """An exception in a pure model, emphatically NOT a real process crash."""
    def __init__(self, durable_model):
        self.durable_model=durable_model
        super().__init__('SIMULATED_FAULT')


def digest(value):
    return hashlib.sha256(value.encode('utf8')).hexdigest()


def fingerprint(command):
    body=asdict(command)
    body.pop('key_symbol');body.pop('issued_at')
    return digest(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(',',':')))


def _need(ok):
    if not ok:raise ModelInvalid('SIMULATED_INTEGRITY_UNAVAILABLE')


def _triple(value):
    return value.fact_kind,value.progress_stage,value.classification_contract


def _same(left,right):
    # Dataclass/Python equality aliases True/1 and False/0. Preserve JSON types
    # across snapshots and independently stored source/declaration edges.
    return (type(left) is type(right)
        and json.dumps(asdict(left),sort_keys=True,ensure_ascii=False)
            ==json.dumps(asdict(right),sort_keys=True,ensure_ascii=False))


def validate(state):
    """Validate this deliberately narrower append/review-only MODEL graph."""
    _need(type(state) is State and type(state.next_id) is int and state.next_id>0)
    collections=('sessions','turns','facts','changes','sources','audits','bases','receipts')
    _need(all(type(getattr(state,k)) is tuple for k in collections))
    classes=(SimSession,SimTurn,SimFact,SimChange,SimSource,SimAudit,SimBasis,SimReceipt)
    _need(all(type(row) is cls for name,cls in zip(collections,classes) for row in getattr(state,name)))
    def indexed(rows):
        _need(all(type(r.id) is str and bool(r.id) for r in rows))
        _need(len({r.id for r in rows})==len(rows))
        return {r.id:r for r in rows}
    sessions=indexed(state.sessions);turns=indexed(state.turns);facts=indexed(state.facts)
    changes=indexed(state.changes);bases=indexed(state.bases);receipts=indexed(state.receipts)
    _need(len({r.key_digest for r in state.receipts})==len(state.receipts))
    for s in state.sessions:
        _need(type(s.revision) is int and s.revision>0 and type(s.active) is bool
            and s.mode in ('typed_model','legacy_model') and bool(s.principal) and bool(s.project)
            and s.worker_state in ('none','reserved','running','unknown','completed','failed','stale'))
    for turn in state.turns:
        _need(turn.session in sessions and turn.role=='user' and type(turn.content) is str)
    for fact in state.facts:
        _need(fact.session in sessions and fact.project==sessions[fact.session].project)
        _need(type(fact.current) is Snapshot and type(fact.current.version) is int and fact.current.version>0)
        _need(all(type(c.after) is Snapshot and (c.before is None or type(c.before) is Snapshot)
            for c in state.changes if c.fact==fact.id))
        history=sorted((c for c in state.changes if c.fact==fact.id),key=lambda c:c.after.version)
        _need(bool(history) and [c.after.version for c in history]==list(range(1,fact.current.version+1)))
        _need(history[0].before is None and history[0].action=='created' and history[0].actor=='system'
            and history[0].after.status=='pending' and _same(history[-1].after,fact.current))
        for i,c in enumerate(history):
            snap=c.after
            _need(type(snap.version) is int and snap.version>0 and c.session==fact.session
                and snap.status in ('pending','user_confirmed','rejected')
                and snap.memory_state=='unspecified' and snap.origin=='manual'
                and snap.ai_run_id is None and snap.evidence_id is None)
            Classification(fact_kind=snap.fact_kind,progress_stage=snap.progress_stage,
                classification_contract=snap.classification_contract)
            _need(snap.statement==history[0].after.statement and _triple(snap)==_triple(history[0].after))
            if i:_need(c.before is not None and _same(c.before,history[i-1].after)
                and c.action=='status_changed' and c.actor=='user')
        anchors=[s for s in state.sources if s.fact==fact.id]
        _need(len(anchors)==1 and anchors[0].quote==history[0].after.statement)
    _need(all(c.fact in facts for c in state.changes))
    for source in state.sources:
        _need(source.fact in facts and source.turn in turns)
        turn=turns[source.turn];fact=facts[source.fact]
        _need(source.session==turn.session==fact.session
            and type(source.start) is int and type(source.end) is int
            and 0<=source.start<source.end<=len(turn.content)
            and turn.content[source.start:source.end]==source.quote)
    for row in state.receipts:
        _need(row.contract_version in (1,2,3) and type(row.contract_version) is int
            and type(row.expires_at) is int and row.expires_at>0 and row.state in ('applied','deleted')
            and row.decision_contract=={1:'explicit-target-v1',2:'append-batch-v1',3:CONTRACT}[row.contract_version])
        _need(all(type(value) is str and len(value)==64 and set(value)<=set('0123456789abcdef')
            for value in (row.key_digest,row.scope_digest,row.principal_digest)))
        if row.state=='deleted':
            _need(row.session is None and row.turn is None and row.request_tag is None
                and not row.facts and not row.changes and not row.bases and row.result_revision is None)
            continue
        _need(row.session in sessions and row.scope_digest==digest(row.session)
            and row.principal_digest==digest(sessions[row.session].principal)
            and type(row.request_tag) is str and bool(row.request_tag))
        if row.contract_version in (1,2):
            _need(row.opaque_legacy and row.decision_contract=={1:'explicit-target-v1',2:'append-batch-v1'}[row.contract_version]
                and not row.facts and not row.changes and not row.bases and row.turn is None)
            continue  # a labeled opaque fixture, NOT validation of a real old graph
        _need(not row.opaque_legacy and row.decision_contract==CONTRACT and row.turn in turns
            and turns[row.turn].session==row.session and 1<=len(row.facts)<=5
            and len(row.facts)==len(set(row.facts))==len(row.changes)==len(set(row.changes))==len(row.bases)
            and type(row.result_revision) is int and row.result_revision<=sessions[row.session].revision)
        audits=sorted((a for a in state.audits if a.operation==row.id),key=lambda a:a.slot)
        _need([a.slot for a in audits]==list(range(1,len(row.facts)+1)))
        for slot,(fid,cid,bid) in enumerate(zip(row.facts,row.changes,row.bases),1):
            _need(fid in facts and cid in changes and bid in bases)
            change=changes[cid];basis=bases[bid];fact=facts[fid];audit=audits[slot-1]
            source=next(s for s in state.sources if s.fact==fid)
            _need(type(audit.slot) is int and type(basis.slot) is int
                and change.fact==fid and change.action=='created' and change.after.version==1
                and fact.session==row.session and source.turn==row.turn
                and audit.fact==fid and audit.change==cid and _same(audit.source,source)
                and basis.operation==row.id and basis.slot==slot and basis.fact==fid
                and basis.change==cid and _same(basis.source,source) and _triple(basis)==_triple(change.after)
                and basis.validation_contract==LANGUAGE_CONTRACT
                and basis.evidence_class=='SIMULATED_DECLARATION_ONLY')
    _need(all(a.operation in receipts and a.fact in facts and a.change in changes for a in state.audits))
    _need(all(b.operation in receipts and b.fact in facts and b.change in changes for b in state.bases))
    live=[r for r in state.receipts if r.contract_version==3 and r.state=='applied']
    _need(sorted(f.id for f in state.facts)==sorted(fid for r in live for fid in r.facts))
    _need(sorted(t.id for t in state.turns)==sorted(r.turn for r in live))
    _need(len(state.bases)==sum(len(r.bases) for r in live)
        and len(state.audits)==sum(len(r.facts) for r in live))


def _authorized(state,sid,principal):
    return next((s for s in state.sessions if s.id==sid and s.principal==principal),None)


def _receipt(state,key):
    return next((r for r in state.receipts if r.key_digest==digest(key)),None)


def _history(state,sid):
    return tuple(Record(f.current.statement,f.current.status,
        tuple((c.after.statement,c.after.status) for c in state.changes if c.fact==f.id),
        tuple(Source(s.turn,s.start,s.end) for s in state.sources if s.fact==f.id))
        for f in state.facts if f.session==sid)


def submit(state,command,principal,*,now=0,fault=None):
    """Return a new immutable MODEL state or the exact unchanged input state."""
    if fault is not None and fault not in FAULTS:raise ValueError('unknown_model_fault')
    if type(command) is not Command:return state,Outcome('request_invalid')
    session=_authorized(state,command.session,principal)
    if session is None:return state,Outcome('resource_unavailable')
    try:
        validate(state)
        if (type(now) is not int or type(command.issued_at) is not int or command.issued_at>now
                or type(command.key_symbol) is not str or not command.key_symbol):
            return state,Outcome('key_invalid')
        if type(command.contract_version) is not int or command.contract_version!=3 or command.decision_contract!=CONTRACT:
            return state,Outcome('contract_unsupported')
        row=_receipt(state,command.key_symbol)
        if row:
            if row.scope_digest!=digest(command.session) or row.principal_digest!=digest(principal):
                return state,Outcome('resource_unavailable')
            if row.contract_version!=3:return state,Outcome('contract_mismatch')
            if row.state=='deleted':return state,Outcome('resource_deleted')
            if now>=row.expires_at:return state,Outcome('receipt_expired')
            if row.expires_at!=command.issued_at+WINDOW:return state,Outcome('key_metadata_mismatch')
            if row.request_tag!=fingerprint(command):return state,Outcome('payload_mismatch')
            return state,Outcome('replayed',row.id,row.facts,row.result_revision)
        if now>=command.issued_at+WINDOW:return state,Outcome('key_expired')
        if session.mode!='typed_model':return state,Outcome('creation_contract_unavailable')
        if not session.active:return state,Outcome('session_ended')
        if session.worker_state in ('reserved','running','unknown'):return state,Outcome('unresolved_run')
        if command.project!=session.project:return state,Outcome('resource_unavailable')
        if type(command.base_revision) is not int or command.base_revision!=session.revision:
            return state,Outcome('context_conflict')
        if type(command.items) is not tuple or any(type(item) is not Item for item in command.items):
            return state,Outcome('items_invalid')
        language=validate_candidate(dict(validation_contract=LANGUAGE_CONTRACT,synthetic=True,
            raw_text=command.content,items=[asdict(i) for i in command.items]))
        if language.status!='eligible_candidate':return state,Outcome('language_or_quote_rejected')
        history=_history(state,session.id)
        for item in command.items:
            risk=assess(Claim(item.quote,Source('SIMULATED-new-turn',item.start,item.end)),history)
            if risk.conservative_block:return state,Outcome('history_requires_review')
            if 'EXACT_REUSE' in risk.labels:return state,Outcome('exact_reuse')
            if 'SEMANTICALLY_SUSPECTED' in risk.labels:return state,Outcome('semantic_review_required')
        def checkpoint(name,value):
            if fault==name:raise SimulatedCrash(value)
        checkpoint('before_turn',state)
        prefix='sim-'+str(state.next_id);oid=prefix+'-operation';tid=prefix+'-turn'
        staged=replace(state,turns=state.turns+(SimTurn(tid,session.id,command.content),))
        checkpoint('after_turn',state)
        new_facts=tuple(SimFact(prefix+'-fact-'+str(n),session.id,session.project,
            Snapshot(i.quote,i.fact_kind,i.progress_stage,i.classification_contract))
            for n,i in enumerate(command.items,1))
        staged=replace(staged,facts=state.facts+new_facts)
        checkpoint('after_facts',state)
        new_changes=tuple(SimChange(prefix+'-change-'+str(n),session.id,f.id,None,f.current)
            for n,f in enumerate(new_facts,1))
        staged=replace(staged,changes=state.changes+new_changes)
        checkpoint('after_history',state)
        sources=tuple(SimSource(f.id,session.id,tid,i.start,i.end,i.quote) for f,i in zip(new_facts,command.items))
        audits=tuple(SimAudit(oid,n,f.id,c.id,s) for n,(f,c,s) in enumerate(zip(new_facts,new_changes,sources),1))
        bases=tuple(SimBasis(prefix+'-basis-'+str(n),oid,n,f.id,c.id,s,*_triple(f.current))
            for n,(f,c,s) in enumerate(zip(new_facts,new_changes,sources),1))
        staged=replace(staged,sources=state.sources+sources,audits=state.audits+audits,bases=state.bases+bases)
        checkpoint('after_sources',state)
        receipt=SimReceipt(oid,digest(command.key_symbol),digest(session.id),digest(principal),3,CONTRACT,
            fingerprint(command),command.issued_at+WINDOW,session.id,tid,tuple(f.id for f in new_facts),
            tuple(c.id for c in new_changes),tuple(b.id for b in bases),session.revision+1)
        staged=replace(staged,receipts=state.receipts+(receipt,),next_id=state.next_id+1,
            sessions=tuple(replace(s,revision=s.revision+1) if s.id==session.id else s for s in state.sessions))
        checkpoint('after_receipt',state)
        validate(staged)
        checkpoint('before_commit',state)
        checkpoint('after_commit',staged)
        return staged,Outcome('simulated_applied',oid,receipt.facts,receipt.result_revision)
    except (ModelInvalid,ValidationError,KeyError,TypeError,ValueError,StopIteration):
        return state,Outcome('integrity_unavailable')


def recover(state,sid,key_symbol,principal,*,version=3,now=0):
    """Pure GET-like MODEL projection; no state replacement, cleanup or key."""
    if type(key_symbol) is not str or not key_symbol:return Outcome('key_invalid')
    row=_receipt(state,key_symbol)
    if _authorized(state,sid,principal) is None:
        if not (row and row.state=='deleted' and row.scope_digest==digest(sid)
                and row.principal_digest==digest(principal)):
            return Outcome('resource_unavailable')
    try:validate(state)
    except (ModelInvalid,ValidationError,KeyError,TypeError,ValueError,StopIteration):return Outcome('integrity_unavailable')
    if row is None:return Outcome('receipt_not_found')
    if row.scope_digest!=digest(sid) or row.principal_digest!=digest(principal):return Outcome('resource_unavailable')
    if type(version) is not int or version not in (1,2,3):return Outcome('contract_unsupported')
    if row.contract_version!=version:return Outcome('contract_mismatch')
    if type(now) is not int:return Outcome('clock_invalid')
    if row.state=='deleted':return Outcome('resource_deleted')
    if now>=row.expires_at:return Outcome('receipt_expired')
    return Outcome('recovered',row.id,row.facts,row.result_revision)


def delete_session(state,sid,principal):
    """SIMULATED deletion only; actual DELETE policy/permissions stay unchanged."""
    if _authorized(state,sid,principal) is None:return state,Outcome('resource_unavailable')
    try:validate(state)
    except (ModelInvalid,ValidationError,KeyError,TypeError,ValueError,StopIteration):return state,Outcome('integrity_unavailable')
    fact_ids={f.id for f in state.facts if f.session==sid}
    receipt_ids={r.id for r in state.receipts if r.session==sid}
    receipts=tuple(replace(r,state='deleted',session=None,turn=None,request_tag=None,
        facts=(),changes=(),bases=(),result_revision=None) if r.id in receipt_ids else r for r in state.receipts)
    result=replace(state,sessions=tuple(s for s in state.sessions if s.id!=sid),
        turns=tuple(t for t in state.turns if t.session!=sid),facts=tuple(f for f in state.facts if f.id not in fact_ids),
        changes=tuple(c for c in state.changes if c.session!=sid),sources=tuple(s for s in state.sources if s.session!=sid),
        audits=tuple(a for a in state.audits if a.operation not in receipt_ids),
        bases=tuple(b for b in state.bases if b.operation not in receipt_ids),receipts=receipts)
    validate(result)
    return result,Outcome('simulated_deleted')


def legacy_capability(state,sid,principal,capability):
    """SIMULATED policy distinction, no old command implementation or effect."""
    if _authorized(state,sid,principal) is None:return Outcome('resource_unavailable')
    try:validate(state)
    except (ModelInvalid,ValidationError,KeyError,TypeError,ValueError,StopIteration):return Outcome('integrity_unavailable')
    if capability in ('receipt_recovery','end','delete','worker_finalize'):
        return Outcome('separate_existing_capability_not_implemented')
    if capability!='fresh_fact_command':return Outcome('capability_unsupported')
    triples=[_triple(f.current) for f in state.facts if f.session==sid]
    triples += [_triple(c.after) for c in state.changes if c.session==sid]
    if any(t!=('legacy_unspecified','legacy_unknown','legacy-v0') for t in triples):
        return Outcome('legacy_upgrade_required')
    return Outcome('legacy_policy_candidate_only')
