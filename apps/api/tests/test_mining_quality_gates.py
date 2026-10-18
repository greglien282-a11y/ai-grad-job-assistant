"""DRAFT gate fixtures checked against the real, unchanged business state machine.

Random PostgreSQL test schema only. No real Provider, secrets or paid ledger.
"""
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func,select

from test_http_api import api
from test_mining import stack,request,aggregate
from app.main import app
from app.mining_api import get_provider
from app.mining_context import build_context
from app.mining_fake import ContextFakeProvider
from app.mining_quality_data import load_dataset
from app.models import ExperienceSession,MiningRun,ExperienceFact


class CountingFake(ContextFakeProvider):
    def __init__(self): self.calls=0

    async def mine(self,context):
        self.calls+=1
        return await super().mine(context)


@pytest.mark.parametrize('case_id',['GQ15','GQ17'])
def test_business_gate_history_matches_build_context_and_blocks_dispatch(stack,case_id):
    client,factory,_,data,auth=stack
    _,cases=load_dataset();case=next(c for c in cases if c.case_id==case_id)
    fake=CountingFake();app.dependency_overrides[get_provider]=lambda:fake
    turns={t.turn_id:t for t in case.turns}
    latest=None
    for history in case.gate_history:
        turn=turns[history.input_turn_id]
        url,headers,body=request(stack,turn.text)
        response=client.post(url,headers=headers,json=body)
        assert response.status_code==201
        latest=response.json()
        assert latest['state']=='completed'
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ExperienceFact).where(
                ExperienceFact.ai_run_id==UUID(latest['id'])))==history.added_facts
    if case_id=='GQ15':
        response=client.post('/api/v1/experience/sessions/'+data['session_id']+'/mining-stop',
            headers=auth,json={'base_revision':aggregate(client,data,auth)['context_revision']})
        assert response.status_code==200
    with factory() as db:
        session=db.get(ExperienceSession,UUID(data['session_id']))
        assert session.mining_status=='stopped'
        # Read-only snapshot comparison, not a new reserved run or dispatch.
        # A completed run's old reserved_revision is not relabeled as current.
        snapshot=build_context(db,SimpleNamespace(session_id=session.id,
            project_id=UUID(data['project_id']),input_turn_id=UUID(latest['input_turn_id']),
            reserved_revision=session.context_revision),session)
        assert snapshot.stop.model_dump()==case.stop_context
        run_count=db.scalar(select(func.count()).select_from(MiningRun))
        fact_count=db.scalar(select(func.count()).select_from(ExperienceFact))
    calls=fake.calls
    # Even a new operation key and syntactically valid answer must not dispatch.
    url,headers,body=request(stack,'合成：试图在业务停止后继续。')
    response=client.post(url,headers=headers,json=body)
    assert response.status_code==409 and response.json()['error']['code']=='mining_stopped'
    assert fake.calls==calls==len(case.gate_history)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MiningRun))==run_count
        assert db.scalar(select(func.count()).select_from(ExperienceFact))==fact_count
