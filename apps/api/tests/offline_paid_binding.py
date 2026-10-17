"""Offline fixture installer/coordinator, NOT importable from a Provider factory.

Uses the ORIGINAL 0008 paid_runtime inside the SAME transaction as binding DDL.
No alternate balance, HTTP, secret resolution or automatic recovery/retry.
"""
import hashlib
import hmac
import json
from pathlib import Path
import re
from uuid import UUID

from sqlalchemy import select, text

from app import facts
from app.cost_ledger import canonical, digest
from app.deepseek_contract import SyntheticRequest, synthetic_requests
from app.mining_call_binding import MiningCallBindingV1
from app.models import MiningRun, MiningReceipt, ConversationTurn
from app.paid_control import PaidControl
from app.paid_models import PaidGrant


def identifier(value):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', value):
        raise ValueError('binding_identifier_invalid')
    return '"' + value + '"'


def install_test_proposal(connection, schema, role):
    url = connection.engine.url
    if (url.database not in ('pathwise_test', 'pathwise_e2e') or url.host not in ('127.0.0.1', 'localhost')
        or not re.fullmatch('test_[a-f0-9]{32}', schema)
        or connection.scalar(text('SELECT current_database()')) != url.database
        or connection.scalar(text('SELECT current_schema()')) != schema):
        raise ValueError('binding_isolated_schema_required')
    sql = (Path(__file__).parent / 'fixtures/mining_paid_binding_v1.sql').read_text(encoding='utf-8')
    identifier(role)
    sql = sql.replace('__SCHEMA__', identifier(schema)).replace('__ROLE__', identifier(role))
    sql = sql.replace('__SCHEMA_RAW__', schema).replace('__SCHEMA_LITERAL__', "'" + schema + "'")
    sql = sql.replace('__ROLE_LITERAL__', "'" + role + "'")
    # SQL is fixed test fixture source with validated identifiers, no passwords.
    connection.exec_driver_sql(sql, execution_options={'no_parameters': True})


def scopes(scope_key, server_actor, sid):
    """Synthetic server identity only. Not a client-supplied user/session tag.

    A real authenticated principal/issuance service does not yet exist in MVP.
    No Bearer/token hash is used as a user identifier or written to this table.
    """
    return (hmac.digest(scope_key, ('actor:' + server_actor).encode(), 'sha256').hex(),
            hmac.digest(scope_key, ('session:' + str(sid)).encode(), 'sha256').hex())


def stage_test_plan(factory, schema, control, sid, token, rid, context, request):
    """Owner-fixture staging after real business authorization, never runtime.

    Call/request/grant references are supplied by this trusted test service,
    NOT frontend JSON. The existing synthetic whitelist remains unchanged.
    """
    identifier(schema)
    if type(request) is not SyntheticRequest or request not in synthetic_requests(256):
        raise ValueError('binding_synthetic_request_required')
    policy = control.checked_policy(control.fixture_grant)
    parsed = json.loads(request.body)
    approved_context = json.loads(parsed['messages'][1]['content'])
    with factory() as db, db.begin():
        facts.authorize(db, sid, token, lock=True)
        run = db.get(MiningRun, rid)
        if (run is None or run.session_id != sid or run.project_id != context.project_id
            or run.reserved_revision != context.context_revision or run.input_turn_id != context.input_turn_id):
            raise ValueError('binding_business_identity_invalid')
        original = db.get(ConversationTurn, run.input_turn_id)
        if (str(run.project_id) != approved_context['project_id']
            or str(original.id) != approved_context['input_turn_id']
            or original.content != approved_context['user_turns'][0]['content']):
            raise ValueError('binding_fixture_source_mismatch')
        root = run
        visited = set()
        while root.retry_of:
            if root.id in visited: raise ValueError('binding_retry_cycle')
            visited.add(root.id)
            root = db.get(MiningRun, root.retry_of)
            if root is None or root.session_id != sid: raise ValueError('binding_retry_identity_invalid')
        receipt = db.scalar(select(MiningReceipt).where(MiningReceipt.run_id == root.id))
        if receipt is None: raise ValueError('binding_original_receipt_missing')
        identity = db.execute(text(f'SELECT actor_scope,session_scope FROM "{schema}".binding_identity WHERE session_id=:sid'), {'sid':sid}).mappings().one()
        operation = digest(canonical(dict(version=1, ledger=control.ledger_id,
            receipt=receipt.key_digest, **identity)))
        policy_sha = digest(canonical(policy.model_dump(mode='json')))
        db.execute(text(f'''INSERT INTO "{schema}".binding_plans(run_id,root_run_id,session_id,ledger_id,grant_id,
            operation_hash,receipt_hash,request_sha,policy_sha,context_sha,prompt_sha,schema_sha,account_sha,profile_version)
            VALUES(:rid,:root,:sid,:ledger,:grant,:operation,:receipt,:request,:policy,:context,:prompt,:schema_sha,:account,'fixed-fixture-binding-v1')'''),
            dict(rid=rid,root=root.id,sid=sid,ledger=UUID(control.ledger_id),grant=control.fixture_grant,
                operation=operation,receipt=receipt.key_digest,request=request.fingerprint,policy=policy_sha,
                context=digest(canonical(context.payload())),prompt=digest(parsed['messages'][0]['content']),
                schema_sha=hashlib.sha256((Path(__file__).parents[3]/'docs/evaluation/provider-wire-output.schema.json').read_bytes()).hexdigest(),
                account=digest(policy.account_ref)))


