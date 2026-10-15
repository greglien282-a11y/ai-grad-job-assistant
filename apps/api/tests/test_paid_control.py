"""Paid-control proof with synthetic approvals ONLY, never a supplier call.

Positive balances/certificates below are isolated test fixtures, not owner
authorization or a proven DeepSeek tokenizer/framing bound.
"""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from decimal import Decimal
import multiprocessing
import os
import time
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.cost_ledger import canonical, digest
from app.deepseek_contract import ProbeError, SyntheticRequest, synthetic_requests
from app.deepseek_transport import DeepSeekOfficialTransport
from app.models import ProbeFunding, utcnow
from app.paid_control import PaidAdmin, PaidControl, PaidPolicy
from app.paid_models import PaidFunding, PaidScope, PaidGrant, PaidCall, PaidAudit
from test_cost_ledger import ledger_stack, profile  # fixture dependencies
from test_http_api import api
from test_deepseek_c0 import policy as offline_policy


def policy(**changes):
    req = synthetic_requests()[0]; fixture = offline_policy(req)
    now = utcnow(); until = now + timedelta(hours=1)
    data = dict(account_ref='synthetic-account-not-real', secret_ref_digest=digest('fake SecretRef, not a key'),
        output_cap=256, price=fixture.price.model_dump(mode='json'), price_starts_at=now-timedelta(minutes=1),
        price_account_ref='synthetic-account-not-real', calendar_digest=digest('synthetic calendar'),
        cache_rule_digest=digest('synthetic cache rules'), fx=fixture.fx.model_dump(mode='json'),
        fx_starts_at=now-timedelta(minutes=1), fx_approval_digest=digest('synthetic FX approval'),
        certificates=[dict(request_sha=req.fingerprint, input_bound=5000, evidence_digest=digest('TEST ONLY not a supplier proof'),
            kind='owner_attested_full_request_bound', tokenizer_version='synthetic-test-framing',
            covers_full_request_and_framing=True, expires_at=until)])
    data.update(changes)
    return PaidPolicy.model_validate(data)


@pytest.fixture
def paid(ledger_stack):
    _, factory, schema = ledger_stack
    admin = PaidAdmin(factory)
    with factory() as db: ledger_id = db.get(PaidFunding, 1).ledger_id
    control = PaidControl(factory.kw['bind'], schema, ledger_id)
    admin.approve_total('1', digest('synthetic total approval'))
    admin.approve_scope('provider', 'deepseek_official', '1', digest('synthetic provider approval'))
    admin.approve_scope('model', 'deepseek-flash', '1', digest('synthetic model approval'))
    p = policy()
    gid = authorize(admin, p)
    return admin, control, factory, schema, gid, p


def authorize(admin, p, **kw):
    args = dict(approver='synthetic-owner', proof=digest('fixture ' + str(uuid4())), starts_at=utcnow()-timedelta(seconds=1),
                expires_at=utcnow()+timedelta(minutes=30), ceiling='1', call_limit='1', calls_limit=20)
    args.update(kw)
    return admin.authorize(p, **args)


def reserve(paid, op='one', batch='batch-a', gid=None, p=None):
    _, control, _, _, grant, original = paid
    p = p or original
    return control.reserve(gid or grant, synthetic_requests()[0], op, batch, digest(canonical(p.model_dump(mode='json'))))


def permit(paid, cid, p=None):
    p = p or paid[5]
    return paid[1].transition(cid, 'permit', synthetic_requests()[0].fingerprint, digest(canonical(p.model_dump(mode='json'))))['permitted']


def expire(factory, cid):
    with factory.begin() as db: db.get(PaidCall, UUID(cid)).lease_until = utcnow()-timedelta(seconds=1)


def test_initial_paid_authority_zero_and_transport_denied(ledger_stack):
    _, factory, schema = ledger_stack
    with factory() as db:
        pool = db.get(PaidFunding, 1)
        assert pool.ceiling == pool.held == pool.spent == 0
        assert db.scalar(select(PaidGrant)) is None
        control = PaidControl(factory.kw['bind'], schema, pool.ledger_id)
    with patch('httpx.AsyncClient', side_effect=AssertionError('no HTTP')), patch('socket.getaddrinfo', side_effect=AssertionError('no DNS')):
        with pytest.raises(ProbeError, match='live_dispatch_disabled_c0'):
            asyncio.run(DeepSeekOfficialTransport().invoke(control=control, enabled=True))
    with pytest.raises(DBAPIError, match='paid_grant_inactive'):
        control.reserve(uuid4(), synthetic_requests()[0], 'one', 'fixture', digest('no grant'))


