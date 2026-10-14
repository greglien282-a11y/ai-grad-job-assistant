"""Bounded, Bearer-bound receipts. Never retain request/response plaintext."""
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re

from sqlalchemy import delete, event, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import IdempotencyOperation, utcnow

WINDOW = timedelta(hours=24)
FIELDS = ('operation', 'session_id', 'target_id', 'request_tag', 'project_id', 'initial_turn_id', 'turn_id', 'fact_id')


class IdempotencyError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)  # Safe code only, never a key/credential/tag.


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def decode(value: str) -> bytes:
    try:
        raw = base64.b64decode(value + '=', altchars=b'-_', validate=True)
        if len(raw) != 32 or encode(raw) != value:
            raise ValueError
        return raw
    except (ValueError, TypeError):
        raise IdempotencyError(422, 'idempotency_key_invalid') from None


def message(kind, scope, issued, nonce):
    return '\n'.join(('pathwise-idempotency-v1', kind, scope, str(issued), nonce)).encode()


@dataclass(frozen=True, repr=False)
class OperationKey:
    digest: str
    expires_at: datetime
    kind: str
    scope: str

    def fresh(self):
        if utcnow() >= self.expires_at:
            raise IdempotencyError(410, 'idempotency_key_expired')


def parse(value, token, kind, scope):
    if not value or len(value) > 128:
        raise IdempotencyError(422, 'idempotency_key_invalid')
    match = re.fullmatch(r'v1\.([1-9][0-9]{9})\.([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})', value)
    if not match:
        raise IdempotencyError(422, 'idempotency_key_invalid')
    issued, nonce, proof = match.groups()
    decode(nonce); supplied = decode(proof)
    if not token or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise IdempotencyError(401, 'idempotency_credential_invalid')
    try:
        decode(token)
    except IdempotencyError:
        raise IdempotencyError(401, 'idempotency_credential_invalid') from None
    expected = hmac.digest(token.encode(), message(kind, scope, issued, nonce), 'sha256')
    if not hmac.compare_digest(supplied, expected):
        raise IdempotencyError(401, 'idempotency_credential_invalid')
    timestamp = datetime.fromtimestamp(int(issued), timezone.utc)
    if timestamp > utcnow() + timedelta(minutes=5):
        raise IdempotencyError(422, 'idempotency_clock_skew')
    key = OperationKey(hashlib.sha256(value.encode()).hexdigest(), timestamp + WINDOW, kind, scope)
    key.fresh()
    return key


def request_tag(key, token, body):
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hmac.new(token.encode(), (key.kind + '\n' + key.scope + '\n' + canonical).encode(), hashlib.sha256).hexdigest()


def lock(db, key):
    # Transaction-scoped; PostgreSQL coordinates independent processes/connections.
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    number = int.from_bytes(bytes.fromhex(key.digest)[:8], 'big', signed=True)
    try:
        db.execute(text('SELECT pg_advisory_xact_lock(:number)'), {'number': number})
    except OperationalError as exc:
        if getattr(exc.orig, 'sqlstate', None) == '55P03':
            raise IdempotencyError(503, 'idempotency_busy') from None
        raise
    key.fresh()
    # Recheck using a real clock immediately before the transaction commits.
    db.info.setdefault('idempotency_keys', []).append(key)


def existing(db, key):
    return db.scalar(select(IdempotencyOperation).where(IdempotencyOperation.key_digest == key.digest).execution_options(populate_existing=True))


def match_receipt(row, key, tag=None):
    if row.state == 'deleted':
        raise IdempotencyError(410, 'idempotency_resource_deleted')
    if row.operation != key.kind:
        raise IdempotencyError(409, 'idempotency_payload_mismatch')
    if tag is not None and not hmac.compare_digest(row.request_tag, tag):
        raise IdempotencyError(409, 'idempotency_payload_mismatch')


def remember(db, key, token, body, **ids):
    db.add(IdempotencyOperation(key_digest=key.digest, state='completed', expires_at=key.expires_at,
                               operation=key.kind, request_tag=request_tag(key, token, body), **ids))
    db.flush()


def erase_receipts(db, session_id):
    db.execute(update(IdempotencyOperation).where(IdempotencyOperation.session_id == session_id)
               .values(state='deleted', **{field: None for field in FIELDS}))


def cleanup(db: Session):
    # Only expired operation metadata, never session/business rows.
    return db.execute(delete(IdempotencyOperation).where(IdempotencyOperation.expires_at <= utcnow())).rowcount


@event.listens_for(Session, 'before_commit')
def enforce_deadline(db):
    for key in db.info.get('idempotency_keys', []):
        key.fresh()


@event.listens_for(Session, 'after_transaction_end')
def clear_deadlines(db, transaction):
    if transaction.parent is None:
        db.info.pop('idempotency_keys', None)
