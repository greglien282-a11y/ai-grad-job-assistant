"""Synthetic responses only; never vendor IO, real credentials or live ledger."""
import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.controlled_probe_io import (RESPONSE_FAILURE_CODES, ResponseFailure,
    HTTPFailure, _post_once, validate_response, WindowsCredentialSecret)
from app.deepseek_bridge import synthetic_request
from app.deepseek_contract import FAKE_SECRET, ProbeError
from app.model_adapter import AdapterError, OutputJSONError, OutputSchemaError, parse_output
from test_controlled_probe import experiment, run
from test_cost_ledger import ledger_stack
from test_deepseek_bridge import response, role_capability


@pytest.fixture(autouse=True)
def no_live_io():
    with patch.object(WindowsCredentialSecret, 'resolve', side_effect=AssertionError('real key forbidden')), \
         patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', side_effect=AssertionError('vendor network forbidden')):
        yield


def mutated(fault):
    packet = response()
    if fault == 'envelope_json': return b'private raw not JSON'
    if fault == 'fingerprint_missing': packet.pop('system_fingerprint')
    if fault == 'fingerprint_null': packet['system_fingerprint'] = None
    if fault == 'fingerprint_type': packet['system_fingerprint'] = {}
    if fault == 'model': packet['model'] = 'unapproved-model'
    if fault == 'usage_missing': packet.pop('usage')
    if fault == 'usage_cache_missing': packet['usage'].pop('prompt_cache_miss_tokens')
    if fault == 'usage_bool': packet['usage']['prompt_tokens'] = True
    if fault == 'usage_negative': packet['usage']['completion_tokens'] = -1
    if fault == 'usage_total': packet['usage']['total_tokens'] += 1
    if fault == 'usage_cache': packet['usage']['prompt_cache_miss_tokens'] += 1
    if fault == 'usage_cap': packet['usage'].update(completion_tokens=257, total_tokens=357)
    if fault == 'usage_details_null': packet['usage']['completion_tokens_details'] = None
    if fault == 'usage_cached_details_type': packet['usage']['prompt_tokens_details'] = []
    if fault == 'reasoning': packet['usage']['completion_tokens_details']['reasoning_tokens'] = 1
    if fault == 'length': packet['choices'][0]['finish_reason'] = 'length'
    if fault == 'finish_missing': packet['choices'][0].pop('finish_reason')
    if fault == 'finish_type': packet['choices'][0]['finish_reason'] = None
    if fault == 'refusal': packet['choices'][0]['message']['refusal'] = 'private refusal'
    if fault == 'filter': packet['choices'][0]['finish_reason'] = 'content_filter'
    if fault == 'mode': packet['choices'][0]['message']['tool_calls'] = [{'private': 'tool'}]
    message = packet['choices'][0]['message']
    if fault == 'output_json': message['content'] = 'private malformed JSON'
    if fault == 'output_schema': message['content'] = '{}'
    if fault in ('fact', 'offset', 'self_confirm', 'preview'):
        value = json.loads(message['content'])
        if fault == 'fact': value['candidates'][0]['citation']['quote'] = '我优化了性能百分之九十。'
        if fault == 'offset': value['candidates'][0]['citation']['start'] += 1
        if fault == 'self_confirm': value['candidates'][0]['status'] = 'user_confirmed'
        if fault == 'preview':
            tid = value['candidates'][0]['citation']['turn_id']
            value.update(stop=False, stop_reason=None, questions=[dict(
                text='请核对 Bearer PUBLIC_FAKE_VALUE', purpose='detail', source_turn_ids=[tid])])
        message['content'] = json.dumps(value)
    return json.dumps(packet).encode('utf-8')


