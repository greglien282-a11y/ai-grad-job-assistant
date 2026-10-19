"""Inert B2-a metadata. No endpoint, parser, Provider or runtime writer."""
from datetime import datetime
from uuid import UUID,uuid4
from sqlalchemy import (CheckConstraint,DateTime,ForeignKeyConstraint,Index,Integer,
    SmallInteger,String,Text,UniqueConstraint,Uuid,func,text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column
from app.models import Base


class ConversationOperation(Base):
    __tablename__='conversation_operations'
    __table_args__=(
        UniqueConstraint('id','session_id',name='uq_co_session'),
        ForeignKeyConstraint(['session_id'],['experience_sessions.id'],deferrable=True,initially='DEFERRED'),
        ForeignKeyConstraint(['input_turn_id','session_id'],['conversation_turns.id','conversation_turns.session_id'],deferrable=True,initially='DEFERRED'),
        ForeignKeyConstraint(['target_fact_id','session_id'],['experience_facts.id','experience_facts.session_id'],deferrable=True,initially='DEFERRED'),
        ForeignKeyConstraint(['parent_operation_id','session_id'],['conversation_operations.id','conversation_operations.session_id'],deferrable=True,initially='DEFERRED'),
        CheckConstraint("contract_version IN (1,2) AND key_digest ~ '^[a-f0-9]{64}$' AND state IN ('applied','needs_clarification','deleted')",name='ck_co_identity'),
        CheckConstraint('expires_at>created_at',name='ck_co_expiry'),
        CheckConstraint("((state='deleted' AND num_nonnulls(session_id,input_turn_id,kind,action,parent_operation_id,submission_tag,request_tag,proposed_action,proposal_spans,progress_stage,base_revision,result_revision,target_fact_id,target_version,effect_count,outcome_code,decision_contract,completed_at)=0) OR (state<>'deleted' AND session_id IS NOT NULL AND input_turn_id IS NOT NULL AND kind IS NOT NULL AND action IS NOT NULL AND proposal_spans IS NOT NULL AND base_revision>0 AND result_revision>=base_revision AND effect_count BETWEEN 0 AND 5 AND request_tag ~ '^[a-f0-9]{64}$' AND ((contract_version=1 AND decision_contract='explicit-target-v1') OR (contract_version=2 AND decision_contract='append-batch-v1')) AND completed_at>=created_at)) IS TRUE",name='ck_co_shape'),
        Index('uq_co_submission','session_id','submission_tag',unique=True,postgresql_where=text("kind='root' AND state<>'deleted'")),
        Index('uq_co_resolution','parent_operation_id',unique=True,postgresql_where=text("state<>'deleted'")),
        Index('ix_co_session_created','session_id','created_at','id'),
        Index('ix_co_input','input_turn_id'),
        Index('ix_co_expired','expires_at',postgresql_where=text("state='deleted'")),)
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,default=uuid4)
    contract_version:Mapped[int]=mapped_column(SmallInteger,nullable=False,default=1)
    key_digest:Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    state:Mapped[str]=mapped_column(String(24),nullable=False)
    session_id:Mapped[UUID|None]=mapped_column(Uuid)
    input_turn_id:Mapped[UUID|None]=mapped_column(Uuid)
    kind:Mapped[str|None]=mapped_column(String(16))
    action:Mapped[str|None]=mapped_column(String(24))
    parent_operation_id:Mapped[UUID|None]=mapped_column(Uuid)
    submission_tag:Mapped[str|None]=mapped_column(String(64))
    request_tag:Mapped[str|None]=mapped_column(String(64))
    proposed_action:Mapped[str|None]=mapped_column(String(24))
    proposal_spans:Mapped[list|None]=mapped_column(JSONB)
    progress_stage:Mapped[str|None]=mapped_column(String(24))
    base_revision:Mapped[int|None]=mapped_column(Integer)
    result_revision:Mapped[int|None]=mapped_column(Integer)
    target_fact_id:Mapped[UUID|None]=mapped_column(Uuid)
    target_version:Mapped[int|None]=mapped_column(Integer)
    effect_count:Mapped[int|None]=mapped_column(SmallInteger)
    outcome_code:Mapped[str|None]=mapped_column(String(32))
    decision_contract:Mapped[str|None]=mapped_column(String(32))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))


class FactChangeSource(Base):
    __tablename__='fact_change_sources'
    __table_args__=(
        ForeignKeyConstraint(['change_id','fact_id','session_id'],['fact_changes.id','fact_changes.fact_id','fact_changes.session_id'],ondelete='CASCADE'),
        ForeignKeyConstraint(['operation_id','session_id'],['conversation_operations.id','conversation_operations.session_id'],deferrable=True,initially='DEFERRED'),
        ForeignKeyConstraint(['turn_id','session_id'],['conversation_turns.id','conversation_turns.session_id'],deferrable=True,initially='DEFERRED'),
        UniqueConstraint('change_id','source_role',name='uq_fcs_change_role'),
        UniqueConstraint('operation_id','effect_slot','source_role',name='uq_fcs_effect_role'),
        CheckConstraint("effect_slot BETWEEN 1 AND 5 AND source_role IN ('statement','intent') AND reason IN ('addition','explicit_correction','explicit_withdrawal','progress_update')",name='ck_fcs_kind'),
        CheckConstraint("start_cp>=0 AND end_cp>start_cp AND length(quote) BETWEEN 1 AND 10000 AND (source_role<>'statement' OR length(quote)<=500)",name='ck_fcs_quote'),
        CheckConstraint('after_version>0 AND (before_version IS NULL OR before_version>0)',name='ck_fcs_versions'),
        Index('ix_fcs_fact_version','fact_id','after_version'),Index('ix_fcs_turn','turn_id'),)
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,default=uuid4)
    operation_id:Mapped[UUID]=mapped_column(Uuid,nullable=False)
    effect_slot:Mapped[int]=mapped_column(SmallInteger,nullable=False)
    change_id:Mapped[UUID]=mapped_column(Uuid,nullable=False)
    fact_id:Mapped[UUID]=mapped_column(Uuid,nullable=False)
    session_id:Mapped[UUID]=mapped_column(Uuid,nullable=False)
    turn_id:Mapped[UUID]=mapped_column(Uuid,nullable=False)
    source_role:Mapped[str]=mapped_column(String(16),nullable=False)
    reason:Mapped[str]=mapped_column(String(24),nullable=False)
    start_cp:Mapped[int]=mapped_column(Integer,nullable=False)
    end_cp:Mapped[int]=mapped_column(Integer,nullable=False)
    quote:Mapped[str]=mapped_column(Text,nullable=False)
    before_version:Mapped[int|None]=mapped_column(Integer)
    after_version:Mapped[int]=mapped_column(Integer,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
