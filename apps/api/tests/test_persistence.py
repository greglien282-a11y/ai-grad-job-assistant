"""Real PostgreSQL only. Each test owns a randomly named, disposable schema."""
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.facts import add_fact, add_turn, authorize, change_fact, create_experience, eligible_facts, end_session, snapshot
from app.models import Base, ConversationTurn, ExperienceFact, ExperienceProject, ExperienceSession, FactChange, FactEvidence, FactSource, FactStatus



def seed(db):
    project, turn, token = create_experience(db, "Synthetic: built a course task tracker.")
    fact = add_fact(db, project.id, token, "Built a task tracker", [turn.id])
    return project, turn, token, fact


def test_empty_database_migration_roundtrip(migrated_connection):
    connection, cfg = migrated_connection
    assert set(Base.metadata.tables).issubset(inspect(connection).get_table_names())
    command.check(cfg)
    command.downgrade(cfg, "base")
    assert not set(Base.metadata.tables).intersection(inspect(connection).get_table_names())
    command.upgrade(cfg, "head")


def test_version_migration_preserves_existing_confirmed_fact(migrated_connection):
    connection, cfg = migrated_connection
    command.downgrade(cfg, "0001_experience_library")
    sid, pid, fid = uuid4(), uuid4(), uuid4()
    connection.execute(text("INSERT INTO experience_sessions (id,access_token_hash,status,created_at,updated_at) VALUES (:sid,:hash,'active',now(),now())"), {"sid": sid, "hash": "0" * 64})
    connection.execute(text("INSERT INTO experience_projects (id,session_id,raw_input,created_at) VALUES (:pid,:sid,'Synthetic old input',now())"), {"pid": pid, "sid": sid})
    connection.execute(text("INSERT INTO experience_facts (id,project_id,session_id,statement,status,created_at,updated_at) VALUES (:fid,:pid,:sid,'Synthetic existing claim','user_confirmed',now(),now())"), {"fid": fid, "pid": pid, "sid": sid})
    connection.commit()
    command.upgrade(cfg, "head")
    row = connection.execute(text("SELECT version,statement,status FROM experience_facts WHERE id=:fid"), {"fid": fid}).one()
    assert tuple(row) == (1, "Synthetic existing claim", "user_confirmed")
    command.check(cfg)


