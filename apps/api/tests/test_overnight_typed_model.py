"""SIMULATED state transitions, not PostgreSQL/crypto/process guarantees."""
from dataclasses import asdict, replace, FrozenInstanceError
from itertools import permutations, product
import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.read_contract import Classification
from overnight_research.typed_model import (State,SimSession,SimReceipt,SimChange,SimSource,
    SimTurn,Item,Command,Snapshot,Outcome,CONTRACT,WINDOW,FAULTS,SimulatedCrash,ModelInvalid,
    digest,validate,submit,recover,delete_session,legacy_capability)
from test_typed_semantic_spike import candidate


def initial():return State((SimSession('s1','p1','u1'),SimSession('s2','p2','u2')))


def command(raw='我部署了服务。',*,key='SIM-A',kind='personal_action',stage='completed',quotes=None,revision=1):
    return Command('s1','p1',key,0,revision,raw,
        tuple(Item(**i) for i in candidate(raw,kind,stage,quotes=quotes)['items']))


def applied():
    state,result=submit(initial(),command(),'u1')
    assert result.code=='simulated_applied'
    return state


def review_fixture(state,status):
    """Arrange a later reviewed state, NOT a classify/review command."""
    fact=state.facts[0];after=replace(fact.current,status=status,version=fact.current.version+1)
    change=SimChange('sim-later-review-'+str(after.version),fact.session,fact.id,fact.current,after,'status_changed','user')
    return replace(state,facts=(replace(fact,current=after),)+state.facts[1:],
        changes=state.changes+(change,),sessions=tuple(replace(s,revision=s.revision+1) if s.id=='s1' else s for s in state.sessions))


def safe(outcome):
    assert outcome.evidence_class=='SIMULATED'
    assert outcome.source_binding=='SIMULATED_ONLY' and outcome.semantic_independence=='NOT_PROVEN'
    assert outcome.transaction_review_required is True
    assert outcome.truth_verified is False and outcome.persistence_authorized is False


@pytest.mark.parametrize('n',range(1,6))
def test_simulated_n_item_atomic_graph_pending_v1_and_declaration_basis(n):
    sentences=['我部署了服务。','我编写了脚本。','我制作了🧪原型图。','我测试了导出按钮。','我整理了27条缺失记录。'][:n]
    original=initial();cmd=command('\r\n'.join(sentences),quotes=sentences)
    state,r=submit(original,cmd,'u1');safe(r);validate(state)
    assert r.code=='simulated_applied' and len(r.facts)==n
    assert len(state.turns)==1 and state.turns[0].content==cmd.content
    assert len(state.facts)==len(state.changes)==len(state.sources)==len(state.audits)==len(state.bases)==n
    assert len(state.receipts)==1 and original==initial()
    assert [a.slot for a in state.audits]==list(range(1,n+1))
    assert all(f.current.status=='pending' and f.current.version==1 and f.current.evidence_id is None for f in state.facts)
    assert all(c.before is None and c.actor=='system' and c.after.origin=='manual' and c.after.ai_run_id is None for c in state.changes)
    assert all(b.evidence_class=='SIMULATED_DECLARATION_ONLY' for b in state.bases)
    assert all(b.source==s for b,s in zip(state.bases,state.sources))
    replay,again=submit(state,cmd,'u1');safe(again)
    assert replay is state and again.code=='replayed' and again.facts==r.facts
    before=asdict(state);got=recover(state,'s1','SIM-A','u1');safe(got)
    assert got.code=='recovered' and got.facts==r.facts and asdict(state)==before


@pytest.mark.parametrize('raw,kind,stage',[
    ('我正在部署服务。','personal_action','in_progress'),('我计划部署服务。','plan','planned'),
    ('我正在准备部署服务。','plan','in_progress'),('我们部署了服务。','background','not_applicable'),
    ('我没有部署服务。','boundary','not_applicable')])
def test_simulated_type_progress_and_trust_are_independent(raw,kind,stage):
    state,r=submit(initial(),command(raw,kind=kind,stage=stage),'u1');safe(r)
    assert r.code=='simulated_applied'
    snap=state.facts[0].current
    assert (snap.fact_kind,snap.progress_stage,snap.status)==(kind,stage,'pending')