class BindingControl:
    """Separate test LOGIN, only SELECT + this reviewed proposal function.

    Not PaidControl inheritance. No synthetic/live flag or HTTP entry exists.
    """
    def __init__(self, engine, schema, ledger_id):
        identifier(schema)
        if (engine.url.database not in ('pathwise_test','pathwise_e2e') or engine.url.host not in ('localhost','127.0.0.1')
            or not re.fullmatch('test_[a-f0-9]{32}',schema)):
            raise ValueError('binding_isolated_schema_required')
        self.engine, self.schema, self.ledger_id = engine, schema, str(UUID(str(ledger_id)))

    def statement(self):
        return text(f'SELECT "{self.schema}".binding_runtime(CAST(:ledger AS uuid),:action,CAST(:rid AS uuid),CAST(:usage AS jsonb))')

    def payload(self, action, rid, usage=None):
        return dict(ledger=self.ledger_id,action=action,rid=str(UUID(str(rid))),usage=canonical(usage))

    def invoke(self, action, rid, usage=None):
        if action not in ('bind','permit','received','unknown'):
            raise ValueError('binding_action_invalid')
        with self.engine.begin() as conn:
            return conn.scalar(self.statement(), self.payload(action,rid,usage))

    def read(self, rid):
        with self.engine.connect() as conn, conn.begin():
            conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            if conn.scalar(text('SELECT current_database()')) != self.engine.url.database:
                raise ValueError('binding_isolated_schema_required')
            actual_ledger = conn.scalar(text(f'SELECT ledger_id FROM "{self.schema}".paid_funding WHERE id=1'))
            if str(actual_ledger) != self.ledger_id: raise ValueError('binding_ledger_mismatch')
            consistent = conn.scalar(text(f'''SELECT held=(SELECT coalesce(sum(reserved),0) FROM "{self.schema}".paid_calls WHERE actual IS NULL)
                AND spent=(SELECT coalesce(sum(actual),0) FROM "{self.schema}".paid_calls)
                FROM "{self.schema}".paid_funding WHERE id=1'''))
            if consistent is not True: raise ValueError('binding_ledger_inconsistent')
            row = conn.execute(text(f'''SELECT b.*,c.state AS paid_state,c.reserved,c.actual,
                c.operation_hash AS call_operation,c.request_hash AS call_request,c.policy_hash AS call_policy,
                c.provider AS call_provider,c.model AS call_model,c.grant_id AS call_grant
                FROM "{self.schema}".mining_call_bindings b JOIN "{self.schema}".paid_calls c ON c.id=b.call_id
                WHERE b.run_id=:rid AND b.ledger_id=CAST(:ledger AS uuid)'''),
                dict(rid=rid,ledger=self.ledger_id)).mappings().one()
            if (row['operation_hash'],row['request_sha'],row['policy_sha'],row['provider'],row['model'],row['grant_id']) != (
                row['call_operation'],row['call_request'],row['call_policy'],row['call_provider'],row['call_model'],row['call_grant']):
                raise ValueError('binding_ledger_inconsistent')
            metadata = {name: row[name] for name in MiningCallBindingV1.model_fields}
            return MiningCallBindingV1.model_validate(metadata), row['paid_state'], row['reserved'], row['actual']
