"""M2 SIMULATED diagnostics + OBSERVED_EXISTING_BEHAVIOR; never new guarantees."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import facts
from app.models import ExperienceFact, ExperienceSession
from app.typed_semantic_spike import validate_candidate
from overnight_research.r03 import Assessment, Claim, Source, Record, LABELS, assess
from test_http_api import api
from test_maintenance_api import service, seed
from test_append_api import append_service, legacy_rejected_history, body as append_body, post as append_post
from test_cutoff_preflight import preflight, auth, ROOT
from test_idempotency import headers
from test_legacy_upgrade_handoff import digest
from test_typed_semantic_spike import candidate

CORPUS=json.loads((Path(__file__).parent/'overnight_research/r03_cases.json').read_text(encoding='utf8'))


def arranged(case):
    relation=case['source'];source=Source('old',0,12)
    current=Source('new',0,len(case['new']))
    if relation=='overlap':current=Source('old',0,7)
    elif relation=='disjoint':current=Source('old',20,27)
    elif relation=='unknown':source=Source('old');current=Source('old',20,27)
    past=((case.get('prior',case['old']),'rejected'),) if case['past'] else ()
    return Claim(case['new'],current),(Record(case['old'],case['status'],past,(source,)),)


@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda c:c['id'])
def test_simulated_adversarial_labels_and_unchanged_language(case):
    claim,history=arranged(case);copy=deepcopy((claim,history));r=assess(claim,history)
    expected={'INDEPENDENCE_NOT_PROVEN',*case['expected']}
    if case['expected']:expected.add('NEEDS_HUMAN_DECISION')
    assert set(r.labels)==expected and set(r.labels)<=LABELS
    assert r.conservative_block==(case['status']=='rejected' or case['past'])
    assert r.evidence_class=='SIMULATED' and r.source_binding=='NOT_CHECKED'
    assert not r.truth_verified and not r.persistence_authorized
    assert r.semantic_independence=='NOT_PROVEN' and (claim,history)==copy
    assert assess(claim,history)==r
    assert validate_candidate(candidate(case['new'])).status==case['language']
    with pytest.raises(FrozenInstanceError):r.persistence_authorized=True


def test_blanket_policy_cost_is_explicit_and_not_a_population_accuracy_claim():
    unrelated=[c for c in CORPUS['cases'] if c.get('unrelated')]
    blocked=[c for c in unrelated if assess(*arranged(c)).conservative_block]
    assert len(unrelated)==6 and len(blocked)==5
    assert len(CORPUS['cases'])==24 and CORPUS['synthetic'] is True
    # All five unrelated cases WITH rejected history are blocked; the clean
    # comparison is not authority to persist even though blanket_block=False.
    clean=next(c for c in unrelated if c['id']=='no_rejection_unrelated')
    assert assess(*arranged(clean)).labels==('INDEPENDENCE_NOT_PROVEN',)


@pytest.mark.parametrize('bad',[Source(''),Source('t',True,3),Source('t',0,None),Source('t',3,2)])
def test_malformed_synthetic_source_is_not_a_safety_verdict(bad):
    with pytest.raises(ValueError,match='synthetic_input_invalid'):assess(Claim('synthetic',bad),())


@pytest.mark.parametrize('entry',['manual','mining','append'])
@pytest.mark.parametrize('new',['我测试了三个导出按钮。','我验证了3个导出按钮。','我部署了服务。'])
def test_observed_cross_entry_reassertion_and_unrelated_availability(preflight,entry,new):
    s=preflight;b=seed(s,status='rejected');before=digest(s.admin)
    if entry=='append':
        r=append_post(s,b,append_body(b,[new]))
        assert r.status_code==409 and r.json()['error']['code']=='append_requires_clarification'
        assert digest(s.admin)==before and s.provider.calls==0
    elif entry=='manual':
        turn=s.client.post(ROOT+f'/sessions/{b.sid}/turns',headers=auth(b),json={'content':new})
        assert turn.status_code==201
        r=s.client.post(ROOT+f'/projects/{b.pid}/facts',headers=auth(b),json={'statement':new,'source_turn_ids':[turn.json()['id']]})
        assert r.status_code==201 and s.provider.calls==0
    else:
        h,_=headers('mining_run',f'session:{b.sid}',b.token)
        r=s.client.post(ROOT+f'/sessions/{b.sid}/mining-runs',headers=h,
            json={'project_id':str(b.pid),'base_revision':b.revision,'content':new})
        assert r.status_code==201 and r.json()['state']=='completed' and s.provider.calls==1
    with s.admin() as db:
        assert db.get(ExperienceFact,b.fid).status=='rejected'
        found=db.scalar(select(ExperienceFact).where(ExperienceFact.session_id==b.sid,ExperienceFact.statement==new))
        assert (found is None)==(entry=='append')
        if found is not None:assert found.status=='pending' and found.classification_contract=='legacy-v0'
        assert db.scalar(text('SELECT count(*) FROM paid_calls'))==0


@pytest.mark.parametrize('current',['pending','user_confirmed'])
def test_observed_history_only_gap_and_append_history_gate(preflight,current):
    s=preflight;b=seed(s);old=legacy_rejected_history(s,b,current,'both')
    # Existing shared guard only SELECTs currently rejected rows. This direct
    # domain observation runs on the restricted legacy identity, not owner.
    with s.legacy.begin() as db:
        facts.authorize(db,b.sid,b.token,lock=True)
        turn=facts.add_turn(db,b.sid,b.token,'我维护了新的旧记录清单。')
        added=facts.add_fact(db,b.pid,b.token,'我维护了旧记录清单。',[turn.id])
        assert added.status=='pending'
    with s.admin() as db:
        assert db.get(ExperienceFact,old).status==current
        b.revision=db.get(ExperienceSession,b.sid).context_revision
    before=digest(s.admin)
    r=append_post(s,b,append_body(b,['我部署了服务。']))
    assert r.status_code==409 and r.json()['error']['code']=='append_requires_clarification'
    assert digest(s.admin)==before


def test_observed_exact_rejection_can_leave_a_separately_saved_legacy_turn(preflight):
    s=preflight;b=seed(s,status='rejected');raw='我测试了3个导出按钮。'
    turn=s.client.post(ROOT+f'/sessions/{b.sid}/turns',headers=auth(b),json={'content':raw})
    assert turn.status_code==201
    before_fact=digest(s.admin)
    r=s.client.post(ROOT+f'/projects/{b.pid}/facts',headers=auth(b),json={'statement':raw,'source_turn_ids':[turn.json()['id']]})
    assert r.status_code==409 and r.json()['error']['code']=='fact_rejected_immutable'
    assert digest(s.admin)==before_fact
    with s.admin() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_turns WHERE session_id=:sid'),{'sid':b.sid})==2
        assert db.scalar(text('SELECT count(*) FROM experience_facts WHERE session_id=:sid'),{'sid':b.sid})==1


def test_research_has_no_production_import_or_language_modification():
    root=Path(__file__).parents[1]/'app'
    for file in root.rglob('*.py'):
        assert 'overnight_research' not in file.read_text(encoding='utf8')
    assert Assessment.__dataclass_params__.frozen