@pytest.mark.parametrize('point',FAULTS)
def test_simulated_fault_boundary_and_get_only_recovery_not_process_crash(point):
    original=initial();cmd=command('我部署了服务。我编写了脚本。',quotes=['我部署了服务。','我编写了脚本。'])
    with pytest.raises(SimulatedCrash) as exc:submit(original,cmd,'u1',fault=point)
    durable=exc.value.durable_model;validate(durable)
    assert original==initial()
    got=recover(durable,'s1','SIM-A','u1');safe(got)
    if point=='after_commit':
        assert got.code=='recovered' and len(durable.facts)==2
        replay,r=submit(durable,cmd,'u1');assert replay is durable and r.code=='replayed'
    else:
        assert durable is original and got.code=='receipt_not_found'


@pytest.mark.parametrize('field,value',[
    ('base_revision',99),('project','p2'),('content','我编写了脚本。'),
    ('fact_kind','plan'),('progress_stage','in_progress'),('classification_contract','unclassified-v1'),
    ('quote','我部署了推荐服务。'),('start',1),('end',2)])
def test_simulated_same_key_payload_identity_covers_every_declared_field(field,value):
    state=applied();cmd=command()
    changed=replace(cmd,**{field:value}) if field in ('base_revision','project','content') else replace(cmd,items=(replace(cmd.items[0],**{field:value}),))
    after,r=submit(state,changed,'u1');safe(r)
    assert after is state and r.code=='payload_mismatch'


@pytest.mark.parametrize('version',[0,1,2,4,True,'3',None])
def test_simulated_unknown_new_contract_never_uses_old_writer(version):
    state=initial();after,r=submit(state,replace(command(),contract_version=version),'u1');safe(r)
    assert after is state and r.code=='contract_unsupported'


@pytest.mark.parametrize('version',[1,2])
def test_simulated_opaque_old_receipt_isolated_both_directions(version):
    old=SimReceipt('sim-old',digest('SIM-OLD'),digest('s1'),digest('u1'),version,
        {1:'explicit-target-v1',2:'append-batch-v1'}[version],'sim-tag',WINDOW,session='s1',opaque_legacy=True)
    state=replace(initial(),receipts=(old,));validate(state)
    assert recover(state,'s1','SIM-OLD','u1',version=version).code=='recovered'
    assert recover(state,'s1','SIM-OLD','u1',version=3).code=='contract_mismatch'
    after,r=submit(state,command(key='SIM-OLD'),'u1')
    assert after is state and r.code=='contract_mismatch'
    new,r=submit(state,command(),'u1');assert r.code=='simulated_applied'
    assert recover(new,'s1','SIM-A','u1',version=version).code=='contract_mismatch'
    assert recover(new,'s1','SIM-OLD','u1',version=version).code=='recovered'


@pytest.mark.parametrize('case',['same_key','same_key_other_body','different_key'])
def test_simulated_both_serial_orders_are_not_real_connection_concurrency(case):
    a=command();b=command() if case=='same_key' else command('我编写了脚本。',key='SIM-B' if case=='different_key' else 'SIM-A')
    for first,second in permutations((a,b)):
        state,r=submit(initial(),first,'u1');assert r.code=='simulated_applied'
        after,r=submit(state,second,'u1');safe(r)
        assert after is state and len(after.facts)==1
        assert r.code=={'same_key':'replayed','same_key_other_body':'payload_mismatch','different_key':'context_conflict'}[case]


def test_simulated_exact_reuse_and_rejected_unrelated_work_need_review():
    state=applied();revision=state.sessions[0].revision
    after,r=submit(state,command(key='SIM-B',revision=revision),'u1')
    assert after is state and r.code=='exact_reuse'
    for status in ('user_confirmed','rejected'):
        reviewed=review_fixture(state,status);validate(reviewed)
        # Original receipt takes precedence over later context/status history.
        after,replayed=submit(reviewed,command(),'u1')
        assert after is reviewed and replayed.code=='replayed'
        if status=='rejected':
            fresh=command('我编写了脚本。',key='SIM-B',revision=reviewed.sessions[0].revision)
            after,r=submit(reviewed,fresh,'u1')
            assert after is reviewed and r.code=='history_requires_review'


