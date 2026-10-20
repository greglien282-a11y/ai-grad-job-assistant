"""Validated projections on one read-only snapshot. Never invokes a writer."""
from collections import defaultdict
import json

from sqlalchemy import select

from app import facts, read_contract as dto, schemas
from app.fact_classification import FIELDS, LEGACY
from app.fact_maintenance_models import ConversationOperation, FactChangeSource
from app.maintenance_errors import ConversationError
from app.models import (ExperienceProject, ConversationTurn, ExperienceFact, FactChange,
                        FactSource, FactEvidence, MiningRun, MiningQuestion, AnswerQuestion, utcnow)

REASONS={'unclassified-v1':'classification_unreviewed','personal_action':'action_in_progress',
         'plan':'plan_not_contribution','background':'background_context','boundary':'boundary_limitation'}


def invalid():
    raise ConversationError(503,'experience_read_integrity_unavailable')


def require(ok):
    if not ok:invalid()


def json_equal(left,right):
    # Python equality aliases False/0 and True/1, including nested JSON. A
    # projection must not accept type corruption that PostgreSQL JSONB rejects.
    return json.dumps(left,sort_keys=True,ensure_ascii=False)==json.dumps(right,sort_keys=True,ensure_ascii=False)


def classification(snapshot):
    require(isinstance(snapshot,dict))
    keys=set(FIELDS)&snapshot.keys()
    require(not keys or keys==set(FIELDS))
    values={k:snapshot[k] for k in FIELDS} if keys else dict(zip(FIELDS,LEGACY))
    return dto.SnapshotClassification(**values,interpretation='explicit_fields' if keys else 'legacy_missing_keys')


def raw(row, *, omit=()):
    return {c.key:getattr(row,c.key) for c in row.__table__.columns if c.key not in omit}


def quote(turn, citation):
    require(isinstance(citation,dict) and set(citation)=={'turn_id','start','end','quote'})
    start,end=citation['start'],citation['end']
    require(type(start) is int and type(end) is int and 0<=start<end<=len(turn.content))
    require(str(turn.id)==citation['turn_id'] and turn.role=='user'
            and turn.content[start:end]==citation['quote'])


