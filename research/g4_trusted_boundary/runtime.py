"""G4 disposable trusted services. No HTTP, factory, environment or Provider.

The Broker connection/key are service capabilities, never caller parameters in
an application. Python process isolation and key custody are explicit assumptions.
All persistent objects are the unchanged G3 research graph plus a private permit.
"""

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import time
from uuid import uuid4

from psycopg import sql
import app.typed_semantic_spike as semantic
from research.g3_choice_protocol.runtime import apply, recover, Refused


def validator_hash():
    return hashlib.sha256(Path(semantic.__file__).read_bytes()).hexdigest()


def message(seal, nonce, expires, version):
    graph_hash = hashlib.sha256(seal.encode("utf8")).hexdigest()
    return f"g4-proof-v1\n{version}\n{expires}\n{nonce}\n{graph_hash}".encode("utf8")


@dataclass(frozen=True)
class Proof:
    seal: str
    nonce: str
    expires: int
    validator_hash: str
    mac: bytes


class Issuer:
    """Independent service simulation; its synthetic key is NOT a client key.

    Issue only after independently parsing the sealed original and declarations.
    DB later compares the whole seal with actual rows, rather than trusting it.
    An issuer/key compromised enough to sign arbitrary bytes breaks model B.
    """

    def __init__(self, secret, approved_hash):
        self._secret = secret
        self.approved_hash = approved_hash

    def issue(self, seal):
        if validator_hash() != self.approved_hash:
            raise Refused("validator_version_unapproved")
        graph = json.loads(seal)
        op = graph["operation"]
        if (
            graph["domain"] != "g4-disposable-proof-v1"
            or type(op["contract_version"]) is not int
            or op["contract_version"] != 3
            or op["scheme"] != "A"
        ):
            raise Refused("reference_contract_unapproved")
        turns = graph["turns"]
        if len(turns) != 1 or turns[0]["role"] != "user":
            raise Refused("original_unavailable")
        decision = semantic.validate_candidate(
            dict(
                validation_contract="typed-semantic-spike-v1",
                synthetic=True,
                raw_text=turns[0]["content"],
                items=[
                    dict(
                        quote=i["quote"],
                        start=i["start_cp"],
                        end=i["end_cp"],
                        fact_kind=i["fact_kind"],
                        progress_stage=i["progress_stage"],
                        classification_contract=i["classification_contract"],
                    )
                    for i in graph["choices"]
                ],
            )
        )
        if decision.status != "eligible_candidate":
            raise Refused("independent_language_refused")
        nonce, expires = str(uuid4()), int(time.time()) + 120
        mac = hmac.digest(
            self._secret, message(seal, nonce, expires, self.approved_hash), "sha256"
        )
        return Proof(seal, nonce, expires, self.approved_hash, mac)


