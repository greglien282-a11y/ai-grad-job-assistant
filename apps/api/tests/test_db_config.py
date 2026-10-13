import pytest

from app.db import database_url
from app.facts import required_text, token_hash


def test_database_is_explicit_and_postgresql_only(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        database_url()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///not-supported.db")
    with pytest.raises(ValueError):
        database_url()
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic:password@localhost/test")
    assert database_url().startswith("postgresql+psycopg://")


def test_text_validation_preserves_original():
    assert required_text("  Synthetic course project  ") == "  Synthetic course project  "
    for value in (" ", "a" * 10001):
        with pytest.raises(ValueError):
            required_text(value)


def test_credentials_are_hashed():
    assert len(token_hash("synthetic-token")) == 64
    assert token_hash("synthetic-token") != token_hash("another-token")