FAULTS = [
    ('envelope_json', 'controlled_envelope_invalid'),
    ('fingerprint_missing', 'controlled_envelope_invalid'),
    ('fingerprint_null', 'controlled_envelope_invalid'),
    ('fingerprint_type', 'controlled_envelope_invalid'),
    ('model', 'controlled_model_mismatch'),
    *((name, 'controlled_usage_invalid') for name in (
        'usage_missing', 'usage_cache_missing', 'usage_bool', 'usage_negative',
        'usage_total', 'usage_cache', 'usage_cap', 'usage_details_null',
        'usage_cached_details_type', 'reasoning')),
    ('length', 'controlled_output_truncated'),
    ('refusal', 'controlled_output_refused'),
    ('filter', 'controlled_output_refused'),
    ('mode', 'controlled_output_mode_invalid'),
    ('output_json', 'controlled_output_json_invalid'),
    ('output_schema', 'controlled_output_schema_invalid'),
    ('fact', 'controlled_facts_invalid'),
    ('offset', 'controlled_facts_invalid'),
    ('self_confirm', 'controlled_output_schema_invalid'),
    ('preview', 'controlled_preview_invalid'),
    ('finish_missing', 'controlled_envelope_invalid'),
    ('finish_type', 'controlled_envelope_invalid'),
]


@pytest.mark.parametrize('fault,code', FAULTS)
def test_validation_phase_is_fixed_and_does_not_leak(fault, code, caplog):
    with caplog.at_level(logging.DEBUG), pytest.raises(ResponseFailure) as error:
        validate_response(mutated(fault), synthetic_request().body, secret=FAKE_SECRET)
    assert error.value.code == code and error.value.status == 200
    assert str(error.value) == code and code in RESPONSE_FAILURE_CODES
    assert not caplog.text
    assert FAKE_SECRET not in repr(error.value) and 'private' not in repr(error.value)


@pytest.mark.parametrize('optional_details', [True, False])
def test_valid_packet_uses_actual_usage_not_offline_estimate(optional_details):
    packet = response()
    packet['usage'].update(prompt_tokens=624, completion_tokens=71,
        total_tokens=695, prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=624)
    if optional_details:
        packet['usage']['prompt_tokens_details'] = {'cached_tokens': 0}
    else:
        packet['usage'].pop('prompt_tokens_details')
        packet['usage'].pop('completion_tokens_details')
    diagnostic, preview = validate_response(json.dumps(packet).encode(), synthetic_request().body)
    assert diagnostic['usage']['total_tokens'] == 695 and diagnostic['validated'] is True
    assert preview['candidates'][0]['citation']['quote'] == '我实现了本地筛选。'
    # 71 tokens alone does not imply truncation: a valid stop response is accepted.


@pytest.mark.parametrize('content,error', [('{', OutputJSONError), ('{"a":1,"a":2}', OutputJSONError),
    ('```json\n{}\n```', OutputJSONError), ('{}', OutputSchemaError), ('[]', OutputSchemaError)])
def test_shared_parser_preserves_legacy_error_contract(content, error):
    with pytest.raises(error, match='^output_invalid$') as failure:
        parse_output(content)
    assert isinstance(failure.value, AdapterError)


def test_model_text_cannot_select_diagnostic_code():
    packet = response()
    packet['choices'][0]['message']['content'] = json.dumps({'safe_code': 'controlled_validated'})
    with pytest.raises(ResponseFailure, match='^controlled_output_schema_invalid$'):
        validate_response(json.dumps(packet).encode(), synthetic_request().body)
    with pytest.raises(ProbeError, match='^controlled_response_invalid$'):
        ResponseFailure('provider-controlled-free-text')


@pytest.mark.parametrize('fault,code', [FAULTS[i] for i in (0, 4, 9, 15, 19, 20, 21, 24)])
def test_200_rejection_persists_fixed_code_and_preserves_budget(experiment, fault, code, caplog):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, content=mutated(fault))
    with caplog.at_level(logging.DEBUG):
        result = run(experiment, handler)
    assert result['state'] == 'unknown' and result['frozen'] is True
    assert result['held_cny'] == '0.100000' and result['spent_cny'] == '0.000000'
    assert result['actual_cny'] is None and result.get('validated_preview') is None
    assert result['diagnostic'] == dict(http_status=200, validated=False, safe_code=code)
    assert FAKE_SECRET not in json.dumps(result) + caplog.text
    assert 'private' not in json.dumps(result) + caplog.text
    with pytest.raises(ProbeError, match='controlled_already_attempted'):
        run(experiment, handler)
    assert calls == [1]


class BrokenBody(httpx.AsyncByteStream):
    def __init__(self, fault): self.fault = fault
    async def __aiter__(self):
        yield b'{'
        if self.fault == 'timeout': raise httpx.ReadTimeout('private exception')
        raise httpx.ReadError('private exception')


