"""Executable disposable-DB reference adapter. NOT a Pathwise writer/CO3 API.

No factory/env/network/Provider wiring. Caller supplies a connection to its
random research schema; bearer tokens and subjects are synthetic test fixtures.
"""

import hashlib
import hmac
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.typed_semantic_spike import validate_candidate

TABLES = (
    "ref_sessions",
    "ref_operations",
    "ref_auth_contexts",
    "ref_turns",
    "ref_facts",
    "ref_changes",
    "ref_sources",
    "ref_fcs",
    "ref_choices",
)
CONTRACT = "g3-choice-graph-ref-v1"


class Refused(Exception):
    """Fixed diagnostic codes only; never include request/SQL/credential data."""


def digest(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def admit(db, *, mode="writer"):
    # TEMP may have been populated before READ ONLY begins. Reject contaminated
    # connections before any unqualified reference-table query; no DB-wide ACL
    # change is needed. All admission metadata is pg_catalog-qualified as well.
    if db.execute(
        "SELECT 1 FROM pg_catalog.pg_class WHERE relnamespace=pg_catalog.pg_my_temp_schema() UNION ALL SELECT 1 FROM pg_catalog.pg_proc WHERE pronamespace=pg_catalog.pg_my_temp_schema() LIMIT 1"
    ).fetchone():
        raise Refused("reference_runtime_unapproved")
    meta = db.execute(
        "SELECT pg_catalog.current_schema() AS schema,current_user AS role,session_user AS login"
    ).fetchone()
    role = db.execute(
        "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=current_user"
    ).fetchone()
    if not meta["schema"]:
        raise Refused("reference_schema_unavailable")
    path = db.execute("SELECT pg_catalog.current_schemas(false) AS path").fetchone()[
        "path"
    ]
    if path != [meta["schema"]]:
        raise Refused("reference_runtime_unapproved")
    if (
        not meta["schema"].startswith("g3_ref_")
        or meta["role"] != meta["login"]
        or not role["rolcanlogin"]
        or any(v for k, v in role.items() if k != "rolcanlogin")
    ):
        raise Refused("reference_runtime_unapproved")
    if db.execute(
        "SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user)"
    ).fetchone():
        raise Refused("reference_runtime_unapproved")
    names = db.execute(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=pg_catalog.current_schema()"
    ).fetchall()
    if {r["tablename"] for r in names} != set(TABLES):
        raise Refused("reference_schema_unavailable")
    if db.execute(
        "SELECT 1 FROM pg_catalog.pg_class WHERE relnamespace=pg_catalog.current_schema()::regnamespace AND relowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user)"
    ).fetchone():
        raise Refused("reference_runtime_unapproved")
    if db.execute(
        "SELECT pg_catalog.has_schema_privilege(pg_catalog.current_schema(),'CREATE') AS bad"
    ).fetchone()["bad"]:
        raise Refused("reference_acl_unapproved")
    columns = db.execute("""SELECT c.relname,a.attname,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'SELECT') AS sel,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'INSERT') AS ins,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'UPDATE') AS upd,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'REFERENCES') AS refs
      FROM pg_catalog.pg_class c JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
      WHERE c.relnamespace=pg_catalog.current_schema()::regnamespace AND c.relkind='r'
      AND a.attnum>0 AND NOT a.attisdropped""").fetchall()
    for c in columns:
        session = c["relname"] == "ref_sessions"
        expected = (
            not session or c["attname"] != "credential_hash",
            mode == "writer"
            and not session
            and c["relname"] != "ref_auth_contexts"
            and c["attname"] not in ("created_xid", "recorded_at", "expires_at"),
            mode == "writer" and session and c["attname"] == "revision",
            False,
        )
        if tuple(c[k] for k in ("sel", "ins", "upd", "refs")) != expected:
            raise Refused("reference_acl_unapproved")
    if db.execute(
        """SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname=pg_catalog.current_schema()
      AND (pg_catalog.has_table_privilege(pg_catalog.quote_ident(schemaname)||'.'||pg_catalog.quote_ident(tablename),'DELETE')
      OR pg_catalog.has_table_privilege(pg_catalog.quote_ident(schemaname)||'.'||pg_catalog.quote_ident(tablename),'TRUNCATE')
      OR pg_catalog.has_table_privilege(pg_catalog.quote_ident(schemaname)||'.'||pg_catalog.quote_ident(tablename),'TRIGGER'))"""
    ).fetchone():
        raise Refused("reference_acl_unapproved")
    functions = db.execute("""SELECT p.proname,p.prosecdef,p.proconfig,
      pg_catalog.has_function_privilege(p.oid,'EXECUTE') AS executable,r.rolcanlogin,r.rolsuper,
      EXISTS(SELECT 1 FROM pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) x
      WHERE x.grantee=0 AND x.privilege_type='EXECUTE') AS public_exec
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
      WHERE p.pronamespace=pg_catalog.current_schema()::regnamespace""").fetchall()
    expected_functions = {
        "ref_authorize",
        "ref_record_auth",
        "ref_validate",
        "ref_consistent",
        "ref_revision",
        "ref_erase",
        "ref_immutable",
        "ref_lock_operation",
    }
    executable = {"ref_authorize", "ref_validate"} | (
        {"ref_record_auth", "ref_lock_operation"} if mode == "writer" else set()
    )
    if {f["proname"] for f in functions} != expected_functions or len(functions) != 8:
        raise Refused("reference_schema_unavailable")
    for f in functions:
        if (
            f["public_exec"]
            or f["rolcanlogin"]
            or f["rolsuper"]
            or f["proconfig"] != ["search_path=pg_catalog"]
            or f["prosecdef"] != (f["proname"] != "ref_immutable")
            or f["executable"] != (f["proname"] in executable)
        ):
            raise Refused("reference_function_unapproved")
    triggers = db.execute(
        """SELECT t.tgname,t.tgenabled,t.tgdeferrable,t.tginitdeferred,
      c.relname,p.proname FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
      JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
      WHERE c.relnamespace=pg_catalog.current_schema()::regnamespace AND NOT t.tgisinternal"""
    ).fetchall()
    expected_triggers = {
        ("ref_sessions", "ref_revision_guard", "ref_revision", True, True)
    }
    for table in TABLES[1:]:
        expected_triggers |= {
            (table, "ref_consistency", "ref_consistent", True, True),
            (table, "ref_immutable", "ref_immutable", False, False),
            (table, "ref_no_truncate", "ref_immutable", False, False),
        }
    if (
        any(t["tgenabled"] != "O" for t in triggers)
        or {
            (
                t["relname"],
                t["tgname"],
                t["proname"],
                t["tgdeferrable"],
                t["tginitdeferred"],
            )
            for t in triggers
        }
        != expected_triggers
    ):
        raise Refused("reference_schema_unavailable")


def command(
    sid,
    pid,
    texts,
    *,
    scheme="A",
    revision=1,
    kind="personal_action",
    stage="completed",
):
    raw = "\r\n".join(texts)
    cursor = 0
    items = []
    for quote in texts:
        start = raw.index(quote, cursor)
        cursor = start + len(quote)
        items.append(
            dict(
                quote=quote,
                start=start,
                end=cursor,
                fact_kind=kind,
                progress_stage=stage,
                classification_contract="explicit-typed-v1",
                selection_id=str(uuid4()),
            )
        )
    return dict(
        reference_contract=CONTRACT,
        contract_version=3,
        scheme=scheme,
        session_id=str(sid),
        project_id=str(pid),
        base_revision=revision,
        content=raw,
        items=items,
    )


def authorized(db, sid, token):
    if not db.execute(
        "SELECT ref_authorize(%s,%s) AS allowed", (sid, token)
    ).fetchone()["allowed"]:
        raise Refused("resource_unavailable")


def request_digest(db, body):
    return db.execute(
        "SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex') AS digest",
        (Jsonb(body),),
    ).fetchone()["digest"]


def _view(db, row, version, scheme):
    if row["state"] == "deleted":
        raise Refused("deleted")
    if db.execute(
        "SELECT clock_timestamp()>%s AS expired", (row["expires_at"],)
    ).fetchone()["expired"]:
        raise Refused("expired")
    if (
        type(version) is not int
        or row["contract_version"] != version
        or row["scheme"] != scheme
    ):
        raise Refused("contract_mismatch")
    db.execute("SELECT ref_validate(%s)", (row["id"],))
    choices = db.execute(
        "SELECT id,fact_id,change_id,effect_slot,source_kind FROM ref_choices WHERE operation_id=%s ORDER BY effect_slot",
        (row["id"],),
    ).fetchall()
    return dict(
        evidence_class="DISPOSABLE_PG_REFERENCE",
        status="reference_result",
        operation_id=str(row["id"]),
        contract_version=version,
        scheme=scheme,
        result_revision=row["result_revision"],
        effects=[
            {
                k: str(v) if k in ("id", "fact_id", "change_id") else v
                for k, v in c.items()
            }
            for c in choices
        ],
        truth_verified=False,
        persistence_authorized=False,
        semantic_independence="NOT_PROVEN",
    )


def recover(db, sid, token, key, *, version=3, scheme="A"):
    """Caller uses one REPEATABLE READ READ ONLY transaction. No new context."""
    admit(db, mode="reader")
    if db.execute(
        "SELECT current_setting('transaction_read_only') AS ro,current_setting('transaction_isolation') AS iso"
    ).fetchone() != dict(ro="on", iso="repeatable read"):
        raise Refused("readonly_snapshot_required")
    row = db.execute(
        "SELECT * FROM ref_operations WHERE key_digest=%s", (digest(key),)
    ).fetchone()
    if row and row["state"] == "deleted":
        if not hmac.compare_digest(row["owner_digest"], digest(token)) or row[
            "scope_digest"
        ] != digest(str(sid)):
            raise Refused("resource_unavailable")
        raise Refused("deleted")
    authorized(db, sid, token)
    if not row:
        raise Refused("not_found")
    if row["session_id"] != sid:
        raise Refused("resource_unavailable")
    return _view(db, row, version, scheme)


def apply(db, sid, token, key, body, *, fault=None):
    """One top-level transaction owned by caller; no HTTP or formal CO3 writes.

    fault mutates only a STAGED research graph in tests; never a history waiver.
    """
    admit(db)
    authorized(db, sid, token)  # no version/history detail before authentication
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (digest(key),))
    row = db.execute(
        "SELECT * FROM ref_lock_operation(%s) WHERE id IS NOT NULL", (digest(key),)
    ).fetchone()
    if row:
        if row["state"] == "deleted":
            if not hmac.compare_digest(row["owner_digest"], digest(token)) or row[
                "scope_digest"
            ] != digest(str(sid)):
                raise Refused("resource_unavailable")
            raise Refused("deleted")
        if row["session_id"] != sid:
            raise Refused("resource_unavailable")
        result = _view(db, row, body.get("contract_version"), body.get("scheme"))
        if row["request_digest"] != request_digest(db, body):
            raise Refused("payload_mismatch")
        return result, "replayed"
    if (
        set(body)
        != {
            "reference_contract",
            "contract_version",
            "scheme",
            "session_id",
            "project_id",
            "base_revision",
            "content",
            "items",
        }
        or body["reference_contract"] != CONTRACT
        or type(body["contract_version"]) is not int
        or body["contract_version"] != 3
        or body["scheme"] not in ("A", "B")
        or body["session_id"] != str(sid)
        or type(body["base_revision"]) is not int
    ):
        raise Refused("contract_unsupported")
    session = db.execute(
        "SELECT id,project_id,revision,new_command_review_required FROM ref_sessions WHERE id=%s FOR UPDATE",
        (sid,),
    ).fetchone()
    if session is None:
        raise Refused("resource_unavailable")
    if str(session["project_id"]) != body["project_id"]:
        raise Refused("resource_unavailable")
    if session["revision"] != body["base_revision"]:
        raise Refused("context_conflict")
    if session["new_command_review_required"]:
        raise Refused("requires_review")
    items = body["items"]
    if (
        type(items) is not list
        or not 1 <= len(items) <= 5
        or any(
            set(i)
            != {
                "quote",
                "start",
                "end",
                "fact_kind",
                "progress_stage",
                "classification_contract",
                "selection_id",
            }
            for i in items
        )
    ):
        raise Refused("items_invalid")
    language = validate_candidate(
        dict(
            validation_contract="typed-semantic-spike-v1",
            synthetic=True,
            raw_text=body["content"],
            items=[{k: v for k, v in i.items() if k != "selection_id"} for i in items],
        )
    )
    if language.status != "eligible_candidate":
        raise Refused("language_not_supported")
    if db.execute(
        "SELECT 1 FROM ref_turns WHERE session_id=%s AND purpose='body' AND content=%s",
        (sid, body["content"]),
    ).fetchone():
        raise Refused("exact_source_reuse")
    oid = uuid4()
    tid = uuid4()
    ctid = uuid4() if body["scheme"] == "B" else None
    db.execute(
        "INSERT INTO ref_operations(id,key_digest,scope_digest,owner_digest,contract_version,scheme,session_id,project_id,input_turn_id,choice_turn_id,item_count,base_revision,result_revision,request_digest) VALUES(%s,%s,%s,%s,3,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            oid,
            digest(key),
            digest(str(sid)),
            digest(token),
            body["scheme"],
            sid,
            session["project_id"],
            tid,
            ctid,
            len(items),
            session["revision"],
            session["revision"] + 1,
            request_digest(db, body),
        ),
    )
    aid = db.execute(
        "SELECT ref_record_auth(%s,%s,%s) AS id", (oid, sid, token)
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO ref_turns(id,operation_id,session_id,purpose,role,content) VALUES(%s,%s,%s,'body','user',%s)",
        (tid, oid, sid, body["content"]),
    )
    lines = [
        f"{n}:{i['fact_kind']}/{i['progress_stage']}" for n, i in enumerate(items, 1)
    ]
    if ctid:
        db.execute(
            "INSERT INTO ref_turns(id,operation_id,session_id,purpose,role,content) VALUES(%s,%s,%s,'choice','user',%s)",
            (ctid, oid, sid, "\n".join(lines)),
        )
    choice_cursor = 0
    for slot, item in enumerate(items, 1):
        fid, cid, bid = uuid4(), uuid4(), uuid4()
        labels = {
            k: item[k]
            for k in ("fact_kind", "progress_stage", "classification_contract")
        }
        db.execute(
            "INSERT INTO ref_facts(id,operation_id,session_id,project_id,version,statement,status,memory_state,origin,fact_kind,progress_stage,classification_contract) VALUES(%s,%s,%s,%s,1,%s,'pending','unspecified','manual',%s,%s,%s)",
            (fid, oid, sid, session["project_id"], item["quote"], *labels.values()),
        )
        snap = dict(
            version=1,
            statement=item["quote"],
            status="pending",
            origin="manual",
            memory_state="certain" if fault == "snapshot" else "unspecified",
            ai_run_id=None,
            evidence_id=None,
            **labels,
            original_turn_id=str(tid),
            start_cp=item["start"],
            end_cp=item["end"],
            quote=item["quote"],
            basis_id=str(bid),
        )
        db.execute(
            "INSERT INTO ref_changes(id,operation_id,session_id,fact_id,action,actor,after) VALUES(%s,%s,%s,%s,'created','system',%s)",
            (cid, oid, sid, fid, Jsonb(snap)),
        )
        db.execute(
            "INSERT INTO ref_sources(fact_id,operation_id,session_id,turn_id,start_cp,end_cp,quote) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (fid, oid, sid, tid, item["start"], item["end"], item["quote"]),
        )
        db.execute(
            "INSERT INTO ref_fcs(operation_id,effect_slot,session_id,fact_id,change_id,turn_id,start_cp,end_cp,quote,source_role) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'statement')",
            (oid, slot, sid, fid, cid, tid, item["start"], item["end"], item["quote"]),
        )
        if fault == "missing_choice" and slot == len(items):
            continue
        choice_quote = lines[slot - 1] if ctid else None
        choice_end = choice_cursor + len(choice_quote) if ctid else None
        db.execute(
            "INSERT INTO ref_choices(id,operation_id,effect_slot,session_id,project_id,fact_id,fact_version,change_id,basis_contract,source_kind,fact_kind,progress_stage,classification_contract,statement_turn_id,start_cp,end_cp,quote,selection_id,selection,auth_context_id,validator_contract,validation_result,choice_turn_id,choice_start_cp,choice_end_cp,choice_quote) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                bid,
                oid,
                slot,
                sid,
                uuid4() if fault == "project" else session["project_id"],
                fid,
                2 if fault == "version" else 1,
                cid,
                "g3-choice-turn-ref-v1" if ctid else "g3-choice-event-ref-v1",
                "conversation_turn" if ctid else "immutable_user_choice_event",
                *labels.values(),
                tid,
                item["start"] + 1 if fault == "quote_offset" else item["start"],
                item["end"],
                item["quote"],
                item["selection_id"],
                Jsonb(
                    {**labels, "progress_stage": "in_progress"}
                    if fault == "selection"
                    else labels
                ),
                uuid4() if fault == "auth_context" else aid,
                "typed-semantic-spike-v1",
                "finite_rule_match",
                tid if fault == "choice_turn" and ctid else ctid,
                choice_cursor if ctid else None,
                (
                    choice_end + 1
                    if fault == "choice_end" and slot == len(items)
                    else choice_end
                ),
                choice_quote,
            ),
        )
        if ctid:
            choice_cursor = choice_end + 1
    db.execute("UPDATE ref_sessions SET revision=revision+1 WHERE id=%s", (sid,))
    # The graph remains uncommitted here. COMMIT's deferred database checks,
    # not an application pre-check, must reject injected faults atomically.
    return (
        dict(
            status="uncommitted_reference_graph",
            operation_id=str(oid),
            truth_verified=False,
            persistence_authorized=False,
        ),
        "staged",
    )
