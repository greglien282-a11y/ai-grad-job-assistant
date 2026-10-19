"""Audited origins are immutable; unaudited legacy origins are not frozen.

Real PostgreSQL random schemas, synthetic data and independent connections.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import facts
from app.models import ExperienceFact, FactChange, FactSource
from test_fact_maintenance import initial, append_operation, correction, UNICODE
from test_http_api import api
from test_deepseek_mining_integration import offline_guard, test_database_only


def stored(factory):
    """Whole synthetic state, so a failed write cannot hide history/receipt drift."""
    names=('experience_sessions','conversation_turns','experience_facts','fact_sources',
           'fact_changes','fact_change_sources','conversation_operations')
    with factory() as db:
        return {name:db.scalars(text(f'SELECT to_jsonb(t)::text FROM {name} t ORDER BY to_jsonb(t)::text')).all()
                for name in names}


def legacy(factory,b):
    with factory.begin() as db:
        fact=facts.add_fact(db,b.pid,b.token,'我测试了3个导出按钮。',[b.tid])
        return fact.id


def audit(factory,b,kind):
    if kind=='append':
        with factory.begin() as db:return append_operation(db,b).fid
    fid=legacy(factory,b)
    with factory.begin() as db:correction(db,b,fid,action=kind)
    return fid


@pytest.mark.parametrize('kind',['append','correct','withdraw'])
@pytest.mark.parametrize('attack',['citations','delete','insert','move_out','move_in','created_history_delete','truncate'])
def test_committed_audited_origin_attacks_rollback_all_state(api,kind,attack):
    _,factory=api;b=initial(factory)
    other=legacy(factory,b)
    # Both source turns are real user turns in exactly the same session.
    with factory.begin() as db:extra=facts.add_turn(db,b.sid,b.token,UNICODE).id
    fid=audit(factory,b,kind)
    before=stored(factory)
    with pytest.raises(IntegrityError,match='maintenance_(original|history|immutable)'),factory.begin() as db:
        if attack=='citations':
            db.execute(text("UPDATE fact_sources SET citations='[]'::jsonb WHERE fact_id=:f"),{'f':fid})
        elif attack=='delete':db.execute(text('DELETE FROM fact_sources WHERE fact_id=:f'),{'f':fid})
        elif attack=='insert':db.add(FactSource(fact_id=fid,session_id=b.sid,turn_id=extra))
        elif attack=='move_out':
            # Use the extra turn to avoid a pre-existing PK collision.
            db.execute(text('UPDATE fact_sources SET fact_id=:other,turn_id=:t WHERE fact_id=:f'),{'other':other,'t':extra,'f':fid})
        elif attack=='move_in':
            db.execute(text('UPDATE fact_sources SET fact_id=:f,turn_id=:t WHERE fact_id=:other'),{'f':fid,'t':extra,'other':other})
        elif attack=='created_history_delete':
            db.execute(text("DELETE FROM fact_changes WHERE fact_id=:f AND action='created'"),{'f':fid})
        else:db.execute(text('TRUNCATE fact_sources'))
    assert stored(factory)==before


@pytest.mark.parametrize('attack',['citations','delete','insert','noop_update'])
def test_legacy_write_then_first_audit_in_same_transaction_refused(api,attack):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    with factory.begin() as db:extra=facts.add_turn(db,b.sid,b.token,UNICODE).id
    before=stored(factory)
    with pytest.raises(IntegrityError,match='maintenance_original_invalid'),factory.begin() as db:
        if attack=='citations':db.execute(text("UPDATE fact_sources SET citations='[{}]'::jsonb WHERE fact_id=:f"),{'f':fid})
        elif attack=='delete':db.execute(text('DELETE FROM fact_sources WHERE fact_id=:f'),{'f':fid})
        elif attack=='insert':
            db.add(FactSource(fact_id=fid,session_id=b.sid,turn_id=extra));db.flush()
        else:db.execute(text('UPDATE fact_sources SET citations=citations WHERE fact_id=:f'),{'f':fid})
        correction(db,b,fid)
    assert stored(factory)==before


@pytest.mark.parametrize('attack',['citations','insert','delete'])
def test_legacy_drift_committed_before_audit_is_not_silently_certified(api,attack):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    with factory.begin() as db:
        extra=facts.add_turn(db,b.sid,b.token,UNICODE)
        if attack=='citations':db.execute(text("UPDATE fact_sources SET citations='[{}]'::jsonb WHERE fact_id=:f"),{'f':fid})
        elif attack=='insert':db.add(FactSource(fact_id=fid,session_id=b.sid,turn_id=extra.id))
        else:db.execute(text('DELETE FROM fact_sources WHERE fact_id=:f'),{'f':fid})
    before=stored(factory)  # legacy write remains valid; audit must be atomic
    with pytest.raises(IntegrityError,match='maintenance_original_invalid'),factory.begin() as db:
        correction(db,b,fid)
    assert stored(factory)==before


@pytest.mark.parametrize('attack',['extra_row','extra_citation'])
def test_append_rejects_polluted_origin_even_with_self_consistent_creation_snapshot(api,attack):
    _,factory=api;b=initial(factory);before=stored(factory)
    def poison(db,fact,turn,change):
        if attack=='extra_row':
            db.add(FactSource(fact_id=fact.id,session_id=b.sid,turn_id=b.tid))
        else:
            source=db.get(FactSource,(fact.id,turn.id))
            source.citations=source.citations+[dict(turn_id=str(b.tid),quote='我测试了3个导出按钮。',start=0,end=11)]
        db.flush()
        # This is deliberately adversarial fixture-owner code. Even a matching
        # initial history snapshot must not bless extra origins for new append.
        change.after=facts.snapshot(db,fact)
        db.flush()
    with pytest.raises(IntegrityError,match='maintenance_original_source_invalid'),factory.begin() as db:
        append_operation(db,b,before_audit=poison)
    assert stored(factory)==before


def test_legacy_multi_origin_and_null_citations_remain_compatible(api):
    _,factory=api;b=initial(factory)
    with factory.begin() as db:
        extra=facts.add_turn(db,b.sid,b.token,'我记录了测试结果。')
        fact=facts.add_fact(db,b.pid,b.token,'我测试了3个导出按钮。',[b.tid,extra.id]);fid=fact.id
    with factory.begin() as db:correction(db,b,fid)
    with factory.begin() as db:
        facts.change_fact(db,fid,b.token,statement='我测试了1个导出按钮。',expected_version=2)
    with factory() as db:
        rows=db.scalars(select(FactSource).where(FactSource.fact_id==fid)).all()
        assert len(rows)==2 and all(row.citations is None for row in rows)
        assert db.get(ExperienceFact,fid).version==3
        created=db.scalar(select(FactChange).where(FactChange.fact_id==fid,FactChange.action=='created'))
        assert created.after['statement']=='我测试了3个导出按钮。'


def test_unaudited_legacy_dml_and_read_committed_truncate_not_frozen(api):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    with factory.begin() as db:
        extra=facts.add_turn(db,b.sid,b.token,UNICODE)
        db.add(FactSource(fact_id=fid,session_id=b.sid,turn_id=extra.id));db.flush()
        db.execute(text("UPDATE fact_sources SET citations='[]'::jsonb WHERE fact_id=:f"),{'f':fid})
        db.execute(text('DELETE FROM fact_sources WHERE fact_id=:f AND turn_id=:t'),{'f':fid,'t':extra.id})
    with factory() as db:assert len(db.scalars(select(FactSource)).all())==1
    with factory.begin() as db:db.execute(text('TRUNCATE fact_sources'))
    with factory() as db:assert db.scalar(text('SELECT count(*) FROM fact_sources'))==0


@pytest.mark.parametrize('attack',['update','truncate'])
def test_repeatable_read_old_snapshot_cannot_hide_new_audit(api,attack):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    with factory() as stale:
        stale.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        assert stale.scalar(text('SELECT count(*) FROM fact_change_sources'))==0
        with factory.begin() as db:correction(db,b,fid)
        before=stored(factory)
        with pytest.raises(DBAPIError) as denied:
            if attack=='update':stale.execute(text("UPDATE fact_sources SET citations='[]'::jsonb WHERE fact_id=:f"),{'f':fid})
            else:stale.execute(text('TRUNCATE fact_sources'))
            stale.commit()
        assert denied.value.orig.sqlstate==('40001' if attack=='update' else '23514')
        stale.rollback()
    assert stored(factory)==before


def test_repeatable_read_auditor_cannot_ignore_prior_legacy_source_commit(api):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    with factory() as stale:
        stale.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        assert stale.scalar(text('SELECT count(*) FROM fact_change_sources'))==0
        assert stale.get(ExperienceFact,fid).version==1
        with factory.begin() as db:
            db.execute(text("UPDATE fact_sources SET citations='[{}]'::jsonb WHERE fact_id=:f"),{'f':fid})
        before=stored(factory)
        with pytest.raises(DBAPIError) as denied:
            correction(stale,b,fid)
            stale.commit()
        assert denied.value.orig.sqlstate=='40001'
        stale.rollback()
    assert stored(factory)==before


def test_repeatable_read_auditor_cannot_adopt_origin_removed_by_legacy_truncate(api):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    with factory() as stale:
        stale.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        assert stale.scalar(text('SELECT count(*) FROM fact_change_sources'))==0
        assert stale.get(ExperienceFact,fid).version==1
        # No prior access to fact_sources in stale: PostgreSQL TRUNCATE is not
        # MVCC-safe, so the later read must not be trusted as a valid origin.
        with factory.begin() as db:db.execute(text('TRUNCATE fact_sources'))
        before=stored(factory)
        with pytest.raises(IntegrityError,match='maintenance_original_invalid'):
            correction(stale,b,fid)
            stale.commit()
        stale.rollback()
    assert stored(factory)==before


def test_legacy_source_write_fence_preserves_logical_session_and_fact_versions(api):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    with factory() as db:
        before=db.execute(text('SELECT context_revision,updated_at,xmin::text FROM experience_sessions WHERE id=:s'),{'s':b.sid}).one()
    with factory.begin() as db:
        db.execute(text("UPDATE fact_sources SET citations='[]'::jsonb WHERE fact_id=:f"),{'f':fid})
    with factory() as db:
        after=db.execute(text('SELECT context_revision,updated_at,xmin::text FROM experience_sessions WHERE id=:s'),{'s':b.sid}).one()
        assert after[:2]==before[:2] and after[2]!=before[2]
        assert db.get(ExperienceFact,fid).version==1
        assert db.scalar(text('SELECT count(*) FROM fact_changes'))==1


@pytest.mark.parametrize('attack',['update','delete','insert'])
def test_origin_write_after_audit_in_initial_transaction_rolls_back_everything(api,attack):
    _,factory=api;b=initial(factory);before=stored(factory)
    with pytest.raises(IntegrityError,match='maintenance_original_immutable'),factory.begin() as db:
        r=append_operation(db,b)
        if attack=='update':db.execute(text("UPDATE fact_sources SET citations='[]'::jsonb WHERE fact_id=:f"),{'f':r.fid})
        elif attack=='delete':db.execute(text('DELETE FROM fact_sources WHERE fact_id=:f'),{'f':r.fid})
        else:db.add(FactSource(fact_id=r.fid,session_id=b.sid,turn_id=b.tid))
    assert stored(factory)==before


@pytest.mark.parametrize('first',['audit','source'])
def test_first_audit_and_raw_legacy_source_write_are_serialized(api,first):
    _,factory=api;b=initial(factory);fid=legacy(factory,b)
    ready=Event();entered=Event();finished=Event()
    def leader():
        with factory.begin() as db:
            if first=='audit':correction(db,b,fid)
            else:db.execute(text("UPDATE fact_sources SET citations='[{}]'::jsonb WHERE fact_id=:f"),{'f':fid})
            ready.set();assert entered.wait(5)
            if first=='audit':assert finished.wait(5)  # source NOWAIT must finish
    def follower():
        assert ready.wait(5);entered.set()
        try:
            if first=='audit':
                with pytest.raises(DBAPIError) as denied,factory.begin() as db:
                    db.execute(text("UPDATE fact_sources SET citations='[{}]'::jsonb WHERE fact_id=:f"),{'f':fid})
                assert denied.value.orig.sqlstate=='55P03'
            else:
                with pytest.raises(IntegrityError,match='maintenance_original_invalid'),factory.begin() as db:
                    correction(db,b,fid)
        finally:finished.set()
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(leader),pool.submit(follower)]
        for future in futures:future.result(15)
    with factory() as db:
        assert db.scalar(text('SELECT count(*) FROM conversation_operations'))==int(first=='audit')
        assert db.get(ExperienceFact,fid).version==(2 if first=='audit' else 1)
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==(2 if first=='audit' else 1)


def test_delete_holding_session_lock_rejects_raw_origin_write_without_deadlock(api):
    _,factory=api;b=initial(factory)
    fid=audit(factory,b,'append');ready=Event();finished=Event()
    def delete():
        with factory.begin() as db:
            facts.authorize(db,b.sid,b.token,write=True)
            ready.set();assert finished.wait(5)
            db.execute(text('DELETE FROM experience_sessions WHERE id=:s'),{'s':b.sid})
    def write():
        assert ready.wait(5)
        try:
            with pytest.raises(DBAPIError) as denied,factory.begin() as db:
                db.execute(text("UPDATE fact_sources SET citations='[]'::jsonb WHERE fact_id=:f"),{'f':fid})
            assert denied.value.orig.sqlstate=='55P03'
        finally:finished.set()
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(delete),pool.submit(write)]
        for future in futures:future.result(15)
    with factory() as db:
        for name in ('fact_sources','fact_change_sources','fact_changes','experience_facts','conversation_turns'):
            assert db.scalar(text(f'SELECT count(*) FROM {name}'))==0
        assert db.scalar(text("SELECT count(*) FROM conversation_operations WHERE state='deleted'"))==1
