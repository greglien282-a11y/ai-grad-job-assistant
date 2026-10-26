from types import SimpleNamespace
import secrets
from psycopg import sql
import pytest
from research.g3_choice_protocol.conftest import model
from research.g4_trusted_boundary.conftest import boundary
from research.g4_source_binding.binding import Ingress, BoundIssuer, approved_hash


@pytest.fixture
def bound(boundary):
    x = boundary
    assert x.gate.mode == "credential"
    version = approved_hash()
    key = secrets.token_bytes(32)
    # Provision a DIFFERENT approved contract before any request. No existing
    # graph/receipt/history rewritten; old issuer version cannot serve this key.
    x.model.admin.execute(
        sql.SQL("UPDATE {} SET validator_hash=%s").format(
            sql.Identifier(x.gate.schema, "policy")
        ),
        (version,),
    )
    x.gate.validator_hash = version
    return SimpleNamespace(
        x=x,
        ingress=Ingress(key),
        issuer=BoundIssuer(x.secret, key, version),
        ingress_key=key,
    )
