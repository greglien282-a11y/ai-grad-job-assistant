"""c3b: synthetic PostgreSQL, real SELECT-only LOGIN, never an HTTP writer."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app import facts
from app.models import ConversationTurn, ExperienceSession
from app.typed_source_preflight import CONTRACT, preflight
from test_http_api import api
from test_maintenance_api import service, seed as legacy_seed, post
from test_append_api import append_service, legacy_rejected_history
from test_experience_read import reader, synthetic, corrupt
from test_legacy_upgrade_handoff import digest
from test_typed_semantic_spike import candidate


def revision(s,b):
    with s.admin() as db:b.revision=db.get(ExperienceSession,b.sid).context_revision


def seed(s,**kwargs):
    b=legacy_seed(s,**kwargs);revision(s,b)
    return b


def saved(s,b,raw,role='user'):
    """Owner arranges a saved Turn outside the runtime request."""
    with s.admin.begin() as db:
        turn=ConversationTurn(session_id=b.sid,role=role,content=raw)
        db.add(turn);db.flush()
        tid=turn.id
    revision(s,b)
    return tid


def request(b,raw='我整理了27条缺失记录。',kind='personal_action',stage='completed',quotes=None):
    return dict(preflight_contract=CONTRACT,synthetic=True,context_revision=b.revision,
                items=candidate(raw,kind,stage,quotes=quotes)['items'])


def check(s,b,tid,payload,**overrides):
    """Every normal/denied request proves all business tables are unchanged."""
    before=digest(s.admin);copy=deepcopy(payload)
    args=dict(session_id=b.sid,project_id=b.pid,turn_id=tid,token=b.token,request=payload)
    args.update(overrides)
    result=preflight(s.reader,**args)
    assert digest(s.admin)==before and payload==copy
    assert result.truth_verified is False and result.persistence_authorized is False
    assert result.transaction_review_required and result.semantic_independence=='unproven'
    output=json.dumps(asdict(result),ensure_ascii=False)
    assert b.token not in output and '我' not in output
    assert 'operation_id' not in output and 'accepted_items' not in output
    return result


@pytest.mark.parametrize('raw,kind,stage',[
    ('我整理了27条缺失记录。','personal_action','completed'),
    ('我正在部署服务。','personal_action','in_progress'),
    ('我计划部署服务。','plan','planned'),
    ('我正在准备部署服务。','plan','in_progress'),
    ('我们部署了服务。','background','not_applicable'),
    ('我没有部署服务。','boundary','not_applicable'),
    ('我制作了🧪原型图。','personal_action','completed'),
    ('我制作了e\u0301原型图。','personal_action','completed'),
    ('我制作了👩‍💻原型图。','personal_action','completed'),
    (' \r\n我制作了é原型图。\r\n我部署了服务。\t','personal_action','completed'),
])
def test_saved_source_exact_codepoints_and_unchanged_language(reader,raw,kind,stage):
    s=reader;b=seed(s);tid=saved(s,b,raw)
    quotes=[q.strip(' \t\r\n')+'。' for q in raw.split('。') if q.strip(' \t\r\n')]
    r=check(s,b,tid,request(b,raw,kind,stage,quotes))
    assert r.status=='candidate_only' and r.source_binding=='bound'
    assert r.language_status=='eligible_candidate' and r.history_status=='independence_unproven'
    assert r.history_flags==() and r.context_revision==b.revision
    with pytest.raises(FrozenInstanceError):r.truth_verified=True


@pytest.mark.parametrize('fault',['27_to_28','utf16_end','nfc_quote','negation_truncated',
    'plan_truncated','team_truncated','uncertain_truncated','partial_sentence','overlap','reordered','omitted'])
def test_saved_text_cannot_be_replaced_or_selectively_quoted(reader,fault):
    s=reader;b=seed(s);raw='我整理了27条缺失记录。';p=request(b,raw)
    if fault=='27_to_28':p=request(b,raw.replace('27','28'))
    elif fault=='utf16_end':
        raw='我制作了👩‍💻原型图。';p=request(b,raw);p['items'][0]['end']=len(raw.encode('utf-16-le'))//2
    elif fault=='nfc_quote':raw='我制作了e\u0301原型图。';p=request(b,'我制作了é原型图。')
    elif fault.endswith('truncated'):
        raw={'negation_truncated':'我没有部署服务。','plan_truncated':'我计划部署服务。',
             'team_truncated':'我们部署了服务。','uncertain_truncated':'我可能部署过服务。'}[fault]
        p=request(b,raw);p['items'][0].update(start=1,quote=raw[1:])
    elif fault=='partial_sentence':p['items'][0].update(end=len(raw)-1,quote=raw[:-1])
    else:
        raw='我部署了服务。\r\n我编写了脚本。';p=request(b,raw,quotes=raw.split('\r\n'))
        if fault=='overlap':p['items'].append(deepcopy(p['items'][0]))
        elif fault=='reordered':p['items'].reverse()
        else:p['items'].pop()
    tid=saved(s,b,raw);p['context_revision']=b.revision
    r=check(s,b,tid,p)
    assert r.status=='candidate_rejected' and r.source_binding=='not_bound'
    assert r.language_status=='rejected'


@pytest.mark.parametrize('raw,expected',[
    ('我计划部署服务。','requires_clarification'),('我正在部署服务。','requires_clarification'),
    ('我们部署了服务。','requires_clarification'),('我没有部署服务。','requires_clarification'),
    ('如果我部署服务。','requires_clarification'),('我可能部署过服务。','requires_clarification'),
    ('我编写并测试了系统。','requires_clarification'),('我整理了27条缺失记录，提升率20%。','requires_clarification'),
    ('我负责每周更新名单。','unsupported'),
])
def test_complete_saved_quote_does_not_prove_declared_semantics(reader,raw,expected):
    s=reader;b=seed(s);r=check(s,b,saved(s,b,raw),request(b,raw))
    assert r.source_binding=='bound' and r.language_status==expected
    assert r.status=='candidate_rejected'


@pytest.mark.parametrize('fault',['foreign_session','foreign_project','foreign_turn','missing_turn','assistant'])
def test_source_ownership_and_user_role(reader,fault):
    s=reader;b=seed(s);foreign=seed(s);raw='我部署了服务。';tid=saved(s,b,raw)
    overrides={}
    if fault=='foreign_session':overrides.update(session_id=foreign.sid)
    elif fault=='foreign_project':overrides.update(project_id=foreign.pid)
    elif fault=='foreign_turn':tid=foreign.tid
    elif fault=='missing_turn':tid=uuid4()
    else:tid=saved(s,b,raw,'assistant')
    r=check(s,b,tid,request(b,raw),**overrides)
    assert r.status==('authorization_denied' if fault=='foreign_session' else 'source_rejected')
    assert r.history_flags==() and r.language_status=='not_checked'


@pytest.mark.parametrize('fault',['raw_text','force','history_safe','ignore_duplicate','version','revision',
    'bool_revision','synthetic','invalid_items'])
def test_strict_preflight_contract_and_no_bypass(reader,fault):
    s=reader;b=seed(s);raw='我部署了服务。';tid=saved(s,b,raw);p=request(b,raw)
    if fault in ('raw_text','force','history_safe','ignore_duplicate'):p[fault]='forged'
    elif fault=='version':p['preflight_contract']='typed-source-preflight-v99'
    elif fault=='revision':p['context_revision']+=1
    elif fault=='bool_revision':p['context_revision']=True
    elif fault=='synthetic':p['synthetic']=False
    else:p['items']=None
    r=check(s,b,tid,p)
    assert r.status in ('rejected','version_rejected','candidate_rejected')
    # Even unsupported versions do not disclose anything to a foreign bearer.
    assert check(s,b,tid,p,token='foreign').status=='authorization_denied'


@pytest.mark.parametrize('history',['current','pending','confirmed'])
@pytest.mark.parametrize('raw',['我测试了三个导出按钮。','我验证了3个导出按钮。','我部署了服务。'])
def test_rejected_current_history_and_unrelated_false_positive(reader,history,raw):
    s=reader;b=seed(s,status='rejected' if history=='current' else 'pending')
    if history!='current':legacy_rejected_history(s,b,'pending' if history=='pending' else 'user_confirmed','both')
    tid=saved(s,b,raw);r=check(s,b,tid,request(b,raw))
    assert r.source_binding=='bound' and r.language_status=='eligible_candidate'
    assert r.status=='requires_review' and 'historical_rejected' in r.history_flags
    assert ('current_rejected' in r.history_flags)==(history=='current')
    assert 'exact_text_reuse' not in r.history_flags and 'original_source_reuse' not in r.history_flags
    # New Turn / changed digits / synonym is never an independence proof.


def test_original_source_and_exact_text_are_distinct_from_semantic_independence(reader):
    s=reader;b=seed(s);raw='我测试了3个导出按钮。'
    r=check(s,b,b.tid,request(b,raw))
    assert set(r.history_flags)=={'exact_text_reuse','original_source_reuse','historical_source_reuse'}
    new=check(s,b,saved(s,b,raw),request(b,raw))
    assert new.history_flags==('exact_text_reuse',)
    alternative='我测试了三个导出按钮。'
    unresolved=check(s,b,saved(s,b,alternative),request(b,alternative))
    assert unresolved.status=='candidate_only' and unresolved.semantic_independence=='unproven'


def test_maintenance_sources_and_old_versions_remain_visible(reader):
    s=reader;b=seed(s);r=post(s,b);assert r.status_code==201,r.text
    with s.admin() as db:
        b.revision=db.get(ExperienceSession,b.sid).context_revision
        tid=db.scalar(text('SELECT input_turn_id FROM conversation_operations WHERE session_id=:sid'),{'sid':b.sid})
    raw='纠正上一条。我测试了2个导出按钮。'
    r=check(s,b,tid,request(b,raw,quotes=['纠正上一条。','我测试了2个导出按钮。']))
    assert 'historical_source_reuse' in r.history_flags and 'exact_text_reuse' in r.history_flags
    assert 'original_source_reuse' not in r.history_flags
    original=check(s,b,saved(s,b,'我测试了3个导出按钮。'),request(b,'我测试了3个导出按钮。'))
    assert original.status=='requires_review' and original.history_flags==('exact_text_reuse',)


@pytest.mark.parametrize('fault',['permission','auth_permission','schema','missing_column','source','snapshot','history_gap','labels','co_version','dml','owner'])
def test_real_permission_schema_history_fail_closed_auth_first(reader,fault):
    s=reader;b=seed(s);raw='我部署了服务。';tid=saved(s,b,raw);fid=synthetic(s,b);revision(s,b)
    if fault in ('permission','auth_permission','schema','missing_column','dml'):
        with s.admin.begin() as db:
            if fault in ('permission','auth_permission'):
                db.execute(text(f'REVOKE SELECT ON {"experience_sessions" if fault=="auth_permission" else "fact_sources"} FROM "{s.read_role}"'))
            elif fault=='schema':db.execute(text("COMMENT ON TABLE experience_facts IS 'pathwise-classification-schema-v99'"))
            elif fault=='missing_column':db.execute(text('ALTER TABLE experience_facts RENAME COLUMN fact_kind TO missing_kind'))
            else:db.execute(text(f'GRANT UPDATE(statement) ON experience_facts TO "{s.read_role}"'))
    elif fault=='source':corrupt(s,'fact_sources','DELETE FROM fact_sources WHERE fact_id=:id',{'id':fid})
    elif fault=='snapshot':corrupt(s,'fact_changes',"UPDATE fact_changes SET after=after-'memory_state' WHERE fact_id=:id",{'id':fid})
    elif fault=='history_gap':corrupt(s,'fact_changes',"DELETE FROM fact_changes WHERE fact_id=:id AND action<>'created'",{'id':fid})
    elif fault=='labels':corrupt(s,'experience_facts',"UPDATE experience_facts SET fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0' WHERE id=:id",{'id':fid})
    elif fault=='co_version':
        # A valid CO is constructed in a separate legacy session before fault injection.
        other=seed(s);assert post(s,other).status_code==201
        before=digest(s.admin)
        with pytest.raises(IntegrityError) as exc:
            corrupt(s,'conversation_operations','UPDATE conversation_operations SET contract_version=99 WHERE session_id=:sid',{'sid':other.sid})
        assert exc.value.orig.diag.constraint_name=='ck_co_identity'
        assert digest(s.admin)==before
        p=request(b,raw);p['preflight_contract']='typed-source-preflight-v99'
        assert check(s,b,tid,p).status=='version_rejected'
        return
    elif fault=='owner':
        before=digest(s.admin)
        r=preflight(s.admin,session_id=b.sid,project_id=b.pid,turn_id=tid,token=b.token,request=request(b,raw))
        assert r.status=='permission_rejected' and digest(s.admin)==before
        return
    try:
        r=check(s,b,tid,request(b,raw))
        assert r.status in ('integrity_unavailable','permission_rejected')
        assert r.source_binding=='not_checked' and r.history_flags==()
        if fault!='auth_permission':
            assert check(s,b,tid,request(b,raw),token='foreign').status=='authorization_denied'
    finally:
        if fault=='missing_column':
            with s.admin.begin() as db:db.execute(text('ALTER TABLE experience_facts RENAME COLUMN missing_kind TO fact_kind'))


def test_real_two_connection_snapshot_and_next_request_revision_conflict(reader):
    s=reader;b=seed(s);raw='我部署了服务。';tid=saved(s,b,raw);p=request(b,raw);fired=False
    def writer():
        with s.admin.begin() as db:
            facts.change_fact(db,b.fid,b.token,status='rejected',expected_version=1)
    def interleave(conn,cursor,sql,params,context,many):
        nonlocal fired
        if not fired and 'FROM experience_facts' in sql:
            fired=True
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(writer).result(timeout=10)
    event.listen(s.read_engine,'before_cursor_execute',interleave)
    try:r=preflight(s.reader,session_id=b.sid,project_id=b.pid,turn_id=tid,token=b.token,request=p)
    finally:event.remove(s.read_engine,'before_cursor_execute',interleave)
    assert fired and r.status=='candidate_only' and r.context_revision==b.revision and r.history_flags==()
    assert not r.truth_verified and not r.persistence_authorized
    # The intentional external commit is the only change; subsequent calls are zero-effect.
    assert check(s,b,tid,p).code=='context_revision_conflict'
    with s.admin() as db:b.revision=db.get(ExperienceSession,b.sid).context_revision
    assert check(s,b,tid,request(b,raw)).status=='requires_review'


def test_real_reader_sql_trace_provider_zero_and_no_runtime_wiring(reader,monkeypatch):
    from app.mining_provider import ScriptedProvider
    def forbidden(*args,**kwargs):raise AssertionError('Provider must not be called')
    monkeypatch.setattr(ScriptedProvider,'mine',forbidden)
    monkeypatch.setattr(ScriptedProvider,'reserve_cost',forbidden)
    s=reader;b=seed(s);raw='我部署了服务。';tid=saved(s,b,raw);queries=[]
    with s.admin() as db:
        for table in ('ai_mining_runs','paid_calls','paid_audit','conversation_operations'):
            assert db.scalar(text(f'SELECT count(*) FROM {table}'))==0
    def capture(conn,cursor,sql,params,context,many):queries.append(sql)
    event.listen(s.read_engine,'before_cursor_execute',capture)
    try:assert check(s,b,tid,request(b,raw)).status=='candidate_only'
    finally:event.remove(s.read_engine,'before_cursor_execute',capture)
    assert 'SHOW transaction_read_only' in queries and 'SHOW transaction_isolation' in queries
    assert not any(word in q.upper() for q in queries for word in ('FOR UPDATE','PG_ADVISORY','INSERT ','UPDATE ','DELETE ','CREATE ','ALTER ','SET CONSTRAINTS'))
    root=Path(__file__).parents[1]/'app'
    source=(root/'typed_source_preflight.py').read_text(encoding='utf8')
    for name in ('os.environ','get_provider','httpx','requests','APIRouter','get_read_factory','db.commit(','db.add('):
        assert name not in source
    assert 'from app.typed_semantic_spike import' in source
    for file in root.rglob('*.py'):
        if file.name!='typed_source_preflight.py':assert 'typed_source_preflight' not in file.read_text(encoding='utf8')


@pytest.mark.parametrize('setting,value',[('transaction_read_only','off'),('transaction_isolation','read committed')])
def test_transaction_settings_must_actually_be_verified(reader,setting,value):
    s=reader;b=seed(s);raw='我部署了服务。';tid=saved(s,b,raw)
    def fault(conn,cursor,sql,params,context,many):
        if sql=='SHOW '+setting:return "SELECT '"+value+"'",params
        return sql,params
    event.listen(s.read_engine,'before_cursor_execute',fault,retval=True)
    try:r=check(s,b,tid,request(b,raw))
    finally:event.remove(s.read_engine,'before_cursor_execute',fault)
    assert r.code=='readonly_identity_required' and r.source_binding=='not_checked'


def test_simultaneous_real_readers_are_repeatable_and_effect_free(reader):
    s=reader;b=seed(s);raw='我部署了服务。';tid=saved(s,b,raw);p=request(b,raw)
    before=digest(s.admin)
    def read():
        return preflight(s.reader,session_id=b.sid,project_id=b.pid,turn_id=tid,token=b.token,request=p)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=[pool.submit(read) for _ in range(2)]
        results=[task.result(timeout=10) for task in pending]
    assert results[0]==results[1] and results[0].status=='candidate_only'
    assert not results[0].truth_verified and not results[0].persistence_authorized
    assert digest(s.admin)==before
