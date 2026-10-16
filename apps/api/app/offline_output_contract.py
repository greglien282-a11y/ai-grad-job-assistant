"""Fixed synthetic offline audit only. Not a Provider, transport or approval.

Historical Adapter/request bytes stay unchanged. The new prompt has its own
version and SHA and deliberately cannot pass the real probe's byte allowlist.
"""
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import zipfile

from app.cost_ledger import canonical
from app.controlled_probe_io import ResponseFailure, validate_response
from app.deepseek_bridge import synthetic_request
from app.deepseek_contract import MODEL, VERSION
from app.mining_context import MiningContext
from app.mining_validation import validate_context_v2
from app.model_adapter import parse_output

ROOT = Path(__file__).resolve().parents[3]
HISTORICAL_SHA = '5cc2def4f875e43760e799678a43c1f2d2072dd4245eaf54457dfe78ee0b373e'
TURN = '1144cfca-8c37-5d49-bc83-8f4d45bc266f'
TEXT = '我实现了本地筛选。'
PROMPT_VERSION = 's03b-prompt-v2-offline'


@dataclass(frozen=True, repr=False)
class OfflinePrompt:
    version: str
    body: bytes = field(repr=False)
    @property
    def sha(self): return hashlib.sha256(self.body).hexdigest()


def historical_body():
    body = synthetic_request().body
    if hashlib.sha256(body).hexdigest() != HISTORICAL_SHA:
        raise ValueError('offline_historical_request_changed')
    return body


def prompt_v2():
    request = json.loads(historical_body())
    context = json.loads(request['messages'][1]['content'])
    if [(t['turn_id'], t['content']) for t in context['user_turns']] != [(TURN, TEXT)]:
        raise ValueError('offline_fixed_input_required')
    prompt = (ROOT / 'docs/evaluation/s03b-prompt-v2.txt').read_text(encoding='utf-8')
    wire = json.loads((ROOT / 'docs/evaluation/provider-wire-output.schema.json').read_text(encoding='utf-8'))
    request['messages'][0]['content'] = prompt.rstrip() + '\n输出 Schema：\n' + canonical(wire)
    return OfflinePrompt(PROMPT_VERSION, canonical(request).encode('utf-8'))


def question(text='你本人如何实现本地筛选？', purpose='detail'):
    return dict(text=text, purpose=purpose, source_turn_ids=[TURN])


def output(text=TEXT, *, questions=(), stop=True, reason='no_new_information', candidate=True):
    return dict(schema_version=2,
        candidates=[dict(citation=dict(turn_id=TURN, quote=text, start=0, end=len(text)))] if candidate else [],
        questions=list(questions), stop=stop, stop_reason=reason)


def envelope(content, *, details=True, model=MODEL, cached=0):
    # Invented internally consistent usage, not actual tokenizer/vendor counts.
    usage = dict(prompt_tokens=1000, completion_tokens=200, total_tokens=1200,
                 prompt_cache_hit_tokens=cached, prompt_cache_miss_tokens=1000-cached)
    if details:
        usage.update(prompt_tokens_details=dict(cached_tokens=cached), completion_tokens_details=dict(reasoning_tokens=0))
    return dict(id='offline-contract-fixture', object='chat.completion', created=1792110000,
        model=model, system_fingerprint='offline-not-version-proof',
        choices=[dict(index=0, finish_reason='stop', message=dict(role='assistant', content=content))], usage=usage)


@dataclass(frozen=True)
class Case:
    name: str
    condition: str
    expected_code: str
    request_body: bytes = field(repr=False)
    response_body: bytes = field(repr=False)
    source_kind: str = 'fixed_s03b'