def test_decimal_worst_rate_and_shared_pool(paid):
    cid = reserve(paid)['id']
    row = paid[1].get(cid)
    assert row['reserved'] == Decimal('0.014910')  # peak miss, no cache assumption
    with paid[2]() as db:
        assert db.get(PaidFunding, 1).held == row['reserved']
        assert db.get(PaidFunding, 1).spent == 0
        assert db.get(PaidGrant, paid[4]).policy['price_currency'] == 'USD'
    with pytest.raises(ProbeError): paid[0].approve_total(0.5, digest('floats forbidden'))
    with pytest.raises(ProbeError, match='paid_limit_precision_invalid'):
        paid[0].approve_total('1.0000001', digest('cannot round up approved budget'))


def test_positive_test_authority_cannot_enable_transport_or_impersonate_fixture(paid):
    from app.deepseek_transport import FakeSecretResolver
    import httpx
    cid = reserve(paid)['id']; assert permit(paid, cid)
    with patch('httpx.AsyncClient', side_effect=AssertionError('HTTP forbidden')), patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')):
        with pytest.raises(ProbeError, match='live_dispatch_disabled_c0'):
            asyncio.run(DeepSeekOfficialTransport().invoke(control=paid[1], call_id=cid, approved=True))
        with pytest.raises(ProbeError):
            asyncio.run(DeepSeekOfficialTransport().exercise_offline(paid[1], paid[4], synthetic_requests()[0], 'wrong', 'wrong',
                resolver=FakeSecretResolver(), wire_transport=httpx.MockTransport(lambda _: None)))


def test_replay_conflict_and_once_intent(paid):
    first = reserve(paid)
    assert reserve(paid) == dict(id=first['id'], created=False)
    with pytest.raises(DBAPIError, match='paid_idempotency_conflict'): reserve(paid, batch='different')
    gid = authorize(paid[0], paid[5])
    with pytest.raises(DBAPIError, match='paid_idempotency_conflict'): reserve(paid, gid=gid)
    assert permit(paid, first['id']) is True
    assert permit(paid, first['id']) is False
    assert reserve(paid)['created'] is False
    with paid[2]() as db: assert len(db.scalars(select(PaidCall)).all()) == 1


@pytest.mark.parametrize('change', ['profile', 'account', 'source', 'certificate', 'fx', 'not_synthetic'])
def test_bad_policy_never_authorized(paid, change):
    data = paid[5].model_dump(mode='json')
    if change == 'profile': data['model'] = 'other'
    if change == 'account': data['price_account_ref'] = 'other'
    if change == 'source': data['price_currency'] = 'CNY_SIMULATED'
    if change == 'certificate': data['certificates'][0]['kind'] = 'offline_fixture_not_supplier_verified'
    if change == 'fx': data['fx']['expires_at'] = (utcnow()-timedelta(seconds=1)).isoformat()
    if change == 'not_synthetic': data['certificates'][0]['request_sha'] = digest('real user information forbidden')
    with pytest.raises(ProbeError): authorize(paid[0], PaidPolicy.model_validate(data))


def test_complete_bound_required_no_character_estimate(paid):
    data = paid[5].model_dump(mode='json')
    data['certificates'][0]['covers_full_request_and_framing'] = False
    with pytest.raises(ProbeError, match='paid_token_bound_unproven'):
        authorize(paid[0], PaidPolicy.model_validate(data))
    with pytest.raises(ProbeError, match='paid_synthetic_request_required'):
        paid[1].reserve(paid[4], SyntheticRequest('fake', 'fake', b'{"max_tokens":256,"private":"not allowed"}'), 'new', 'a', digest('p'))


def test_revoke_blocks_reserved_send_without_refund(paid):
    cid = reserve(paid)['id']; paid[0].revoke(paid[4], digest('synthetic revocation'))
    with pytest.raises(DBAPIError, match='paid_grant_inactive'): permit(paid, cid)
    assert paid[1].get(cid)['reserved'] == Decimal('.014910')
    with pytest.raises(DBAPIError, match='paid_immutable_record'):
        with paid[2].begin() as db: db.get(PaidGrant, paid[4]).revoked = False


