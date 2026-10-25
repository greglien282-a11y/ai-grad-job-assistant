"""Random schema/temporary roles ONLY. Owner is never a request identity."""

import os
from pathlib import Path
import re
import secrets
import sys
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
from research.g3_choice_protocol.runtime import TABLES, digest


@pytest.fixture
def model():
    url = os.getenv("G3_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "G3_TEST_DATABASE_URL must explicitly name a synthetic loopback test database"
        )
    config = conninfo_to_dict(url)
    if config.get("host") not in ("127.0.0.1", "localhost") or config.get(
        "dbname"
    ) not in ("pathwise_test", "pathwise_g3"):
        pytest.fail("Dedicated loopback synthetic database required")
    schema = "g3_ref_" + uuid4().hex
    roles = {
        k: "g3_" + k + "_" + uuid4().hex[:20]
        for k in ("owner", "writer", "reader", "eraser", "mutator")
    }
    passwords = {k: secrets.token_urlsafe(32) for k in roles if k != "owner"}
    admin = psycopg.connect(url, autocommit=True, row_factory=dict_row)
    try:
        for kind, name in roles.items():
            admin.execute(
                sql.SQL(
                    "CREATE ROLE {} {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"
                ).format(
                    sql.Identifier(name),
                    (
                        sql.SQL("NOLOGIN")
                        if kind == "owner"
                        else sql.SQL("LOGIN PASSWORD {}").format(
                            sql.Literal(passwords[kind])
                        )
                    ),
                )
            )
        admin.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                sql.Identifier(schema), sql.Identifier(roles["owner"])
            )
        )
        admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(roles["owner"])))
        source = Path(__file__).with_name("schema.sql").read_text(encoding="utf8")
        assert re.fullmatch("g3_ref_[a-f0-9]{32}", schema)
        admin.execute(
            source.replace("__S__", '"' + schema + '"').replace(
                "__OWNER_NAME__", roles["owner"]
            )
        )
        for table in TABLES[1:]:
            q = sql.Identifier(schema, table)
            admin.execute(
                sql.SQL(
                    "CREATE CONSTRAINT TRIGGER ref_consistency AFTER INSERT OR UPDATE OR DELETE ON {} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {}()"
                ).format(q, sql.Identifier(schema, "ref_consistent"))
            )
            admin.execute(
                sql.SQL(
                    "CREATE TRIGGER ref_immutable BEFORE UPDATE OR DELETE ON {} FOR EACH ROW EXECUTE FUNCTION {}()"
                ).format(q, sql.Identifier(schema, "ref_immutable"))
            )
            admin.execute(
                sql.SQL(
                    "CREATE TRIGGER ref_no_truncate BEFORE TRUNCATE ON {} FOR EACH STATEMENT EXECUTE FUNCTION {}()"
                ).format(q, sql.Identifier(schema, "ref_immutable"))
            )
        admin.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
                sql.Identifier(schema)
            )
        )
        admin.execute(
            sql.SQL("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC").format(
                sql.Identifier(schema)
            )
        )
        for kind in passwords:
            admin.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(roles[kind])
                )
            )
        for kind in ("writer", "reader", "mutator"):
            role = sql.Identifier(roles[kind])
            admin.execute(
                sql.SQL(
                    "GRANT SELECT(id,project_id,subject_id,revision,new_command_review_required) ON {} TO {}"
                ).format(sql.Identifier(schema, "ref_sessions"), role)
            )
            for table in TABLES[1:]:
                admin.execute(
                    sql.SQL("GRANT SELECT ON {} TO {}").format(
                        sql.Identifier(schema, table), role
                    )
                )
        for table in TABLES[1:]:
            if table == "ref_auth_contexts":
                continue
            columns = admin.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                (schema, table),
            ).fetchall()
            allowed = [
                sql.Identifier(c["column_name"])
                for c in columns
                if c["column_name"] not in ("created_xid", "recorded_at", "expires_at")
            ]
            admin.execute(
                sql.SQL("GRANT INSERT({}) ON {} TO {}").format(
                    sql.SQL(",").join(allowed),
                    sql.Identifier(schema, table),
                    sql.Identifier(roles["writer"]),
                )
            )
        admin.execute(
            sql.SQL("GRANT UPDATE(revision) ON {} TO {}").format(
                sql.Identifier(schema, "ref_sessions"), sql.Identifier(roles["writer"])
            )
        )
        for table in TABLES[1:]:
            admin.execute(
                sql.SQL("GRANT UPDATE,DELETE,TRUNCATE ON {} TO {}").format(
                    sql.Identifier(schema, table), sql.Identifier(roles["mutator"])
                )
            )
        for kind in ("writer", "reader"):
            for fn in ("ref_authorize(uuid,text)", "ref_validate(uuid)"):
                admin.execute(
                    sql.SQL(
                        "GRANT EXECUTE ON FUNCTION "
                        + sql.Identifier(schema).as_string(admin)
                        + "."
                        + fn
                        + " TO {}"
                    ).format(sql.Identifier(roles[kind]))
                )
        for kind, fn in (
            ("writer", "ref_record_auth(uuid,uuid,text)"),
            ("eraser", "ref_erase(uuid,text)"),
        ):
            admin.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION "
                    + sql.Identifier(schema).as_string(admin)
                    + "."
                    + fn
                    + " TO {}"
                ).format(sql.Identifier(roles[kind]))
            )
        admin.execute("RESET ROLE")
        admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))

        def dsn(kind):
            return make_conninfo(
                url,
                user=roles[kind],
                password=passwords[kind],
                options="-csearch_path=" + schema,
            )

        def connect(kind="writer", readonly=False):
            conn = psycopg.connect(dsn(kind), row_factory=dict_row)
            if readonly:
                conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return conn

        def seed():
            sid, pid, subject = uuid4(), uuid4(), uuid4()
            token = secrets.token_urlsafe(32)
            admin.execute(
                "INSERT INTO ref_sessions(id,project_id,subject_id,credential_hash) VALUES(%s,%s,%s,%s)",
                (sid, pid, subject, digest(token)),
            )
            return SimpleNamespace(sid=sid, pid=pid, subject=subject, token=token)

        def snapshot():
            return {
                t: admin.execute(
                    sql.SQL(
                        "SELECT to_jsonb(t)::text AS row FROM {} t ORDER BY to_jsonb(t)::text"
                    ).format(sql.Identifier(schema, t))
                ).fetchall()
                for t in TABLES
            }

        yield SimpleNamespace(
            admin=admin,
            roles=roles,
            schema=schema,
            connect=connect,
            seed=seed,
            snapshot=snapshot,
            dsn=dsn,
        )
    finally:
        admin.execute("RESET ROLE")
        admin.execute("SET search_path TO public")
        admin.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )
        for name in reversed(list(roles.values())):
            exists = admin.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)
            ).fetchone()
            if exists:
                admin.execute(
                    sql.SQL("DROP OWNED BY {} RESTRICT").format(sql.Identifier(name))
                )
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))
        admin.close()
