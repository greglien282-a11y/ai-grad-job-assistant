"""TEST ONLY: fictional zero-ceiling metadata + exact MockTransport seam.

Not a Provider registry or approval interface. Cannot use a real HTTP transport.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID,uuid4
import json
import httpx
from sqlalchemy import select

from app import mining,idempotency
from app.models import ExperienceSession,utcnow
from app.mining_api import Start
from app.mining_context import MiningContext
from app.mining_validation import validate_context_v2
from app.mining_paid_models import MiningPaidIdentity,MiningPaidPlan
from app.paid_models import PaidFunding,PaidGrant
from app.cost_ledger import canonical,digest
from app.deepseek_contract import decode_official,ProbeError
from app.prepared_mining_request import prepare_request,sha,ENDPOINT,VERSION
from app.mining_request_snapshot import read_snapshot
from app.mining_request_admission import admit_offline
from test_idempotency import headers


@dataclass(repr=False)
class Environment:
    client: object
    factory: object
    sid: UUID
    pid: UUID
    initial: UUID
    token: str


def start(e,content=None,*,answers=None,claim=True,**extra):
    with e.factory() as db: revision=db.get(ExperienceSession,e.sid).context_revision
    body=Start(project_id=e.pid,base_revision=revision,answered_question_ids=answers,
        **(extra or ({'content':content} if content is not None else {'input_turn_id':e.initial})))
    h,_=headers('mining_run','session:'+str(e.sid),e.token)
    key=idempotency.parse(h['Idempotency-Key'],e.token,'mining_run','session:'+str(e.sid))
    rid,fresh=mining.reserve(e.factory,e.sid,e.token,key,body)
    assert fresh
    if claim: assert mining.claim(e.factory,e.sid,e.token,rid,contract_version=2) is not None
    return rid,key,body


def stage_zero_projection(e,snapshot,prepared,*,config=VERSION,certificates=None):
    """Cannot authorize spending: zero funding, zero fixture Grant ceiling,
    no valid PaidPolicy, no token/pricing evidence or reserve/send function.
    Required solely to exercise 0011's Grant FK and immutable metadata shape.
    """
    with e.factory.begin() as db:
        if db.get(MiningPaidIdentity,e.sid) is None:
            db.add(MiningPaidIdentity(session_id=e.sid,actor_scope=digest('synthetic actor'),
                session_scope=digest(str(e.sid)),issuer_version='offline-fixture-only'))
            db.flush()
        policy={'execution':'offline_contract_fixture_v1','provider':'deepseek_official',
            'model':'deepseek-flash','account_ref':'synthetic-not-real-account'}
        if certificates is not None: policy['certificates']=certificates
        policy_sha=digest(canonical(policy));gid=uuid4()
        db.add(PaidGrant(id=gid,pool_id=1,approver='synthetic-not-authorization',approval_digest=digest('fixture-'+str(gid)),
            starts_at=utcnow()-timedelta(minutes=1),expires_at=utcnow()+timedelta(minutes=30),revoked=False,
            ceiling=Decimal(0),call_limit=Decimal('.000001'),calls_limit=1,policy_hash=policy_sha,policy=policy))
        db.flush()
        db.add(MiningPaidPlan(run_id=snapshot.run_id,root_run_id=snapshot.root_run_id,session_id=e.sid,
            ledger_id=db.get(PaidFunding,1).ledger_id,grant_id=gid,operation_hash=snapshot.operation_hash,
            receipt_hash=snapshot.receipt_hash,request_sha=prepared.request_sha,policy_sha=policy_sha,
            context_sha=prepared.context_sha,prompt_sha=prepared.prompt_sha,schema_sha=prepared.schema_sha,
            account_sha=digest(policy['account_ref']),provider=prepared.provider,model=prepared.model,
            config_version=config,prompt_version=prepared.prompt_version,schema_version=prepared.schema_version))


def frozen(e,rid):
    source=read_snapshot(e.factory,e.sid,e.token,rid)
    request=prepare_request(source)
    stage_zero_projection(e,source,request)
    return request,read_snapshot(e.factory,e.sid,e.token,rid,require_metadata=True)


def output(context,*,candidate=True,question='是否有可供你本人核对的依据？'):
    turn=context.user_turns[0]
    return dict(schema_version=2,candidates=[dict(citation=dict(turn_id=str(turn.turn_id),
        quote=turn.content,start=0,end=len(turn.content)))] if candidate else [],
        questions=[dict(text=question,purpose='verification',source_turn_ids=[str(turn.turn_id)])],
        stop=False,stop_reason=None)


class OfflinePreparedProvider:
    output_contract_version=2
    def __init__(self,e,rid,transport):
        if type(transport) is not httpx.MockTransport: raise ValueError('offline_mock_required')
        self.e,self.rid,self.transport=e,rid,transport
        self.prepared=None;self.calls=0;self.simulated_usage=None
    def reserve_cost(self): raise mining.MiningError(503,'ai_provider_unapproved')
    async def mine(self,input):
        source=read_snapshot(self.e.factory,self.e.sid,self.e.token,self.rid)
        assert source.context.payload()==input.payload()  # never input.content
        prepared=prepare_request(source)
        stage_zero_projection(self.e,source,prepared)
        admit_offline(self.e.factory,self.e.sid,self.e.token,self.rid,prepared)
        self.prepared=prepared
        self.calls+=1
        try:
            with httpx.Client(transport=self.transport,follow_redirects=False,trust_env=False) as client:
                response=client.post(ENDPOINT,content=prepared.body)
            if response.status_code!=200: raise TimeoutError('offline_outcome_unknown')
            envelope=decode_official(response.content,SimpleNamespace(input_upper_bound=12000,output_cap=prepared.output_cap))
            self.simulated_usage=envelope.usage  # fixture usage ONLY; no pricing
            return validate_context_v2(source.context,envelope.output)
        except httpx.HTTPError:
            raise TimeoutError('offline_outcome_unknown') from None