@pytest.mark.parametrize('boundary', ['grant', 'price', 'fx', 'token'])
def test_expiry_rechecked_at_send(paid, boundary):
    data = paid[5].model_dump(mode='json'); until = utcnow()+timedelta(seconds=1)
    if boundary in ('price', 'fx'): data[boundary]['expires_at'] = until.isoformat()
    if boundary == 'token': data['certificates'][0]['expires_at'] = until.isoformat()
    p = PaidPolicy.model_validate(data)
    gid = authorize(paid[0], p, **({'expires_at':until} if boundary == 'grant' else {}))
    cid = reserve(paid, gid=gid, p=p)['id']
    time.sleep(1.1)
    with pytest.raises(DBAPIError, match='paid_grant_inactive|paid_rate_expired|paid_token_bound_unproven'): permit(paid, cid, p)


def test_configuration_and_ledger_binding(paid):
    cid = reserve(paid)['id']
    with pytest.raises(DBAPIError, match='paid_configuration_changed'):
        paid[1].transition(cid, 'permit', synthetic_requests()[0].fingerprint, digest('other config'))
    wrong = PaidControl(paid[2].kw['bind'], paid[3], uuid4())
    with pytest.raises(ProbeError, match='paid_ledger_identity_mismatch'): wrong.get(cid)
    with pytest.raises(DBAPIError, match='paid_ledger_identity_mismatch'): wrong.recover()


@pytest.mark.parametrize('failure', ['timeout', 'cancel', 'disconnect', 'http_429', 'http_5xx'])
def test_unknown_never_refunds_or_resends(paid, failure):
    # The ledger has no network path: callers map any ambiguous transport
    # outcome to the SAME unknown state, not a free retry/refund.
    cid = reserve(paid)['id']; assert permit(paid, cid)
    paid[1].transition(cid, 'unknown')
    assert paid[1].get(cid)['state'] == 'unknown'
    assert permit(paid, cid) is False
    with pytest.raises(DBAPIError, match='paid_pool_blocked'): reserve(paid, op=failure)
    with paid[2]() as db: assert db.get(PaidFunding, 1).held == Decimal('.014910')


def test_response_received_still_holds_and_usage_overrun_freezes(paid):
    cid = reserve(paid)['id']; assert permit(paid, cid)
    with pytest.raises(DBAPIError, match='paid_usage_invalid'):
        paid[1].transition(cid, 'received', usage={'secret':'forbidden'})
    paid[1].transition(cid, 'received', usage={'input_tokens':5001, 'output_tokens':256})
    assert paid[1].get(cid)['state'] == 'response_received'
    with paid[2]() as db:
        assert db.get(PaidFunding, 1).frozen
        assert db.get(PaidFunding, 1).held == Decimal('.014910')


def test_invoice_dedup_actual_usd_fx_and_no_auto_unfreeze(paid):
    cid = reserve(paid)['id']; assert permit(paid, cid)
    invoice, proof = digest('synthetic invoice one'), digest('synthetic invoice review')
    assert paid[0].reconcile(UUID(cid), '.01', invoice, proof)
    assert paid[0].reconcile(UUID(cid), '.01', invoice, proof) is False
    assert paid[1].get(cid)['actual'] == Decimal('.075000')
    totals = paid[1].totals()
    assert totals['provider'][0]['actual_usd'] == Decimal('.01')
    assert totals['model'][0]['actual_cny'] == Decimal('.075000')
    with paid[2]() as db: assert db.get(PaidFunding, 1).frozen
    with pytest.raises(ProbeError, match='paid_invoice_conflict'): paid[0].reconcile(UUID(cid), '.02', invoice, proof)
    paid[0].unfreeze(digest('explicit synthetic manual review'))
    second = reserve(paid, op='second')['id']; assert permit(paid, second)
    with pytest.raises(ProbeError, match='paid_invoice_already_used'): paid[0].reconcile(UUID(second), '.01', invoice, proof)
    paid[1].transition(second, 'unknown')
    with pytest.raises(ProbeError, match='paid_review_unresolved'): paid[0].unfreeze(proof)