def test_simulated_finite_risk_hint_is_not_a_general_semantic_oracle():
    cmd=command('我测试了3个导出按钮。');state,r=submit(initial(),cmd,'u1')
    fresh=command('我验证了3个导出按钮。',key='SIM-B',revision=state.sessions[0].revision)
    after,r=submit(state,fresh,'u1');safe(r)
    assert after is state and r.code=='semantic_review_required'


def test_simulated_no_family_match_can_still_be_a_related_claim_not_write_authority():
    state=applied()  # 我部署了服务。
    # Both finite c3a sentences match. The public adversarial hint list does
    # not establish whether this is the same service or an independent one.
    fresh=command('我部署了推荐服务。',key='SIM-B',revision=state.sessions[0].revision)
    after,r=submit(state,fresh,'u1');safe(r)
    assert r.code=='simulated_applied' and len(after.facts)==2
    assert not r.persistence_authorized and r.semantic_independence=='NOT_PROVEN'


@pytest.mark.parametrize('case',['wrong_owner','foreign_session','foreign_project','bad_revision','bool_revision',
    'ended','legacy_mode','reserved','running','unknown','future_key','expired_key'])
def test_simulated_authorization_revision_and_lifecycle_denial(case):
    state=initial();cmd=command();principal='u1';now=0
    expected={'wrong_owner':'resource_unavailable','foreign_session':'resource_unavailable','foreign_project':'resource_unavailable',
        'bad_revision':'context_conflict','bool_revision':'context_conflict','ended':'session_ended','legacy_mode':'creation_contract_unavailable',
        'reserved':'unresolved_run','running':'unresolved_run','unknown':'unresolved_run','future_key':'key_invalid','expired_key':'key_expired'}[case]
    if case=='wrong_owner':principal='u2'
    elif case=='foreign_session':cmd=replace(cmd,session='s2')
    elif case=='foreign_project':cmd=replace(cmd,project='p2')
    elif case in ('bad_revision','bool_revision'):cmd=replace(cmd,base_revision=99 if case=='bad_revision' else True)
    elif case=='ended':state=replace(state,sessions=(replace(state.sessions[0],active=False),state.sessions[1]))
    elif case=='legacy_mode':state=replace(state,sessions=(replace(state.sessions[0],mode='legacy_model'),state.sessions[1]))
    elif case in ('reserved','running','unknown'):state=replace(state,sessions=(replace(state.sessions[0],worker_state=case),state.sessions[1]))
    elif case=='future_key':cmd=replace(cmd,issued_at=1)
    else:now=WINDOW
    after,r=submit(state,cmd,principal,now=now);safe(r)
    assert after is state and r.code==expected


@pytest.mark.parametrize('case',['quote_number','offset','partial','order','overlap','extra_sentence','plan_as_done','team_as_person','unknown'])
def test_simulated_language_and_source_rejections_are_atomic(case):
    cmd=command('我整理了27条缺失记录。')
    if case=='quote_number':cmd=replace(cmd,items=(replace(cmd.items[0],quote='我整理了28条缺失记录。'),))
    elif case=='offset':cmd=replace(cmd,items=(replace(cmd.items[0],start=True),))
    elif case=='partial':cmd=replace(cmd,items=(replace(cmd.items[0],end=11,quote=cmd.content[:11]),))
    elif case in ('order','overlap'):
        cmd=command('我部署了服务。我编写了脚本。',quotes=['我部署了服务。','我编写了脚本。'])
        cmd=replace(cmd,items=tuple(reversed(cmd.items)) if case=='order' else cmd.items+(cmd.items[0],))
    elif case=='extra_sentence':cmd=replace(cmd,content=cmd.content+'我部署了服务。')
    else:cmd=command({'plan_as_done':'我计划部署服务。','team_as_person':'我们部署了服务。','unknown':'未知表达。'}[case])
    state=initial();after,r=submit(state,cmd,'u1');safe(r)
    assert after is state and r.code=='language_or_quote_rejected'