class Projection:
    def __init__(self,db,session):
        self.db,self.session=db,session
        def rows(model):
            query=select(model).where(model.session_id==session.id)
            return list(db.scalars(query.order_by(model.created_at,model.id) if hasattr(model,'created_at') else query))
        self.projects=rows(ExperienceProject);self.turns=rows(ConversationTurn)
        self.facts=rows(ExperienceFact);self.history=rows(FactChange);self.sources=rows(FactSource)
        self.fcs=rows(FactChangeSource);self.operations=rows(ConversationOperation)
        self.evidence=rows(FactEvidence);self.runs=rows(MiningRun)
        self.questions=rows(MiningQuestion);self.answers=rows(AnswerQuestion)
        self.turn_map={r.id:r for r in self.turns};self.fact_map={r.id:r for r in self.facts}
        self.change_map={r.id:r for r in self.history};self.operation_map={r.id:r for r in self.operations}
        self.hist=defaultdict(list);self.orig=defaultdict(list);self.audit=defaultdict(list)
        for c in self.history:self.hist[c.fact_id].append(c)
        for s in self.sources:self.orig[s.fact_id].append(s)
        for s in self.fcs:self.audit[s.fact_id].append(s)
        self.validate_relations()
        self.views={f.id:self.fact(f) for f in self.facts}

    def validate_relations(self):
        project_ids={p.id for p in self.projects};run_ids={r.id for r in self.runs}
        for f in self.facts:require(f.project_id in project_ids and (f.ai_run_id is None or f.ai_run_id in run_ids))
        for c in self.history:
            require(c.fact_id in self.fact_map and isinstance(c.after,dict)
                    and (c.before is None or isinstance(c.before,dict)))
        for s in self.sources:
            require(s.fact_id in self.fact_map and s.turn_id in self.turn_map)
            turn=self.turn_map[s.turn_id];require(turn.role=='user')
            require(s.citations is None or isinstance(s.citations,list))
            for q in s.citations or []:quote(turn,q)
        for o in self.operations:
            require(type(o.contract_version) is int and o.contract_version in (1,2))
            require(o.decision_contract=={1:'explicit-target-v1',2:'append-batch-v1'}[o.contract_version])
            require(o.state in ('applied','needs_clarification') and o.input_turn_id in self.turn_map)
            require(o.progress_stage is None and o.action in ('append','correct','withdraw','disambiguate')
                    and o.kind in ('root','resolution'))
            if o.contract_version==2:require(o.action=='append' and o.kind=='root')
            require(o.parent_operation_id is None or o.parent_operation_id in self.operation_map)
            require(o.target_fact_id is None or o.target_fact_id in self.fact_map)
            related=[s for s in self.fcs if s.operation_id==o.id]
            slots={s.effect_slot for s in related}
            require(slots==set(range(1,o.effect_count+1)))
            for slot in slots:
                group=[s for s in related if s.effect_slot==slot]
                require(len({(s.fact_id,s.change_id,s.before_version,s.after_version) for s in group})==1)
                roles=[s.source_role for s in group]
                require(len(set(roles))==len(roles))
                first=group[0];change=self.change_map.get(first.change_id)
                require(change is not None)
                if o.action=='append':
                    require(roles==['statement'] and change.action=='created' and first.before_version is None
                            and first.after_version==1 and first.reason=='addition')
                else:
                    require(o.action in ('correct','withdraw') and o.effect_count==1
                            and first.fact_id==o.target_fact_id and first.before_version==o.target_version)
                    require(set(roles)==({'intent','statement'} if o.action=='correct' else {'intent'}))
                    require(change.action==('edited' if o.action=='correct' else 'status_changed'))
                    require(all(s.reason==('explicit_correction' if o.action=='correct' else 'explicit_withdrawal') for s in group))
        for s in self.fcs:
            require(s.fact_id in self.fact_map and s.change_id in self.change_map
                    and s.operation_id in self.operation_map and s.turn_id in self.turn_map)
            c=self.change_map[s.change_id];o=self.operation_map[s.operation_id]
            require(c.fact_id==s.fact_id and c.after.get('version')==s.after_version
                    and type(c.after.get('version')) is int and o.input_turn_id==s.turn_id)
            quote(self.turn_map[s.turn_id],dict(turn_id=str(s.turn_id),start=s.start_cp,end=s.end_cp,quote=s.quote))
            require(s.source_role in ('statement','intent') and s.reason in ('addition','explicit_correction','explicit_withdrawal'))
            require(s.before_version==(c.before.get('version') if c.before else None))
            if s.source_role=='statement':require(s.quote==c.after.get('statement'))
            require(o.state=='applied' and 1<=s.effect_slot<=o.effect_count)
        evidence_ids={e.id for e in self.evidence}
        for e in self.evidence:require(e.fact_id in self.fact_map)
        for f in self.facts:
            require(f.status!='evidence_supported' or f.evidence_id is not None)
            require(f.evidence_id is None or f.evidence_id in evidence_ids and
                    next(e for e in self.evidence if e.id==f.evidence_id).fact_id==f.id)
        question_map={q.id:q for q in self.questions}
        for run in self.runs:
            require(run.project_id in project_ids and run.input_turn_id in self.turn_map and run.provider=='scripted')
            require(run.retry_of is None or run.retry_of in run_ids)
            require(run.assistant_turn_id is None or run.assistant_turn_id in self.turn_map)
        for q in self.questions:require(q.run_id in run_ids)
        for a in self.answers:require(a.turn_id in self.turn_map and a.question_id in question_map)

    def fact(self,f):
        history=self.hist[f.id];sources=self.orig[f.id]
        created=[c for c in history if c.action=='created']
        require(len(created)==1 and bool(sources))
        initial=created[0]
        require(initial.before is None and initial.actor=='system' and initial.after.get('version')==1
                and type(initial.after.get('version')) is int)
        versions=set();annotations={}
        by_version=defaultdict(list)
        for c in history:
            require(c.action in ('created','edited','status_changed','memory_changed'))
            annotations[c.id]=(classification(c.before) if c.before is not None else None,classification(c.after))
            version=c.after.get('version')
            require(type(version) is int and 1<=version<=f.version)
            versions.add(version)
            by_version[version].append(c.after)
            if c.action!='created':require(isinstance(c.before,dict) and type(c.before.get('version')) is int
                                           and c.before['version']==version-1)
        require(versions==set(range(1,f.version+1)))
        for c in history:
            if c.before is None:continue
            for previous in by_version[c.before['version']]:
                # Shared recorded fields must agree; do not fill missing old
                # classification keys into either original JSON snapshot.
                for key in c.before.keys() & previous.keys():
                    require(json_equal(c.before[key],previous[key]))
        current=dto.Classification(**{k:getattr(f,k) for k in FIELDS})
        typed=any(a.classification_contract!='legacy-v0' for pair in annotations.values() for a in pair if a)
        require(not typed or current.classification_contract!='legacy-v0')
        snapshot=facts.snapshot(self.db,f)
        # Every current-version row must agree. No privileged validation helper,
        # SET CONSTRAINTS, normalization or repair is called by this GET.
        for c in history:
            if c.after['version']==f.version:
                for key,value in snapshot.items():require(key in c.after and json_equal(c.after[key],value))
            if typed:
                for saved in (c.before,c.after):
                    if saved is None:continue
                    require('origin' in saved and 'ai_run_id' in saved and 'memory_state' in saved
                            and 'evidence_id' in saved and isinstance(saved.get('statement'),str))
                    require(saved['origin']==f.origin and json_equal(saved['ai_run_id'],str(f.ai_run_id) if f.ai_run_id else None))
                    require(saved['memory_state'] in ('unspecified','certain','approximate','needs_check')
                            and saved.get('status') in ('pending','user_confirmed','evidence_supported','rejected'))
                    evidence={str(e.id):e for e in self.evidence}
                    require(saved['evidence_id'] is None or isinstance(saved['evidence_id'],str)
                            and saved['evidence_id'] in evidence and evidence[saved['evidence_id']].fact_id==f.id)
                    require(saved['status']!='evidence_supported' or saved['evidence_id'] is not None)
        original_ids=sorted(str(s.turn_id) for s in sources)
        require(initial.after.get('original_source_turn_ids')==original_ids)
        actual_quotes=[q for s in sources for q in s.citations or []]
        require(json_equal(initial.after.get('citations'),actual_quotes))
        if typed:
            initial_expected=dict(version=1,status='pending',memory_state='unspecified',evidence_id=None,
                source_kind='conversation_turns',source_change_id=None,source_turn_ids=original_ids)
            for key,value in initial_expected.items():require(key in initial.after and json_equal(initial.after[key],value))
            # Coordinate validity alone does not bind a quote to this fact.
            # Do not infer offsets for source links without a precise citation:
            # that supported subset must match the complete original Turn.
            for source in sources:
                if source.citations:
                    require(all(q['quote']==initial.after['statement'] for q in source.citations))
                else:require(self.turn_map[source.turn_id].content==initial.after['statement'])
        edits=[c for c in history if c.action=='edited']
        edit=max(edits,key=lambda c:(c.after['version'],c.created_at,str(c.id))) if edits else None
        citations=[];turn_ids=[]
        if edit:
            for s in self.audit[f.id]:
                if s.change_id==edit.id and s.source_role=='statement':
                    turn_ids.append(s.turn_id)
                    citations.append(dto.Citation(turn_id=s.turn_id,start=s.start_cp,end=s.end_cp,quote=s.quote,
                        change_id=edit.id,fact_version=edit.after['version'],source_kind='conversation_change'))
        else:
            turn_ids=[s.turn_id for s in sources]
            for s in sources:
                for q in s.citations or []:
                    citations.append(dto.Citation(**q,change_id=initial.id,fact_version=1,source_kind='original_source'))
        return dto.FactV3(**current.model_dump(),id=f.id,session_id=f.session_id,project_id=f.project_id,
            statement=f.statement,status=f.status,version=f.version,created_at=f.created_at,updated_at=f.updated_at,
            origin=f.origin,memory_state=f.memory_state,ai_run_id=f.ai_run_id,evidence_id=f.evidence_id,
            original_source_turn_ids=original_ids,current_statement_source_turn_ids=sorted(set(turn_ids),key=str),
            current_statement_citations=citations,classification_citations=[],
            classification_basis_status='legacy_unclassified' if current.classification_contract=='legacy-v0' else 'not_recorded',
            source_kind=snapshot['source_kind'],source_change_id=snapshot['source_change_id'])

    def summary(self,pid):
        confirmed=[];pending=[];excluded=[]
        for row in self.facts:
            if row.project_id!=pid:continue
            f=self.views[row.id]
            if f.status=='pending':pending.append(f)
            elif f.status in ('user_confirmed','evidence_supported'):
                if f.classification_contract=='legacy-v0' or (f.fact_kind=='personal_action' and f.progress_stage=='completed'):
                    confirmed.append(f)
                else:excluded.append(dto.Excluded(fact=f,reason=REASONS[f.classification_contract] if f.classification_contract in REASONS else REASONS[f.fact_kind]))
        return dto.SummaryV2(project_id=pid,context_revision=self.session.context_revision,
            confirmed=confirmed,pending=pending,reviewed_non_contributions=excluded,
            text='\n'.join(f.statement for f in confirmed),incomplete=not confirmed)

    def export(self):
        history=[dto.ChangeBackup(**raw(c),before_classification=classification(c.before) if c.before is not None else None,
                                  after_classification=classification(c.after)) for c in self.history]
        turns=[schemas.TurnView(**raw(t),answered_questions=[dict(question_id=a.question_id,question_version=a.question_version)
                    for a in sorted(self.answers,key=lambda a:a.slot) if a.turn_id==t.id]) for t in self.turns]
        data=dto.SessionBackup(**raw(self.session,omit=('access_token_hash',)),
            projects=[schemas.ProjectView.model_validate(p) for p in self.projects],turns=turns,
            facts=list(self.views.values()),evidence=[schemas.EvidenceView.model_validate(e) for e in self.evidence],history=history,
            fact_sources=[raw(s) for s in sorted(self.sources,key=lambda s:(str(s.fact_id),str(s.turn_id)))],
            fact_change_sources=[raw(s) for s in self.fcs],
            conversation_operations=[raw(o,omit=('key_digest','submission_tag','request_tag')) for o in self.operations],
            mining_runs=[raw(r) for r in self.runs],mining_questions=[raw(q) for q in self.questions],
            answer_questions=[raw(a) for a in sorted(self.answers,key=lambda a:(str(a.turn_id),a.slot))])
        return dto.ExportV2(exported_at=utcnow(),data=data)