def test_expired_reserved_requires_owner_and_sent_recovery_read_only(paid):
    cid = reserve(paid)['id']; expire(paid[2], cid)
    assert paid[1].recover()['recovered'] == 0
    assert paid[1].get(cid)['actual'] is None
    paid[0].close_unsent(UUID(cid), digest('proven never sent review'))
    assert paid[1].get(cid)['actual'] == 0
    second = reserve(paid, op='second')['id']; assert permit(paid, second)
    expire(paid[2], second)
    assert paid[1].get(second)['state'] == 'unknown'
    assert paid[1].get(second)['persisted_state'] == 'sent'
    assert paid[1].recover()['recovered'] == 1
    assert paid[1].get(second)['persisted_state'] == 'unknown'
    assert paid[1].get(second)['actual'] is None


@pytest.mark.parametrize('scope', ['global', 'provider', 'model', 'grant', 'call', 'count'])
def test_individual_limits(paid, scope):
    p = paid[5]; gid = paid[4]
    if scope == 'global':
        with paid[2].begin() as db: db.get(PaidFunding, 1).ceiling = Decimal('.01')
    elif scope in ('provider','model'):
        key = 'deepseek_official' if scope == 'provider' else 'deepseek-flash'
        paid[0].approve_scope(scope, key, '.01', digest('synthetic lower limit'))
    else:
        gid = authorize(paid[0], p, **({'ceiling':'.01', 'call_limit':'.01'} if scope == 'grant' else
                                   {'call_limit':'.01'} if scope == 'call' else {'calls_limit':1}))
    if scope == 'count':
        cid = reserve(paid, gid=gid)['id']; assert permit(paid, cid)
        paid[0].reconcile(UUID(cid), '0', digest('synthetic zero invoice'), digest('review'))
    with pytest.raises(DBAPIError, match='paid_budget_exceeded|paid_scope_exceeded|paid_call_limit'):
        reserve(paid, gid=gid, op='limit')


def worker(url, schema, ledger, gid, op, p, send=False, crash=False):
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
    try:
        control = PaidControl(engine, schema, ledger)
        try:
            row = control.reserve(gid, synthetic_requests()[0], op, op, p)
            permitted = control.transition(row['id'], 'permit', synthetic_requests()[0].fingerprint, p)['permitted'] if send else False
            if crash and permitted: os._exit(41)
            return row, permitted
        except DBAPIError: return None, False
    finally: engine.dispose()


def test_multiprocess_multigrant_batches_share_total(paid):
    # Exactly one .014910 reserve fits .02, regardless of process/grant/batch.
    with paid[2].begin() as db: db.get(PaidFunding, 1).ceiling = Decimal('.02')
    p = digest(canonical(paid[5].model_dump(mode='json')))
    gids = [paid[4], authorize(paid[0], paid[5], ceiling='.02', call_limit='.02')]
    args = [(os.environ['TEST_DATABASE_URL'], paid[3], paid[1].ledger_id, str(gids[i]), 'batch-'+str(i), p) for i in range(2)]
    with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context('spawn')) as executor:
        futures = [executor.submit(worker, *a) for a in args]
        rows = [f.result(timeout=45) for f in futures]
    assert sum(row is not None for row, _ in rows) == 1
    with paid[2]() as db: assert db.get(PaidFunding, 1).held == Decimal('.014910')


def test_multiprocess_same_key_only_one_intent(paid):
    p = digest(canonical(paid[5].model_dump(mode='json')))
    args = (os.environ['TEST_DATABASE_URL'], paid[3], paid[1].ledger_id, str(paid[4]), 'same-key', p, True)
    with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context('spawn')) as executor:
        futures = [executor.submit(worker, *args) for _ in range(2)]
        rows = [f.result(timeout=45) for f in futures]
    assert len({r['id'] for r, _ in rows}) == 1
    assert sum(sent for _, sent in rows) == 1


def test_real_process_exit_persists_intent_without_second_send(paid):
    p = digest(canonical(paid[5].model_dump(mode='json')))
    process = multiprocessing.get_context('spawn').Process(target=worker, args=(
        os.environ['TEST_DATABASE_URL'], paid[3], paid[1].ledger_id, str(paid[4]), 'crash', p, True, True))
    process.start(); process.join(45)
    assert process.exitcode == 41
    with paid[2]() as db: cid = str(db.scalar(select(PaidCall.id)))
    assert paid[1].get(cid)['persisted_state'] == 'sent'
    expire(paid[2], cid)
    assert paid[1].get(cid)['state'] == 'unknown'
    assert paid[1].recover()['recovered'] == 1
    assert permit(paid, cid) is False
    assert paid[1].get(cid)['reserved'] == Decimal('.014910')


