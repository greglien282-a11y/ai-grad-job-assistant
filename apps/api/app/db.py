"""Lazy PostgreSQL configuration: the health endpoint does not require a DB."""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL connection URL")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Only PostgreSQL is supported")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def build_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True, hide_parameters=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
