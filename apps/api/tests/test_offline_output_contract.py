"""Synthetic contract deviations, not a second provider-quality experiment."""
import asyncio
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import httpx
import pytest

from app.controlled_probe import verify_bytes
from app.controlled_probe_io import _post_once, WindowsCredentialSecret, validate_response
from app.deepseek_contract import FAKE_SECRET, ProbeError
from app.mining_context import MiningContext
from app.model_adapter import parse_output
from app.offline_output_contract import (HISTORICAL_SHA, PROMPT_VERSION, TEXT, TURN,
    ROOT, cases, envelope, evaluate, historical_body, length_analysis, output, prompt_v2)
from test_controlled_probe import experiment, run
from test_cost_ledger import ledger_stack
from test_deepseek_bridge import role_capability


@pytest.fixture(autouse=True)
def prohibit_real_io():
    with patch.object(WindowsCredentialSecret, 'resolve', side_effect=AssertionError('no real key')), \
         patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', side_effect=AssertionError('no real network')):
        yield


@pytest.fixture(scope='module')
def matrix_report():
    return evaluate()


@pytest.mark.parametrize('case',cases(),ids=lambda case:case.name)
def test_each_synthetic_deviation_matches_its_declared_boundary(case,matrix_report):
    row=next(row for row in matrix_report['cases'] if row['case']==case.name)
    assert row['actual_code']==case.expected_code
    assert row['expectation_met']
    assert row['safely_rejected']==(case.expected_code not in ('controlled_validated','source_guard_validated'))
    assert row['validation_scope']==('controlled_probe' if case.source_kind=='fixed_s03b' else 'snapshot_source_guard')


def test_fixed_s03b_has_exact_codepoint_positions_and_uuid():
    assert len(TEXT)==9 and len(TEXT.encode('utf-8'))==27
    ctx=MiningContext.model_validate_json(json.loads(historical_body())['messages'][1]['content'])
    assert str(ctx.input_turn_id)==TURN
    value=parse_output(json.dumps(output(),ensure_ascii=False))
    citation=value.candidates[0].citation
    assert citation.start==0 and citation.end==9 and citation.quote==TEXT
    assert str(citation.turn_id)==TURN==str(ctx.user_turns[0].turn_id)


def test_new_prompt_is_versioned_and_legacy_bytes_are_unchanged():
    old=historical_body()
    draft=prompt_v2()
    assert draft.version==PROMPT_VERSION and draft.sha!=HISTORICAL_SHA
    original=json.loads(old);changed=json.loads(draft.body)
    assert changed['messages'][1]==original['messages'][1]
    changed['messages'][0]=original['messages'][0]
    assert changed==original  # Only system text changed, including no cap/model changes.
    assert hashlib.sha256(historical_body()).hexdigest()==HISTORICAL_SHA
    verify_bytes(old)
    with pytest.raises(ProbeError,match='controlled_request_changed'):verify_bytes(draft.body)


@pytest.mark.parametrize('example_index',[0,1])
def test_both_complete_prompt_examples_pass_existing_chain(example_index):
    prompt=(ROOT/'docs/evaluation/s03b-prompt-v2.txt').read_text(encoding='utf-8')
    examples=[json.loads(line) for line in prompt.splitlines() if line.startswith('{')]
    assert len(examples)==2
    diagnostic,preview=validate_response(json.dumps(envelope(json.dumps(examples[example_index]))).encode(),prompt_v2().body)
    assert diagnostic['validated'] and preview==examples[example_index]


def test_new_prompt_and_supplemental_inputs_cannot_enter_existing_http_gate():
    forbidden=[]
    def handler(request):forbidden.append(1);pytest.fail('unapproved bytes must not reach Mock or real HTTP')
    bodies=[prompt_v2().body]+[case.request_body for case in cases() if case.source_kind!='fixed_s03b']
    for body in bodies:
        with pytest.raises(ProbeError,match='controlled_request_changed'):
            asyncio.run(_post_once(body,FAKE_SECRET,mock=httpx.MockTransport(handler)))
    assert forbidden==[]


