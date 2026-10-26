"""Non-writer protocol preparation against REAL CO1/CO2. Not a CO3 service.

No new operation is created here. Existing legacy and future reference stores
are NOT one collision domain; reverse-order failure evidence is deliberate.
"""

from app import facts, fact_maintenance, idempotency
from app.maintenance_errors import ConversationError


def prepare(db, sid, token, raw_key, body):
    key = idempotency.parse(raw_key, token, fact_maintenance.KIND, f"session:{sid}")
    facts.authorize(db, sid, token)  # no receipt/version disclosure first
    old = fact_maintenance.existing(db, key)
    if old is not None:
        if old.session_id is not None and old.session_id != sid:
            raise PermissionError("Resource unavailable")
        fact_maintenance.available(old)
        raise ConversationError(409, "research_old_contract_collision")
    if type(body.get("contract_version")) is not int or body["contract_version"] != 3:
        raise ConversationError(409, "research_future_contract_unsupported")
    return key, idempotency.request_tag(key, token, body)