@pytest.mark.parametrize('corruption',['current_label','memory','origin','ai_run','version_bool','created_before',
    'created_trust','source_range','source_quote','source_missing','history_missing','basis_missing','basis_rule',
    'basis_type','audit_missing','audit_slot','audit_bool_slot','basis_bool_slot','audit_source_bool',
    'extra_turn','receipt_version','receipt_decision','receipt_tag','receipt_digest','worker_unknown'])
def test_simulated_graph_integrity_failure_no_partial_read_or_write(corruption):
    state=applied();fact=state.facts[0];change=state.changes[0]
    if corruption in ('current_label','memory','origin','ai_run','version_bool'):
        attrs={'current_label':dict(fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0'),
            'memory':dict(memory_state='certain'),'origin':dict(origin='ai_extracted'),'ai_run':dict(ai_run_id='forged'),
            'version_bool':dict(version=True)}[corruption]
        state=replace(state,facts=(replace(fact,current=replace(fact.current,**attrs)),))
    elif corruption=='created_before':state=replace(state,changes=(replace(change,before=change.after),))
    elif corruption=='created_trust':state=replace(state,changes=(replace(change,after=replace(change.after,status='user_confirmed')),))
    elif corruption in ('source_range','source_quote'):
        state=replace(state,sources=(replace(state.sources[0],**({'start':True} if corruption=='source_range' else {'quote':'伪造'})),))
    elif corruption=='source_missing':state=replace(state,sources=())
    elif corruption=='history_missing':state=replace(state,changes=())
    elif corruption=='basis_missing':state=replace(state,bases=())
    elif corruption=='basis_rule':state=replace(state,bases=(replace(state.bases[0],validation_contract='unknown'),))
    elif corruption=='basis_type':state=replace(state,bases=(replace(state.bases[0],fact_kind='plan'),))
    elif corruption=='audit_missing':state=replace(state,audits=())
    elif corruption=='audit_slot':state=replace(state,audits=(replace(state.audits[0],slot=2),))
    elif corruption=='audit_bool_slot':state=replace(state,audits=(replace(state.audits[0],slot=True),))
    elif corruption=='basis_bool_slot':state=replace(state,bases=(replace(state.bases[0],slot=True),))
    elif corruption=='audit_source_bool':
        state=replace(state,audits=(replace(state.audits[0],source=replace(state.sources[0],end=True)),))
    elif corruption=='extra_turn':state=replace(state,turns=state.turns+(SimTurn('extra','s1','我部署了服务。'),))
    elif corruption=='worker_unknown':state=replace(state,sessions=(replace(state.sessions[0],worker_state='unrecognized'),state.sessions[1]))
    elif corruption=='receipt_tag':state=replace(state,receipts=(replace(state.receipts[0],request_tag=None),))
    elif corruption=='receipt_digest':state=replace(state,receipts=(replace(state.receipts[0],key_digest='invalid'),))
    else:state=replace(state,receipts=(replace(state.receipts[0],**({'contract_version':99} if corruption=='receipt_version' else {'decision_contract':'unknown'})),))
    after,r=submit(state,command('我编写了脚本。',key='SIM-B',revision=2),'u1');safe(r)
    assert after is state and r.code=='integrity_unavailable'
    assert recover(state,'s1','SIM-A','u1').code=='integrity_unavailable'
    assert recover(state,'s1','SIM-A','foreign').code=='resource_unavailable'


def test_simulated_expiry_never_renews_receipts_and_deleted_scope_is_private():
    state=applied();old=asdict(state)
    assert recover(state,'s1','SIM-A','u1',now=WINDOW).code=='receipt_expired'
    assert asdict(state)==old
    after,r=submit(state,replace(command(),issued_at=1),'u1',now=1)
    assert after is state and r.code=='key_metadata_mismatch'
    denied,r=delete_session(state,'s1','u2');assert denied is state and r.code=='resource_unavailable'
    deleted,r=delete_session(state,'s1','u1');safe(r);validate(deleted)
    assert deleted.sessions==(state.sessions[1],) and deleted.facts==() and deleted.turns==()
    tomb=deleted.receipts[0]
    assert tomb.state=='deleted' and tomb.request_tag is None and tomb.session is None and tomb.turn is None
    encoded=json.dumps(asdict(tomb),ensure_ascii=False)
    assert '我部署' not in encoded and 's1' not in encoded and 'u1' not in encoded
    assert recover(deleted,'s1','SIM-A','u1').code=='resource_deleted'
    assert recover(deleted,'s1','SIM-A','u2').code=='resource_unavailable'
    reborn=replace(deleted,sessions=initial().sessions)
    after,r=submit(reborn,command(),'u1')
    assert after is reborn and r.code=='resource_deleted' and after.facts==()


@pytest.mark.parametrize('capability',['receipt_recovery','end','delete','worker_finalize'])
def test_simulated_capabilities_are_not_uniformly_blocked_as_writes(capability):
    state=applied();safe(legacy_capability(state,'s1','u1',capability))
    assert legacy_capability(state,'s1','u1',capability).code=='separate_existing_capability_not_implemented'
    assert legacy_capability(state,'s1','u1','fresh_fact_command').code=='legacy_upgrade_required'


def test_simulated_get_does_not_call_submit_and_model_remains_unrouted(monkeypatch):
    import overnight_research.typed_model as model
    state=applied()
    def forbidden(*args,**kwargs):raise AssertionError('GET cannot submit')
    monkeypatch.setattr(model,'submit',forbidden)
    assert recover(state,'s1','SIM-A','u1').code=='recovered'
    with pytest.raises(FrozenInstanceError):state.next_id=99
    path=Path(model.__file__);tree=ast.parse(path.read_text(encoding='utf8'))
    imports={n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
    imports|={a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
    assert imports=={'dataclasses','hashlib','json','pydantic','app.read_contract','app.typed_semantic_spike','r03'}
    for file in (Path(__file__).parents[1]/'app').rglob('*.py'):
        assert 'overnight_research' not in file.read_text(encoding='utf8')
    assert all(not getattr(Outcome('test'),key) for key in ('truth_verified','persistence_authorized'))


@pytest.mark.parametrize('status',['pending','user_confirmed'])
def test_simulated_historical_rejection_survives_restored_current_status(status):
    state=review_fixture(review_fixture(applied(),'rejected'),status);validate(state)
    assert recover(state,'s1','SIM-A','u1').code=='recovered'
    after,r=submit(state,command('我编写了脚本。',key='SIM-B',revision=state.sessions[0].revision),'u1')
    assert after is state and r.code=='history_requires_review'


@pytest.mark.parametrize('field,value',[('decision_contract','unknown'),('contract_version',99),('request_tag','retained-private-tag')])
def test_simulated_tombstone_contract_and_privacy_remain_validated(field,value):
    state,_=delete_session(applied(),'s1','u1')
    damaged=replace(state,receipts=(replace(state.receipts[0],**{field:value}),))
    assert recover(damaged,'s1','SIM-A','u1').code=='integrity_unavailable'
    assert recover(damaged,'s1','SIM-A','foreign').code=='resource_unavailable'


def test_model_reuses_classification_and_language_contract_instead_of_inventing_rules():
    import overnight_research.typed_model as model
    from app.typed_semantic_spike import validate_candidate
    assert model.Classification is Classification and model.validate_candidate is validate_candidate
    for kind,stage,contract in product(
        ('legacy_unspecified','personal_action','plan','background','boundary'),
        ('legacy_unknown','in_progress','completed','planned','not_applicable'),
        ('legacy-v0','unclassified-v1','explicit-typed-v1')):
        valid=(kind=='legacy_unspecified' and stage=='legacy_unknown' and contract in ('legacy-v0','unclassified-v1')) or (
            contract=='explicit-typed-v1' and (kind,stage) in {
                ('personal_action','in_progress'),('personal_action','completed'),('plan','planned'),
                ('plan','in_progress'),('background','not_applicable'),('boundary','not_applicable')})
        values=dict(fact_kind=kind,progress_stage=stage,classification_contract=contract)
        if valid:Classification(**values)
        else:
            with pytest.raises(ValidationError):Classification(**values)