@pytest.mark.parametrize('fault,code', [('timeout', 'controlled_timeout'), ('disconnect', 'controlled_network_unknown')])
def test_headers_observed_before_stream_failure_keep_200(fault, code):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, stream=BrokenBody(fault))
    with pytest.raises(HTTPFailure) as error:
        asyncio.run(_post_once(synthetic_request().body, FAKE_SECRET, mock=httpx.MockTransport(handler)))
    assert error.value.status == 200 and error.value.code == code and calls == [1]
    assert 'private' not in str(error.value)


def test_migration_extends_only_whitelist_preserving_function_acl_and_ledger(experiment):
    _, control, factory, schema, p = experiment
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with factory.kw['bind'].connect() as connection:
        connection.execute(text(f'SET search_path TO "{schema}"')); connection.commit()
        cfg.attributes['connection'] = connection
        before = connection.execute(text('SELECT * FROM controlled_probe')).one()
        pool = connection.execute(text('SELECT * FROM paid_funding')).one()
        fn = '''SELECT p.oid,p.proowner,p.proacl,p.prosecdef,p.proconfig,pg_get_functiondef(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=current_schema() AND p.proname='controlled_runtime' '''
        newest = connection.execute(text(fn)).one(); connection.commit()
        command.downgrade(cfg, '0009_controlled_probe'); connection.commit()
        old = connection.execute(text(fn)).one(); connection.commit()
        command.upgrade(cfg, 'head'); connection.commit()
        restored = connection.execute(text(fn)).one()
        assert restored == newest
        assert newest[:5] == old[:5]  # owner, OID, runtime grants, SECURITY DEFINER and search_path
        assert connection.execute(text('SELECT * FROM controlled_probe')).one() == before
        assert connection.execute(text('SELECT * FROM paid_funding')).one() == pool
        old_definition = old[5]
        for code in sorted(RESPONSE_FAILURE_CODES):
            assert code in restored[5] and code not in old_definition
        addition = ','.join("'" + code + "'" for code in (
            'controlled_envelope_invalid', 'controlled_model_mismatch', 'controlled_usage_invalid',
            'controlled_output_json_invalid', 'controlled_output_schema_invalid', 'controlled_facts_invalid',
            'controlled_preview_invalid', 'controlled_output_truncated', 'controlled_output_refused',
            'controlled_output_mode_invalid')) + ','
        assert restored[5].replace(addition, '', 1) == old_definition
    control.action(p, 'reserve'); control.action(p, 'permit')
    # Every new code is accepted, while free text is still rejected. Transaction
    # rollback restores sent for each check, so there is still only one permit.
    for code in RESPONSE_FAILURE_CODES:
        with control.engine.connect() as connection:
            connection.execute(text(f'SELECT "{schema}".controlled_runtime(:l,:p,\'unknown\',CAST(:v AS jsonb))'),
                dict(l=control.ledger_id, p=p.sha(), v=json.dumps(dict(http_status=200, validated=False, safe_code=code))))
            connection.rollback()
    control.action(p, 'unknown', dict(http_status=200, validated=False, safe_code='controlled_usage_invalid'))
    with factory.kw['bind'].connect() as connection:
        connection.execute(text(f'SET search_path TO "{schema}"')); connection.commit()
        cfg.attributes['connection'] = connection
        with pytest.raises(RuntimeError, match='controlled_diagnostic_downgrade_blocked'):
            command.downgrade(cfg, '0009_controlled_probe')
        connection.rollback()
    assert control.read()['state'] == 'unknown' and control.report()['frozen'] is True


def test_reconciled_fixture_cannot_be_reopened_by_new_diagnostics(experiment):
    admin, control, _, _, p = experiment
    admin.close_unsent('d' * 64)
    before = control.read()
    with pytest.raises(DBAPIError, match='transition_invalid'):
        control.action(p, 'unknown', dict(http_status=200, validated=False, safe_code='controlled_facts_invalid'))
    assert control.read()['state'] == before['state'] == 'reconciled'
    with pytest.raises(ProbeError, match='controlled_already_attempted'):
        run(experiment, lambda request: pytest.fail('reconciled cannot dispatch'))
    for action in ('reserve', 'permit', 'dispatch'):
        try: control.action(p, action)
        except DBAPIError: pass
        assert control.read()['state'] == 'reconciled'
    with pytest.raises(ProbeError): admin.authorize(p)
