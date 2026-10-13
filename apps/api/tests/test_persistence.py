"""Real PostgreSQL only. Each test owns a randomly named, disposable schema."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.facts import add_fact, add_turn, authorize, change_fact, create_experience, eligible_facts, end_session
from app.models import Base, ConversationTurn, ExperienceFact, ExperienceProject, ExperienceSession, FactChange, FactEvidence, FactSource, FactStatus


@pytest.fixture
def migrated_connection():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        if os.getenv("CI"):
            pytest.fail("CI requires TEST_DATABASE_URL; integration tests must not skip")
        pytest.skip("TEST_DATABASE_URL not set; PostgreSQL integration test")
    engine = create_engine(url, hide_parameters=True)
    if engine.dialect.name != "postgresql":
        pytest.fail("PostgreSQL required")
    schema = "test_" + uuid4().hex
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}"'))
        connection.commit()
        cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        cfg.attributes["connection"] = connection
        try:
            command.upgrade(cfg, "head")
            connection.commit()
            yield connection, cfg
        finally:
            connection.rollback()
            connection.execute(text("SET search_path TO public"))
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.commit()
    engine.dispose()


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


def test_commit_reload_edit_and_history(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        project, turn, token, fact = seed(db)
        change_fact(db, fact.id, token, status=FactStatus.USER_CONFIRMED)
        assert eligible_facts(db, project.id, token) == [fact]
        ids = project.id, turn.id, fact.id
    with Session(connection) as db, db.begin():
        project = db.get(ExperienceProject, ids[0])
        fact = db.get(ExperienceFact, ids[2])
        assert fact.status == FactStatus.USER_CONFIRMED
        change_fact(db, fact.id, token, statement="Built the tracker UI")
        assert fact.status == FactStatus.PENDING
        assert eligible_facts(db, project.id, token) == []
        assert project.raw_input == db.get(ConversationTurn, ids[1]).content
        changes = db.scalars(select(FactChange).where(FactChange.fact_id == fact.id).order_by(FactChange.created_at)).all()
        assert len(changes) == 3
        assert changes[-1].before["status"] == "user_confirmed"
        assert changes[-1].after["source_turn_ids"] == [str(ids[1])]
        assert changes[-1].created_at.tzinfo is not None


def test_evidence_retained_after_edit(migrated_connection):
    connection, _ = migrated_connection
    with Session(connection) as db, db.begin():
        _, _, token, fact = seed(db)
        change_fact(db, fact.id, token, status=FactStatus.USER_CONFIRMED)
        with pytest.raises(ValueError):
            change_fact(db, fact.id, token, status=FactStatus.EVIDENCE_SUPPORTED)
        change_fact(db, fact.id, token, status=FactStatus.EVIDENCE_SUPPORTED,
                    material_reference="synthetic-report:section-2", basis="User compared statement with the synthetic report.")
        evidence_id = fact.evidence_id
        change_fact(db, fact.id, token, statement="Built part of the tracker UI")
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
            change_fact(db, fact.id, token, status=FactStatus.EVIDENCE_SUPPORTED, material_reference="report", basis="basis")
        with pytest.raises(ValueError):
            change_fact(db, fact.id, token, statement="Changed", status=FactStatus.USER_CONFIRMED)
        change_fact(db, fact.id, token, status=FactStatus.REJECTED)
        assert eligible_facts(db, project.id, token) == []
        with pytest.raises(ValueError):
            change_fact(db, fact.id, token, status=FactStatus.USER_CONFIRMED)
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
            change_fact(db, fact.id, other_token, status=FactStatus.USER_CONFIRMED)
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
        change_fact(db, fact.id, token, status=FactStatus.USER_CONFIRMED)
        change_fact(db, fact.id, token, status=FactStatus.EVIDENCE_SUPPORTED, material_reference="synthetic-report", basis="human reviewed")
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