@pytest.mark.parametrize('name',['exact_continue','empty_candidates_continue','missing_stop_reason','rewritten_quote','stop_with_questions'])
def test_original_probe_http_and_postgres_still_enforce_contract(experiment,name):
    case=next(c for c in cases() if c.name==name)
    calls=[]
    def handler(request):
        assert request.content==historical_body()
        calls.append(1)
        return httpx.Response(200,content=case.response_body)
    result=run(experiment,handler)
    valid=case.expected_code=='controlled_validated'
    assert result['state']==('response_received' if valid else 'unknown')
    assert result['diagnostic']['safe_code']==case.expected_code
    assert result['diagnostic']['http_status']==200
    assert result['held_cny']=='0.100000' and result['frozen'] is True
    assert result['actual_cny'] is None
    if valid:
        preview=result['validated_preview']
        assert 'user_confirmed' not in json.dumps(preview)
    else:assert result.get('validated_preview') is None
    with pytest.raises(ProbeError,match='already_attempted'):run(experiment,handler)
    assert calls==[1]


def test_report_reproduction_and_unknown_real_metrics():
    tracked=json.loads((ROOT/'docs/evaluation/s03b-offline-contract-report.json').read_text(encoding='utf-8'))
    current=evaluate()
    tracked.pop('length_analysis')
    assert tracked==current
    assert current['all_expectations_met'] and current['real_provider_requests']==0
    assert current['actual_model_quality'] is None and current['actual_cost_cny'] is None
    assert current['supplier_latency_ms'] is None and current['fixture_usage_is_measured'] is False


def test_pure_matrix_cannot_read_private_files_credentials_db_or_network():
    original=Path.read_text
    allowed={'m12c2-synthetic-cases.json','provider-wire-output.schema.json',
             'm12c2-profile-drafts.json','s03b-prompt-v2.txt'}
    def public_text(path,*args,**kwargs):
        assert path.resolve().parent==(ROOT/'docs/evaluation').resolve()
        assert path.name in allowed
        return original(path,*args,**kwargs)
    with patch.object(Path,'read_text',public_text), \
         patch('psycopg.connect',side_effect=AssertionError('DB forbidden')), \
         patch('sqlalchemy.create_engine',side_effect=AssertionError('engine forbidden')), \
         patch.object(ctypes,'WinDLL',side_effect=AssertionError('native credential API forbidden'),create=True), \
         patch('socket.create_connection',side_effect=AssertionError('socket forbidden')), \
         patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')):
        assert evaluate()['all_expectations_met']


def test_length_report_is_explicitly_not_billing_or_first_failure_proof():
    record=json.loads((ROOT/'docs/evaluation/s03b-offline-contract-report.json').read_text(encoding='utf-8'))['length_analysis']
    assert record['status']=='LOCAL_ESTIMATE_NOT_VENDOR_MEASUREMENT'
    assert record['legacy_input_estimated_tokens']==812
    assert record['verified_token_upper_bound'] is None and record['supplier_actual_output_tokens'] is None
    assert record['first_response_cause']=='NOT_DETERMINABLE_FROM_LENGTH'
    assert record['samples']['schema_length_boundary_not_quality']['estimated_output_tokens']>256


def test_missing_local_tokenizer_is_not_downloaded(tmp_path):
    with patch('socket.create_connection',side_effect=AssertionError('no download')):
        with pytest.raises(FileNotFoundError):length_analysis(tmp_path/'not-present.zip')
        bad=tmp_path/'bad.zip';bad.write_bytes(b'not the pinned archive')
        with pytest.raises(ValueError,match='offline_tokenizer_evidence_invalid'):length_analysis(bad)


def test_cli_runs_without_database_credentials_or_tokenizer(tmp_path):
    path=tmp_path/'synthetic-report.json'
    result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/check_s03b_output_contract.py'),
        '--output',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout
    record=json.loads(path.read_text(encoding='utf-8'))
    assert record['length_analysis']['status']=='TOKENIZER_NOT_PROVIDED'
    assert record['real_provider_requests']==0 and record['all_expectations_met']
    # No overwriting earlier audit artifacts even if someone repeats the CLI.
    again=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/check_s03b_output_contract.py'),
        '--output',str(path)],capture_output=True,text=True)
    assert again.returncode==2 and 'Traceback' not in again.stderr