def test_immutable_audit_and_grant_and_no_namespace(paid):
    with pytest.raises(DBAPIError, match='paid_immutable_record'):
        with paid[2].begin() as db: db.get(PaidGrant, paid[4]).policy = {'modified':True}
    with pytest.raises(DBAPIError, match='paid_immutable_record'):
        with paid[2].begin() as db: db.execute(text('DELETE FROM paid_audit'))
    with pytest.raises(TypeError): PaidControl(paid[2].kw['bind'], paid[3], paid[1].ledger_id, namespace='copy')
    with pytest.raises(DBAPIError):
        with paid[2].begin() as db: db.add(PaidFunding(id=2, ledger_id=uuid4(), ceiling=1, held=0, spent=0, frozen=False))


def test_0007_0008_roundtrip_compatibility(migrated_connection):
    conn, cfg = migrated_connection
    assert conn.scalar(text('SELECT ceiling FROM paid_funding')) == 0
    command.check(cfg); conn.commit()
    command.downgrade(cfg, '0007_probe_preflight'); conn.commit()
    conn.execute(text('INSERT INTO probe_funding VALUES (1,0,1,0,0,false,NULL)')); conn.commit()
    command.upgrade(cfg, 'head'); command.check(cfg); conn.commit()
    assert conn.scalar(text('SELECT approved_real_cny FROM probe_funding')) == 0
    assert conn.scalar(text('SELECT count(*) FROM paid_grants')) == 0


def test_runtime_role_cannot_mint_authority_or_unfreeze(paid):
    admin, control, factory, schema, gid, p = paid
    engine = factory.kw['bind']; role = 'paid_test_' + uuid4().hex
    with engine.connect() as conn: owner = conn.scalar(text('SELECT current_user'))
    with pytest.raises(ProbeError, match='paid_runtime_role_not_restricted'):
        admin.provision_runtime_role(schema, owner)
    with engine.connect() as conn:
        can_roles = conn.scalar(text('SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user'))
    if not can_roles:
        # Local dedicated DB owner has NO role-administration privilege. Do
        # not mutate machine roles or borrow an administrator's credential.
        # CI is required to execute the complete restricted-role branch.
        assert not os.getenv('CI'), 'CI must run actual restricted-role checks'
        with engine.connect() as conn:
            assert not conn.scalar(text("SELECT has_function_privilege('public', :f, 'EXECUTE')"), {'f':f'{schema}.paid_runtime(text,text,jsonb)'})
        return
    with engine.begin() as conn:
        conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'))
    role_engine = create_engine(os.environ['TEST_DATABASE_URL'], poolclass=NullPool,
                               connect_args={'options':f'-crole={role}'}, hide_parameters=True)
    try:
        admin.provision_runtime_role(schema, role)
        app = PaidControl(role_engine, schema, control.ledger_id)
        ph = digest(canonical(p.model_dump(mode='json')))
        cid = app.reserve(gid, synthetic_requests()[0], 'restricted', 'restricted', ph)['id']
        assert app.transition(cid, 'permit', synthetic_requests()[0].fingerprint, ph)['permitted']
        forbidden = [f'UPDATE "{schema}".paid_funding SET ceiling=100', f'UPDATE "{schema}".paid_funding SET frozen=false',
            f'DELETE FROM "{schema}".paid_calls', f'DELETE FROM "{schema}".paid_audit',
            f'UPDATE "{schema}".paid_grants SET revoked=false', f'CREATE TABLE "{schema}".other_pool(id int)',
            f'INSERT INTO "{schema}".paid_grants SELECT * FROM "{schema}".paid_grants',
            f'UPDATE "{schema}".paid_scopes SET ceiling=100']
        forbidden += ['CREATE SCHEMA paid_copy_budget']
        for sql in forbidden:
            with pytest.raises(DBAPIError, match='permission denied'):
                with role_engine.begin() as conn: conn.execute(text(sql))
        with pytest.raises(ProbeError, match='paid_runtime_role_not_restricted'):
            admin.provision_runtime_role(schema, 'pathwise_test')
    finally:
        role_engine.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))