def admit_gate(db, gate, *, mode="writer"):
    """Additional fail-closed admission; unchanged G3 admission still runs.

    Manifest is provisioned out of request, not learned from live changed code.
    DB gate remains effective against direct SQL clients who skip this check.
    """
    rows = db.execute(
        """SELECT p.oid,p.proname,p.prosecdef,p.proconfig,
      pg_catalog.pg_get_functiondef(p.oid) AS definition,
      r.rolcanlogin,r.rolsuper,pg_catalog.has_function_privilege(p.oid,'EXECUTE') AS executable,
      EXISTS(SELECT 1 FROM pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
             WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_exec
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
      WHERE p.pronamespace=%s::regnamespace""",
        (gate.schema,),
    ).fetchall()
    actual = {
        r["proname"]: hashlib.sha256(r["definition"].encode()).hexdigest() for r in rows
    }
    if actual != gate.functions or any(
        r["public_exec"]
        or r["rolcanlogin"]
        or r["rolsuper"]
        or r["proconfig"] != ["search_path=pg_catalog"]
        or r["prosecdef"] != (r["proname"] != "hmac256")
        or r["executable"] != (mode == "writer" and r["proname"] == "seal")
        for r in rows
    ):
        raise Refused("trusted_boundary_unavailable")
    fk = db.execute(
        """SELECT condeferrable,condeferred,convalidated,confrelid=%s::regclass AS target,pg_catalog.pg_get_constraintdef(oid) AS definition
      FROM pg_catalog.pg_constraint WHERE conrelid=%s::regclass AND conname='g4_permit_required'
      AND contype='f'""",
        (gate.schema + ".permits", gate.graph_schema + ".ref_operations"),
    ).fetchone()
    if fk != dict(
        condeferrable=True,
        condeferred=True,
        convalidated=True,
        target=True,
        definition=gate.fk,
    ):
        raise Refused("trusted_boundary_unavailable")
    triggers = db.execute(
        """SELECT tgname,tgenabled,pg_catalog.pg_get_triggerdef(oid) AS definition
       FROM pg_catalog.pg_trigger WHERE tgrelid=%s::regclass AND NOT tgisinternal""",
        (gate.schema + ".permits",),
    ).fetchall()
    if (
        any(r["tgenabled"] != "O" for r in triggers)
        or {r["tgname"]: r["definition"] for r in triggers} != gate.triggers
    ):
        raise Refused("trusted_boundary_unavailable")
    columns = db.execute(
        """SELECT c.relname,a.attname,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'SELECT') AS sel,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'INSERT') AS ins,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'UPDATE') AS upd,
      pg_catalog.has_column_privilege(c.oid,a.attnum,'REFERENCES') AS refs
      FROM pg_catalog.pg_class c JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
      WHERE c.relnamespace=%s::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped""",
        (gate.schema,),
    ).fetchall()
    if {r["relname"] for r in columns} != {"policy", "permits"} or any(
        tuple(r[k] for k in ("sel", "ins", "upd", "refs"))
        != (
            False,
            mode == "writer"
            and r["relname"] == "permits"
            and r["attname"] != "created_at",
            False,
            False,
        )
        for r in columns
    ):
        raise Refused("trusted_boundary_unavailable")
    if (
        db.execute(
            """SELECT 1 FROM pg_catalog.pg_class WHERE relnamespace=%s::regnamespace AND relkind='r'
      AND pg_catalog.has_table_privilege(oid,'DELETE,TRUNCATE,TRIGGER')""",
            (gate.schema,),
        ).fetchone()
        or db.execute(
            "SELECT pg_catalog.has_schema_privilege(%s,'CREATE') AS bad", (gate.schema,)
        ).fetchone()["bad"]
    ):
        raise Refused("trusted_boundary_unavailable")


def seal(db, gate, oid):
    return db.execute(
        sql.SQL("SELECT {}(%s) AS seal").format(sql.Identifier(gate.schema, "seal")),
        (oid,),
    ).fetchone()["seal"]


def permit(db, gate, oid, proof=None):
    if proof is None:
        values = (
            oid,
            "broker",
            seal(db, gate, oid),
            str(uuid4()),
            int(time.time()) + 120,
            gate.validator_hash,
            None,
        )
    else:
        values = (
            oid,
            "credential",
            proof.seal,
            proof.nonce,
            proof.expires,
            proof.validator_hash,
            proof.mac,
        )
    db.execute(
        sql.SQL(
            "INSERT INTO {}(operation_id,mode,seal,nonce,expires_epoch,validator_hash,mac) VALUES(%s,%s,%s,%s,%s,%s,%s)"
        ).format(sql.Identifier(gate.schema, "permits")),
        (
            values[0],
            values[1],
            hashlib.sha256(values[2].encode("utf8")).hexdigest(),
            *values[3:],
        ),
    )


def submit(db, gate, b, key, body, *, issuer=None):
    """Stages only. Caller owns COMMIT/rollback. Broker capability stays private.

    Missing independent service is fatal for a NEW B command. Existing receipt
    replay doesn't require service, issue a new proof or create any row.
    """
    admit_gate(db, gate)
    if validator_hash() != gate.validator_hash:
        raise Refused("validator_version_unapproved")
    result, state = apply(db, b.sid, b.token, key, body)
    if state != "replayed":
        oid = result["operation_id"]
        if gate.mode == "credential":
            if issuer is None:
                raise Refused("trusted_validator_unavailable")
            proof = issuer.issue(seal(db, gate, oid))
            permit(db, gate, oid, proof)
        else:
            permit(db, gate, oid)
    return result, state


def read(db, gate, b, key):
    admit_gate(db, gate, mode="reader")
    return recover(db, b.sid, b.token, key)
