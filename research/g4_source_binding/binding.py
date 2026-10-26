"""Second isolated boundary: authenticate the request BEFORE writer staging.

Trusted ingress and validator keys are distinct from Bearer/writer credentials.
No HTTP/factory, new SQL, production contract or durable ingress-event model.
"""

from copy import deepcopy
from dataclasses import dataclass, replace, asdict
import hashlib
import hmac
import json
from pathlib import Path
import time
from uuid import uuid4

from app.typed_semantic_spike import validate_candidate
from research.g3_choice_protocol.runtime import (
    admit,
    authorized,
    apply,
    digest,
    Refused,
)
from research.g4_trusted_boundary.runtime import (
    Issuer,
    validator_hash,
    message,
    admit_gate,
    seal,
    permit,
)

CONTRACT = "g4-authenticated-ingress-ref-v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def approved_hash():
    return hashlib.sha256(
        Path(__file__).read_bytes() + validator_hash().encode()
    ).hexdigest()


@dataclass(frozen=True)
class Origin:
    contract: str
    body: dict
    key_digest: str
    bearer_digest: str
    subject: str
    nonce: str
    expires: int
    mac: bytes


def origin_message(proof):
    return canonical({k: v for k, v in asdict(proof).items() if k != "mac"}).encode(
        "utf8"
    )


class Ingress:
    """Separate trusted request receiver. Never a writer-supplied actor label.

    The host must authenticate/retain the exact received HTTP body before
    handing it to the untrusted adapter. Human gesture/truth remain unproved.
    """

    def __init__(self, key):
        self._key = key

    def capture(self, db, gate, b, key, body):
        admit_gate(db, gate, mode="reader")
        admit(db, mode="reader")
        authorized(db, b.sid, b.token)
        if db.execute(
            "SELECT current_setting('transaction_read_only') AS ro,current_setting('transaction_isolation') AS iso"
        ).fetchone() != dict(ro="on", iso="repeatable read"):
            raise Refused("source_readonly_required")
        session = db.execute(
            "SELECT project_id,subject_id,revision FROM ref_sessions WHERE id=%s",
            (b.sid,),
        ).fetchone()
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
            or body["reference_contract"] != "g3-choice-graph-ref-v1"
            or type(body["contract_version"]) is not int
            or body["contract_version"] != 3
            or body["scheme"] != "A"
            or body["session_id"] != str(b.sid)
            or body["project_id"] != str(session["project_id"])
            or type(body["base_revision"]) is not int
            or body["base_revision"] != session["revision"]
        ):
            raise Refused("source_request_invalid")
        decision = validate_candidate(
            dict(
                validation_contract="typed-semantic-spike-v1",
                synthetic=True,
                raw_text=body["content"],
                items=[
                    {k: v for k, v in item.items() if k != "selection_id"}
                    for item in body["items"]
                ],
            )
        )
        # Record an exact source even when the user's declaration is invalid;
        # this credential does NOT claim semantic validation has succeeded.
        if decision.citations_valid is not True:
            raise Refused("source_quotes_invalid")
        proof = Origin(
            CONTRACT,
            deepcopy(body),
            digest(key),
            digest(b.token),
            str(session["subject_id"]),
            str(uuid4()),
            int(time.time()) + 120,
            b"",
        )
        return replace(
            proof, mac=hmac.digest(self._key, origin_message(proof), "sha256")
        )


class BoundIssuer:
    """Trusted signer checks independently authenticated ingress AND language.

    This prototype shares an ingress verification HMAC key with the validator;
    either trusted root compromised breaks it. No natural-human attestation.
    """

    def __init__(self, signing_key, ingress_key, version):
        self._signing = signing_key
        self._ingress = ingress_key
        self.version = version

    def issue(self, serialized, source):
        if self.version != approved_hash():
            raise Refused("source_validator_unapproved")
        if (
            type(source) is not Origin
            or source.contract != CONTRACT
            or type(source.expires) is not int
            or source.expires <= time.time()
            or not hmac.compare_digest(
                source.mac, hmac.digest(self._ingress, origin_message(source), "sha256")
            )
        ):
            raise Refused("authenticated_source_required")
        g = json.loads(serialized)
        op = g["operation"]
        choices = g["choices"]
        turns = g["turns"]
        if len(turns) != 1:
            raise Refused("authenticated_source_mismatch")
        body = dict(
            reference_contract="g3-choice-graph-ref-v1",
            contract_version=op["contract_version"],
            scheme=op["scheme"],
            session_id=op["session_id"],
            project_id=op["project_id"],
            base_revision=op["base_revision"],
            content=turns[0]["content"],
            items=[
                dict(
                    quote=c["quote"],
                    start=c["start_cp"],
                    end=c["end_cp"],
                    fact_kind=c["fact_kind"],
                    progress_stage=c["progress_stage"],
                    classification_contract=c["classification_contract"],
                    selection_id=c["selection_id"],
                )
                for c in choices
            ],
        )
        if (
            canonical(body) != canonical(source.body)
            or op["key_digest"] != source.key_digest
            or op["owner_digest"] != source.bearer_digest
            or g["auth"]["authenticated_subject"] != source.subject
            or g["session"]["subject_id"] != source.subject
        ):
            raise Refused("authenticated_source_mismatch")
        checked = Issuer(self._signing, validator_hash()).issue(serialized)
        checked = replace(
            checked,
            validator_hash=self.version,
            expires=min(source.expires, checked.expires),
        )
        return replace(
            checked,
            mac=hmac.digest(
                self._signing,
                message(
                    checked.seal, checked.nonce, checked.expires, checked.validator_hash
                ),
                "sha256",
            ),
        )


def stage(db, gate, b, key, body, source, issuer):
    admit_gate(db, gate)
    if gate.validator_hash != approved_hash():
        raise Refused("source_validator_unapproved")
    result, state = apply(db, b.sid, b.token, key, body)
    if state != "replayed":
        if issuer is None:
            raise Refused("trusted_source_service_unavailable")
        proof = issuer.issue(seal(db, gate, result["operation_id"]), source)
        permit(db, gate, result["operation_id"], proof)
    return result, state