def cases():
    result = []
    base = historical_body()
    def add(name, condition, expected='controlled_validated', *, value=None, packet=None,
            content=None, source=TEXT, source_kind='fixed_s03b'):
        request = base
        if source != TEXT:
            payload = json.loads(base)
            ctx = json.loads(payload['messages'][1]['content'])
            ctx['user_turns'][0]['content'] = source
            payload['messages'][1]['content'] = canonical(ctx)
            request = canonical(payload).encode('utf-8')
        if packet is None:
            packet = envelope(content if content is not None else canonical(value if value is not None else output()))
        result.append(Case(name, condition, expected, request, canonical(packet).encode('utf-8'), source_kind))

    add('exact_stop', '完整原句、正确UUID、[0,9)、合法停止')
    continuing = output(questions=[question()], stop=False, reason=None)
    add('exact_continue', '一个完整事实与一个合法追问', value=continuing)
    add('empty_candidates_continue', '没有候选事实但一个合法追问',
        value=output(candidate=False, questions=[question()], stop=False, reason=None))
    add('empty_candidates_stop', '无新信息时空候选与合法停止', value=output(candidate=False))
    add('two_questions', '一个事实与两个不重复且有来源的追问', value=output(
        questions=[question(), question('这段筛选逻辑由你独立完成吗？', 'contribution')], stop=False, reason=None))
    add('version_alias', '允许的公开版本标识', packet=envelope(canonical(output()), model=VERSION))
    add('cache_hit', '缓存命中与未命中之和正确', packet=envelope(canonical(output()), cached=200))
    add('optional_usage_absent', '省略非必需usage details', packet=envelope(canonical(output()), details=False))
    for key in ('schema_version', 'candidates', 'questions', 'stop', 'stop_reason'):
        v=output();v.pop(key)
        add('missing_'+key, 'JSON合法但缺少 '+key, 'controlled_output_schema_invalid', value=v)
    for key, val in [('extra', 'unrequested'), ('stop', 'true'), ('candidates', {}), ('schema_version', '2')]:
        v=output();v[key]=val
        add('wrong_'+key, '额外字段或错误类型 '+key, 'controlled_output_schema_invalid', value=v)
    for name, changes, code in [
        ('uuid_format', {'turn_id':'not-a-uuid'}, 'controlled_output_schema_invalid'),
        ('uuid_unknown', {'turn_id':'22222222-2222-4222-8222-222222222222'}, 'controlled_facts_invalid'),
        ('start_string', {'start':'0'}, 'controlled_output_schema_invalid'),
        ('offset_bytes', {'end':len(TEXT.encode('utf-8'))}, 'controlled_facts_invalid'),
        ('offset_exclusive', {'end':8}, 'controlled_facts_invalid'),
        ('rewritten_quote', {'quote':'我开发了本地筛选。'}, 'controlled_facts_invalid')]:
        v=output();v['candidates'][0]['citation'].update(changes)
        add(name, '引用变体 '+name, code, value=v)
    v=output();v['candidates'][0]['status']='user_confirmed'
    add('self_confirm', '模型添加事实确认状态', 'controlled_output_schema_invalid', value=v)
    add('unsupported_number', '问题加入用户没有给出的百分比', 'controlled_facts_invalid',
        value=output(questions=[question('性能提升50%了吗？')], stop=False, reason=None))
    add('empty_content', 'HTTP content为空字符串', 'controlled_output_json_invalid', content='')
    add('cut_json', '半截JSON，finish仍宣称stop', 'controlled_output_json_invalid', content='{"schema_version":2,"candidates":[')
    add('fenced_json', 'JSON被Markdown包裹', 'controlled_output_json_invalid', content='```json\n'+canonical(output())+'\n```')
    for name, v in [('bad_reason', output(reason='finished')),
                    ('stop_with_questions', output(questions=[question()])),
                    ('continue_without_questions', output(stop=False, reason=None)),
                    ('continue_with_reason', output(questions=[question()], stop=False)),
                    ('stop_without_reason', output(reason=None))]:
        add(name, '停止状态约束冲突 '+name, 'controlled_output_schema_invalid', value=v)
    v=output(questions=[question(),question()],stop=False,reason=None)
    add('duplicate_question', '重复追问', 'controlled_facts_invalid', value=v)
    for name, original in [('negation', '我没有实现本地筛选。'),
                           ('team', '我们团队实现了本地筛选。'),
                           ('hypothesis', '我计划实现本地筛选。')]:
        add(name+'_promoted', '补充离线原文含'+name+'，输出却改成个人已完成成就',
            'source_guard_rejected', value=output(), source=original, source_kind='supplemental_'+name)
    add('negative_preserved', '保留完整否定事实，不视为正向贡献', 'source_guard_validated', value=output('我没有实现本地筛选。'),
        source='我没有实现本地筛选。', source_kind='supplemental_boundary')
    add('team_clarification', '团队归属不清时不提事实，仅询问个人贡献',
        'source_guard_validated',
        value=output(candidate=False, questions=[question('其中你本人完成了什么？','contribution')],stop=False,reason=None),
        source='我们团队实现了本地筛选。', source_kind='supplemental_team')
    emoji='我实现了😀筛选。'
    add('unicode_codepoint', '非BMP字符按Python code point引用', 'source_guard_validated', value=output(emoji), source=emoji, source_kind='supplemental_unicode')
    v=output(emoji);v['candidates'][0]['citation']['end']=len(emoji.encode('utf-16-le'))//2
    add('unicode_utf16', '非BMP字符错误使用UTF-16单元', 'source_guard_rejected',value=v,source=emoji,source_kind='supplemental_unicode')
    for name, original in [('team', '我们团队实现了本地筛选。'), ('hypothesis', '我计划实现本地筛选。')]:
        add(name+'_exact_unclear', '原句虽准确但团队归属或假设不满足原子事实条件',
            'source_guard_rejected', value=output(original), source=original, source_kind='supplemental_'+name)
    for name, field, val, code in [
        ('length', 'finish_reason', 'length', 'controlled_output_truncated'),
        ('bad_usage_total', 'total_tokens', 1201, 'controlled_usage_invalid'),
        ('bad_usage_type', 'completion_tokens', '200', 'controlled_usage_invalid'),
        ('fingerprint_null', 'system_fingerprint', None, 'controlled_envelope_invalid')]:
        packet=envelope(canonical(output()))
        if field=='finish_reason':packet['choices'][0][field]=val
        elif field=='system_fingerprint':packet[field]=val
        else:packet['usage'][field]=val
        add(name, 'HTTP envelope/usage变体 '+name, code, packet=packet)
    return tuple(result)


