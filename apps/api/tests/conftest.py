"""Shared PostgreSQL fixture; tests only create/drop their own random schema."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


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
