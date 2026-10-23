"""G2.3 existing-DB boundaries; no CO3 writer or schema is installed.

Actual independent LOGINs/random schemas reuse reviewed fixtures. Pure M4
checks remain a simulation, explicitly distinct from these PostgreSQL checks.
"""
from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, DBAPIError

from app.fact_maintenance_models import ConversationOperation
from test_http_api import api
from test_maintenance_api import service, seed, key, recovery as v1_recovery
from test_append_api import append_service, body, post, recover
from test_experience_read import reader
from test_legacy_upgrade_handoff import digest
from test_overnight_typed_model import applied
from overnight_research.typed_model import validate, ModelInvalid


@pytest.mark.parametrize('version', [0, 3, 4])
def test_real_restricted_sql_cannot_install_unknown_operation_contract(append_service, version):
    s = append_service; b = seed(s); h = key(b)
    result = post(s, b, body(b), h)
    assert result.status_code == 201
    with s.admin() as db:
        original = db.get(ConversationOperation, UUID(result.json()['operation_id']))
        values = {c.name: deepcopy(getattr(original, c.name)) for c in ConversationOperation.__table__.columns}
    values.update(id=uuid4(), key_digest=uuid4().hex*2, contract_version=version)
    before = digest(s.admin)
    with pytest.raises(IntegrityError) as exc, s.append_runtime.begin() as db:
        db.execute(ConversationOperation.__table__.insert().values(**values))
    assert exc.value.orig.sqlstate == '23514'
    assert exc.value.orig.diag.constraint_name == 'ck_co_identity'
    assert digest(s.admin) == before
    assert recover(s, b, h).json() == result.json()
    assert digest(s.admin) == before


def test_real_old_receipt_contract_collision_is_not_a_new_command(append_service):
    s = append_service; b = seed(s); h = key(b); value = body(b)
    original = post(s, b, value, h)
    assert original.status_code == 201
    before = digest(s.admin)
    wrong_route = v1_recovery(s, b, h)
    assert wrong_route.status_code == 409
    assert wrong_route.json()['error']['code'] == 'conversation_contract_mismatch'
    replay = post(s, b, value, h)
    assert replay.status_code == 200 and replay.json() == original.json()
    changed = deepcopy(value); changed['base_revision'] += 1
    conflict = post(s, b, changed, h)
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'idempotency_payload_mismatch'
    assert digest(s.admin) == before


def test_real_reader_cannot_create_basis_or_any_write_effect(reader):
    s = reader; b = seed(s); before = digest(s.admin)
    with s.reader.begin() as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        role = db.execute(text('SELECT current_user, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
        assert role[0] == s.read_role and not any(role[1:])
        assert db.scalar(text("SELECT current_setting('transaction_read_only')")) == 'on'
        assert db.scalar(text("SELECT current_setting('transaction_isolation')")) == 'repeatable read'
        assert db.scalar(text("SELECT to_regclass(current_schema()||'.classification_declarations')")) is None
    # Runtime SELECT-only is independently effective even without READ ONLY.
    with pytest.raises(DBAPIError) as exc, s.reader.begin() as db:
        db.execute(text('INSERT INTO conversation_turns(id,session_id,role,content) VALUES(:id,:sid,\'user\',\'synthetic\')'),
                   {'id': uuid4(), 'sid': b.sid})
    assert exc.value.orig.sqlstate == '42501'
    assert digest(s.admin) == before


@pytest.mark.parametrize('damage', ['basis_missing', 'basis_wrong_slot', 'basis_wrong_version_graph'])
def test_reference_model_graph_checks_are_explicitly_not_db_enforcement(damage):
    state = applied()
    if damage == 'basis_missing': broken = replace(state, bases=())
    elif damage == 'basis_wrong_slot': broken = replace(state, bases=(replace(state.bases[0], slot=2),))
    else: broken = replace(state, bases=(replace(state.bases[0], change='nonexistent-history'),))
    with pytest.raises(ModelInvalid): validate(broken)
    validate(state)
    assert state.bases[0].evidence_class == 'SIMULATED_DECLARATION_ONLY'