def evaluate():
    rows=[]
    for case in cases():
        scope='controlled_probe' if case.source_kind=='fixed_s03b' else 'snapshot_source_guard'
        if scope=='controlled_probe':
            try:
                diagnostic, preview=validate_response(case.response_body,case.request_body)
                actual=diagnostic['safe_code']
            except ResponseFailure as error:
                actual=error.code
        else:
            # The fixed preview intentionally rejects other source snapshots.
            # Supplemental tests exercise the generic source guard separately;
            # these local audit labels are NOT runtime HTTP diagnostic codes.
            packet=json.loads(case.response_body)
            context=MiningContext.model_validate_json(json.loads(case.request_body)['messages'][1]['content'])
            parsed=parse_output(packet['choices'][0]['message']['content'])
            try:
                validate_context_v2(context,parsed)
                actual='source_guard_validated'
            except ValueError:
                actual='source_guard_rejected'
        rows.append(dict(case=case.name, input_condition=case.condition, source_kind=case.source_kind,
            validation_scope=scope,
            code_origin='runtime_response_validator' if scope=='controlled_probe' else 'offline_snapshot_audit_label',
            full_response_validated=actual=='controlled_validated',
            expected_phase=case.expected_code.removeprefix('controlled_'), expected_code=case.expected_code,
            actual_code=actual, safely_rejected=actual not in ('controlled_validated','source_guard_validated'),
            expectation_met=actual==case.expected_code))
    draft=prompt_v2()
    return dict(mode='offline_synthetic_contract_only', historical_request_sha=HISTORICAL_SHA,
        prompt_version=draft.version, draft_request_sha=draft.sha, historical_request_changed=False,
        real_provider_requests=0, credentials_accessed=False, actual_model_quality=None,
        supplier_latency_ms=None, actual_cost_cny=None, fixture_usage_is_measured=False,
        cases=rows, all_expectations_met=all(r['expectation_met'] for r in rows))


def length_analysis(archive_path):
    """Local pinned tokenizer estimates, never supplier token/billing proof."""
    from app.controlled_probe import TOKENIZER_ARCHIVE_SHA
    from app.probe_estimate import count_json
    with open(archive_path, 'rb') as file:
        data=file.read(4_000_001)
    if len(data)>4_000_000 or hashlib.sha256(data).hexdigest()!=TOKENIZER_ARCHIVE_SHA:
        raise ValueError('offline_tokenizer_evidence_invalid')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member='deepseek_v4_tokenizer/tokenizer.json'
        if archive.getinfo(member).file_size>20_000_000:
            raise ValueError('offline_tokenizer_evidence_invalid')
        tokenizer=archive.read(member).decode('utf-8')
    samples={
        'empty_stop':output(candidate=False),
        'one_fact_stop':output(),
        'one_fact_one_question':output(questions=[question()],stop=False,reason=None),
        'one_fact_two_questions':output(questions=[question(),question('其中你本人完成了什么？','contribution')],stop=False,reason=None),
        'schema_length_boundary_not_quality':output(questions=[
            question('请说明'+('你本人实际完成的步骤和限制。'*25)),
            question('请补充'+('你本人实施筛选的过程和依据。'*25))],stop=False,reason=None),
    }
    measured={}
    for name, value in samples.items():
        compact=canonical(value).encode('utf-8')
        # Check business schema/source only. Do not invent HTTP usage that
        # pretends a long sample was actually emitted within the output cap.
        ctx=MiningContext.model_validate_json(json.loads(historical_body())['messages'][1]['content'])
        validate_context_v2(ctx,parse_output(compact.decode('utf-8')))
        measured[name]=dict(utf8_bytes=len(compact), unicode_characters=len(compact.decode('utf-8')),
            estimated_output_tokens=count_json(tokenizer,compact),
            pretty_json_estimated_tokens=count_json(tokenizer,json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')))
    return dict(status='LOCAL_ESTIMATE_NOT_VENDOR_MEASUREMENT', tokenizer_archive_sha=TOKENIZER_ARCHIVE_SHA,
        tokenizer_method='raw_JSON_add_special_tokens_not_server_framing', historical_output_cap=256,
        legacy_input_estimated_tokens=count_json(tokenizer,historical_body()),
        draft_input_estimated_tokens=count_json(tokenizer,prompt_v2().body), samples=measured,
        supplier_actual_output_tokens=None, verified_token_upper_bound=None,
        first_response_cause='NOT_DETERMINABLE_FROM_LENGTH')
