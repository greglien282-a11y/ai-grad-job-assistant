"""Owner provisions fixtures only, never services requests. No production DSN."""

import hashlib
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

from psycopg import sql
import pytest
from research.g3_choice_protocol.conftest import model  # unchanged random LOGIN fixture
from research.g4_trusted_boundary.runtime import Issuer, validator_hash


@pytest.fixture(params=["broker", "credential"])
def boundary(model, request):
    m = model
    private = "g4_gate_" + uuid4().hex
    secret, vh = secrets.token_bytes(32), validator_hash()
    admin = m.admin
    try:
        admin.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                sql.Identifier(private), sql.Identifier(m.roles["owner"])
            )
        )
        admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(m.roles["owner"])))
        source = Path(__file__).with_name("schema.sql").read_text(encoding="utf8")
        admin.execute(
            source.replace("__G__", m.schema)
            .replace("__S__", private)
            .replace("__WRITER__", m.roles["writer"])
        )
        admin.execute(
            sql.SQL("INSERT INTO {} VALUES(%s,%s,%s)").format(
                sql.Identifier(private, "policy")
            ),
            (request.param, secret, vh),
        )
        admin.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
                sql.Identifier(private)
            )
        )
        for kind in ("writer", "reader"):
            admin.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(private), sql.Identifier(m.roles[kind])
                )
            )
        admin.execute(
            sql.SQL(
                "GRANT INSERT(operation_id,mode,seal,nonce,expires_epoch,validator_hash,mac) ON {} TO {}"
            ).format(
                sql.Identifier(private, "permits"), sql.Identifier(m.roles["writer"])
            )
        )
        admin.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {}(uuid) TO {}").format(
                sql.Identifier(private, "seal"), sql.Identifier(m.roles["writer"])
            )
        )
        admin.execute("RESET ROLE")
        functions = admin.execute(
            "SELECT proname,pg_get_functiondef(oid) AS definition FROM pg_proc WHERE pronamespace=%s::regnamespace",
            (private,),
        ).fetchall()
        gate = SimpleNamespace(
            schema=private,
            graph_schema=m.schema,
            mode=request.param,
            validator_hash=vh,
            functions={
                f["proname"]: hashlib.sha256(f["definition"].encode()).hexdigest()
                for f in functions
            },
        )
        base_snapshot = m.snapshot

        def snapshot():
            result = base_snapshot()
            result["g4_permits"] = admin.execute(
                sql.SQL(
                    "SELECT to_jsonb(p)::text AS row FROM {} p ORDER BY operation_id"
                ).format(sql.Identifier(private, "permits"))
            ).fetchall()
            return result

        m.snapshot = snapshot
        yield SimpleNamespace(
            model=m, gate=gate, issuer=Issuer(secret, vh), secret=secret
        )
    finally:
        admin.execute("RESET ROLE")
        admin.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(private))
        )