def test_commit_reload_edit_and_history(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        project, turn, token, fact = seed(db)
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        assert eligible_facts(db, project.id, token) == [fact]
        ids = project.id, turn.id, fact.id
    with Session(connection) as db, db.begin():
        project = db.get(ExperienceProject, ids[0])
        fact = db.get(ExperienceFact, ids[2])
        assert fact.status == FactStatus.USER_CONFIRMED
        change_fact(db, fact.id, token, expected_version=fact.version, statement="Built the tracker UI")
        assert fact.status == FactStatus.PENDING
        assert eligible_facts(db, project.id, token) == []
        assert project.raw_input == db.get(ConversationTurn, ids[1]).content
        changes = db.scalars(select(FactChange).where(FactChange.fact_id == fact.id).order_by(FactChange.created_at)).all()
        assert len(changes) == 3
        assert changes[-1].before["status"] == "user_confirmed"
        assert changes[-1].after["source_turn_ids"] == []
        assert changes[-1].after["original_source_turn_ids"] == [str(ids[1])]
        assert changes[-1].after["source_change_id"] == str(changes[-1].id)
        assert changes[-1].created_at.tzinfo is not None


def test_edited_fact_provenance_survives_confirmation_and_new_connection(migrated_connection):
    connection, _ = migrated_connection
    schema = connection.scalar(text("SELECT current_schema()"))
    connection.commit()
    with Session(connection) as db, db.begin():
        project, turn, token = create_experience(db, "Synthetic A: worked on image classification.")
        fact = add_fact(db, project.id, token, "Worked on image classification", [turn.id])
        original = snapshot(db, fact)
        assert original["source_kind"] == "conversation_turns"
        assert original["source_turn_ids"] == [str(turn.id)]
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        change_fact(db, fact.id, token, expected_version=fact.version, statement="Synthetic B: handled deployment")
        edited = snapshot(db, fact)
        assert edited["status"] == "pending"
        assert edited["source_kind"] == "user_edit"
        assert edited["source_turn_ids"] == []
        edit_id = edited["source_change_id"]
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        project_id, fact_id, turn_id = project.id, fact.id, turn.id

    # Force a separate physical connection, with its own explicit search_path.
    reader = create_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
    try:
        with reader.connect() as other:
            assert other.connection.driver_connection is not connection.connection.driver_connection
            other.execute(text(f'SET search_path TO "{schema}"'))
            other.commit()
            with Session(other) as db, db.begin():
                fact = eligible_facts(db, project_id, token)[0]
                current = snapshot(db, fact)
                assert fact.id == fact_id and fact.statement == "Synthetic B: handled deployment"
                assert current["status"] == "user_confirmed"
                assert current["source_kind"] == "user_edit"
                assert current["source_change_id"] == edit_id
                assert current["source_turn_ids"] == []
                assert current["original_source_turn_ids"] == [str(turn_id)]
                assert db.get(ConversationTurn, turn_id).content == "Synthetic A: worked on image classification."
                assert db.get(ExperienceProject, project_id).raw_input == "Synthetic A: worked on image classification."
                assert db.scalar(select(FactSource.turn_id).where(FactSource.fact_id == fact_id)) == turn_id
                history = db.scalars(select(FactChange).where(FactChange.fact_id == fact_id).order_by(FactChange.created_at, FactChange.id)).all()
                assert [item.action for item in history] == ["created", "status_changed", "edited", "status_changed"]
                assert history[0].after["statement"] == "Worked on image classification"
                assert history[2].actor == "user" and str(history[2].id) == edit_id
                assert history[2].before == history[1].after
                assert history[2].after["statement"] == fact.statement
                assert history[3].before == history[2].after
                assert history[3].after == current
                assert all(item.created_at.tzinfo for item in history)
    finally:
        reader.dispose()


def test_repeated_edits_replace_current_source_without_losing_history(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        _, turn, token, fact = seed(db)
        change_fact(db, fact.id, token, expected_version=fact.version, statement="Synthetic B: handled deployment")
        first_edit = snapshot(db, fact)
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        change_fact(db, fact.id, token, expected_version=fact.version, statement="Built a task tracker")
        second_edit = snapshot(db, fact)
        assert second_edit["source_change_id"] != first_edit["source_change_id"]
        assert second_edit["source_kind"] == "user_edit"
        assert second_edit["source_turn_ids"] == []
        assert second_edit["original_source_turn_ids"] == [str(turn.id)]
        edits = db.scalars(select(FactChange).where(FactChange.fact_id == fact.id, FactChange.action == "edited").order_by(FactChange.created_at, FactChange.id)).all()
        assert len(edits) == 2
        assert edits[1].before["source_change_id"] == str(edits[0].id)
        assert edits[0].after == first_edit


def test_evidence_retained_after_edit(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        _, _, token, fact = seed(db)
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        with pytest.raises(ValueError):
            change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.EVIDENCE_SUPPORTED)
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.EVIDENCE_SUPPORTED,
                    material_reference="synthetic-report:section-2", basis="User compared statement with the synthetic report.")
        evidence_id = fact.evidence_id
        change_fact(db, fact.id, token, expected_version=fact.version, statement="Built part of the tracker UI")
        assert fact.evidence_id is None and fact.status == FactStatus.PENDING
        assert db.get(FactEvidence, evidence_id).reviewer == "user"
        edit = db.scalar(select(FactChange).where(FactChange.action == "edited"))
        assert edit.before["evidence_id"] == str(evidence_id)


def test_invalid_transitions_rejection_and_closed_session(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        project, _, token, fact = seed(db)
        assert eligible_facts(db, project.id, token) == []
        with pytest.raises(ValueError):
            change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.EVIDENCE_SUPPORTED, material_reference="report", basis="basis")
        with pytest.raises(ValueError):
            change_fact(db, fact.id, token, expected_version=fact.version, statement="Changed", status=FactStatus.USER_CONFIRMED)
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.REJECTED)
        assert eligible_facts(db, project.id, token) == []
        with pytest.raises(ValueError):
            change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        end_session(db, project.session_id, token)
        with pytest.raises(ValueError):
            add_turn(db, project.session_id, token, "Synthetic follow-up")
        assert authorize(db, project.session_id, token).status == "ended"


def test_access_and_source_scope(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        project, _, token, fact = seed(db)
        other, other_turn, other_token = create_experience(db, "Synthetic second session")
        assert token != other_token
        assert db.get(ExperienceSession, project.session_id).access_token_hash != token
        with pytest.raises(PermissionError):
            change_fact(db, fact.id, other_token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        with pytest.raises(PermissionError):
            authorize(db, other.session_id, token)
        with pytest.raises(ValueError):
            add_fact(db, project.id, token, "Other claim", [other_turn.id])
        assistant = ConversationTurn(session_id=project.session_id, role="assistant", content="Synthetic suggestion")
        db.add(assistant)
        db.flush()
        with pytest.raises(ValueError):
            add_fact(db, project.id, token, "Model claim", [assistant.id])
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(FactSource(fact_id=fact.id, turn_id=other_turn.id, session_id=project.session_id))
            db.flush()


def test_db_constraints_and_session_cascade(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        project, _, token, fact = seed(db)
        with pytest.raises(IntegrityError), db.begin_nested():
            fact.status = "invalid"
            db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            fact.status = FactStatus.EVIDENCE_SUPPORTED
            db.flush()
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.USER_CONFIRMED)
        change_fact(db, fact.id, token, expected_version=fact.version, status=FactStatus.EVIDENCE_SUPPORTED, material_reference="synthetic-report", basis="human reviewed")
        db.execute(delete(ExperienceSession).where(ExperienceSession.id == project.session_id))
        db.expire_all()
        for model in (ExperienceProject, ConversationTurn, ExperienceFact, FactSource, FactEvidence, FactChange):
            assert db.scalar(select(model)) is None


def test_rollback_removes_partial_experience(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db:
        with pytest.raises(ValueError), db.begin():
            project, _, token, _ = seed(db)
            add_fact(db, project.id, token, " ", [])
        assert db.scalar(select(ExperienceSession)) is None
