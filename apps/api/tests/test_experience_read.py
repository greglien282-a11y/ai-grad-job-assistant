"""C02-C06: synthetic schemas, real SELECT-only LOGIN, no runtime writer."""
import json
import secrets
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import facts, read_contract
from app.experience_read_api import get_read_factory
from app.fact_classification import FIELDS, LEGACY
from app.main import app
from app.models import ConversationTurn, ExperienceFact, FactChange, FactSource, FactEvidence
from app.mining_api import get_mining_factory, get_provider
from app.read_permissions import READ_TABLES
from test_http_api import api
from test_maintenance_api import service, seed, command, post, error, ambiguous, resolve
from test_append_api import append_service, post as append_post
from test_fact_classification import typed, VALID
from test_fact_source_maintenance import stored

V2='/api/v2/experience'


@pytest.fixture
def reader(append_service):
    s=append_service;role='c2b_read_'+uuid4().hex;password=secrets.token_urlsafe(32)
    with s.admin.begin() as db:
        db.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD \'{password}\' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT'))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{s.schema}" TO "{role}"'))
        for table in READ_TABLES:db.execute(text(f'GRANT SELECT ON "{s.schema}".{table} TO "{role}"'))
    engine=create_engine(s.admin.kw['bind'].url.set(username=role,password=password),poolclass=NullPool,
                         hide_parameters=True,connect_args={'options':'-csearch_path='+s.schema})
    s.reader=sessionmaker(engine,expire_on_commit=False);s.read_role=role;s.read_engine=engine
    app.dependency_overrides[get_read_factory]=lambda:s.reader
    try:yield s
    finally:
        app.dependency_overrides.pop(get_read_factory,None);engine.dispose()
        with s.admin.begin() as db:
            owned=db.scalars(text("SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND proowner=(SELECT oid FROM pg_roles WHERE rolname=:r)"),{'r':role}).all()
            for fn in owned:db.execute(text(f'ALTER FUNCTION {fn} OWNER TO "{s.auditor}"'))
            db.execute(text(f'DROP OWNED BY "{role}" RESTRICT'));db.execute(text(f'DROP ROLE "{role}"'))


def summary(s,b,token=None):
    return s.client.get(f'{V2}/projects/{b.pid}/experience-summary',headers={'Authorization':'Bearer '+(token or b.token)})


def export(s,b,token=None):
    return s.client.get(f'{V2}/sessions/{b.sid}/export',headers={'Authorization':'Bearer '+(token or b.token)})


def corrupt(s,table,sql,params):
    """Owner-only synthetic fault injection; restore every guard before reading.

    The reader must detect damaged records with normal catalog admission intact.
    No runtime bypass or migration modification is introduced.
    """
    with s.admin.begin() as db:
        names=db.scalars(text('SELECT tgname FROM pg_trigger WHERE tgrelid=to_regclass(:t) AND NOT tgisinternal'),{'t':table}).all()
        for name in names:db.execute(text(f'ALTER TABLE {table} DISABLE TRIGGER "{name}"'))
        db.execute(text(sql),params)
        db.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        for name in names:db.execute(text(f'ALTER TABLE {table} ENABLE TRIGGER "{name}"'))


def synthetic(s,b,values=VALID[3],status='user_confirmed',*,statement=None,precise=True):
    """Owner arranges a future state, not a typed writer/API.

    evidence_supported requires an evidence FK cycle. For this fixture only the
    immediate no-writer guard is suspended; deferred 0015 consistency is proved
    before restoring the guard. No restricted LOGIN receives UPDATE permission.
    """
    with s.admin.begin() as db:
        facts.authorize(db,b.sid,b.token,write=True)
        if status=='evidence_supported':db.execute(text('ALTER TABLE experience_facts DISABLE TRIGGER classification_immutable'))
        turn=ConversationTurn(session_id=b.sid,role='user',content='我制作了🧪原型图。\r\ne\u0301')
        db.add(turn);db.flush()
        version=1 if status=='pending' else 3 if status in ('rejected','evidence_supported') else 2
        fid=uuid4()
        db.execute(ExperienceFact.__table__.insert().values(id=fid,session_id=b.sid,project_id=b.pid,
            statement=statement or turn.content,version=version,status='user_confirmed' if status=='evidence_supported' else status,
            **dict(zip(FIELDS,values))))
        f=db.get(ExperienceFact,fid)
        original_quotes=[dict(turn_id=str(turn.id),start=0,end=len(turn.content),quote=turn.content)] if precise else []
        db.add(FactSource(fact_id=f.id,session_id=b.sid,turn_id=turn.id,citations=original_quotes if precise else None));db.flush()
        if status=='evidence_supported':
            evidence=FactEvidence(fact_id=f.id,session_id=b.sid,material_reference='synthetic',basis='synthetic')
            db.add(evidence);db.flush()
            db.execute(text("UPDATE experience_facts SET status='evidence_supported',evidence_id=:eid WHERE id=:id"),{'eid':evidence.id,'id':fid})
            db.refresh(f)
        # The ordinary snapshot helper intentionally refuses a schema with a
        # suspended guard. Arrange explicit fixture JSON; deferred DB checks
        # prove it before the guard is restored.
        current=dict(zip(FIELDS,values)) if values!=LEGACY else {}
        current.update(statement=f.statement,status=f.status,version=version,origin=f.origin,memory_state=f.memory_state,
            ai_run_id=None,evidence_id=str(f.evidence_id) if f.evidence_id else None,
            original_source_turn_ids=[str(turn.id)],source_turn_ids=[str(turn.id)],
            source_kind='conversation_turns',source_change_id=None,
            citations=original_quotes)
        prior=None
        for v in range(1,version+1):
            after={**current,'version':v,'status':'pending' if v==1 else 'user_confirmed' if v<version else status,
                   'evidence_id':current['evidence_id'] if v==version else None}
            db.add(FactChange(fact_id=fid,session_id=b.sid,action='created' if v==1 else 'status_changed',
                              actor='system' if v==1 else 'user',before=prior,after=after))
            prior=after
        if status=='evidence_supported':
            db.flush();db.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
            db.execute(text('ALTER TABLE experience_facts ENABLE TRIGGER classification_immutable'))
        return fid


@pytest.mark.parametrize('values',VALID)
@pytest.mark.parametrize('status',['pending','user_confirmed'])
def test_C02_C05_summary_eligibility_and_full_export(reader,values,status):
    s=reader;b=seed(s);t=typed(s,b,values,status=status);before=stored(s.admin)
    r=summary(s,b);assert r.status_code==200,r.text
    body=r.json();assert body['summary_contract_version']==2
    if status=='pending':assert str(t.fid) in [f['id'] for f in body['pending']]
    elif values in (LEGACY,VALID[3]):
        assert [f['id'] for f in body['confirmed']]==[str(t.fid)]
        assert body['text']=='合成分类资料原话。' and not body['incomplete']
    else:
        assert body['confirmed']==[] and body['incomplete'] and body['text']==''
        item=body['reviewed_non_contributions'][0]
        assert item['fact']['id']==str(t.fid)
        assert item['reason']=={'unclassified-v1':'classification_unreviewed','personal_action':'action_in_progress',
            'plan':'plan_not_contribution','background':'background_context','boundary':'boundary_limitation'}[values[2] if values[2]=='unclassified-v1' else values[0]]
    out=export(s,b);assert out.status_code==200,out.text
    data=out.json();assert data['format_version']==2
    f=next(f for f in data['data']['facts'] if f['id']==str(t.fid))
    assert f['fact_contract_version']==3 and f['provenance_version']==3
    assert tuple(f[k] for k in FIELDS)==values and f['classification_citations']==[]
    assert f['classification_basis_status']==('legacy_unclassified' if values==LEGACY else 'not_recorded')
    assert len(data['data']['facts'])==2 and len(data['data']['fact_sources'])==2
    with s.admin() as db:
        snapshots={str(c.id):(c.before,c.after) for c in db.scalars(select(FactChange).where(FactChange.session_id==b.sid))}
    for c in data['data']['history']:
        assert (c['before'],c['after'])==snapshots[c['id']]
        assert c['after_classification']['interpretation']==('legacy_missing_keys' if all(k not in c['after'] for k in FIELDS) else 'explicit_fields')
    assert stored(s.admin)==before


def test_C04_legacy_v1_literal_compatibility_and_v2_zero_writes(reader):
    s=reader;b=seed(s,status='user_confirmed');h={'Authorization':'Bearer '+b.token}
    app.dependency_overrides[get_mining_factory]=lambda:s.runtime
    urls=[f'/api/v1/experience/sessions/{b.sid}',f'/api/v1/experience/projects/{b.pid}/experience-summary',
          f'/api/v1/experience/sessions/{b.sid}/export']
    initial=[s.client.get(url,headers=h) for url in urls]
    assert all(r.status_code==200 for r in initial),[r.text for r in initial]
    before=[r.json() for r in initial];before[2].pop('exported_at')
    state=stored(s.admin)
    queries=[]
    def capture(conn,cursor,sql,params,context,many):queries.append((id(conn),sql))
    event.listen(s.read_engine,'before_cursor_execute',capture)
    try:
        assert summary(s,b).status_code==200
        assert export(s,b).status_code==200
    finally:event.remove(s.read_engine,'before_cursor_execute',capture)
    assert not any(any(word in q.upper() for word in ('FOR UPDATE','PG_ADVISORY','INSERT ','UPDATE ','DELETE ','SET CONSTRAINTS')) for _,q in queries)
    assert sum('SHOW transaction_read_only' in q for _,q in queries)==2
    assert sum('SHOW transaction_isolation' in q for _,q in queries)==2
    after=[s.client.get(url,headers=h).json() for url in urls];after[2].pop('exported_at')
    assert before==after and stored(s.admin)==state


@pytest.mark.parametrize('damage',['snapshot','schema','schema_mixed','permission','labels'])
def test_C06_auth_before_classification_and_corruption_is_not_partial(reader,damage):
    s=reader;b=seed(s);foreign=seed(s);t=typed(s,b)
    with s.admin.begin() as db:
        if damage=='schema':db.execute(text("COMMENT ON TABLE experience_facts IS 'pathwise-classification-schema-v99'"))
        elif damage=='schema_mixed':db.execute(text("COMMENT ON TABLE experience_facts IS E'pathwise-classification-schema-v1\npathwise-classification-schema-v99'"))
        elif damage=='permission':db.execute(text(f'REVOKE SELECT ON fact_sources FROM "{s.read_role}"'))
    if damage=='snapshot':corrupt(s,'fact_changes',"UPDATE fact_changes SET after=after-'memory_state' WHERE fact_id=:id",{'id':t.fid})
    if damage=='labels':corrupt(s,'experience_facts',"UPDATE experience_facts SET fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0' WHERE id=:id",{'id':t.fid})
    before=stored(s.admin)
    for request in (summary,export):
        error(request(s,b,foreign.token),404,'resource_unavailable')
        response=request(s,b)
        assert response.status_code==503,response.text
        assert set(response.json())=={'error'}
    assert stored(s.admin)==before


def test_C06_default_factory_closed_and_versions_and_query_rejected(reader):
    s=reader;b=seed(s)
    for url in [f'/api/v3/experience/projects/{b.pid}/experience-summary',f'{V2}/facts/{b.fid}']:
        error(s.client.get(url,headers={'Authorization':'Bearer '+b.token}),404,'resource_unavailable')
    assert s.client.get(f'{V2}/sessions/{b.sid}/export?version=1',headers={'Authorization':'Bearer '+b.token}).status_code==400
    app.dependency_overrides.pop(get_read_factory)
    error(summary(s,b),503,'experience_read_disabled')


@pytest.mark.parametrize('values',VALID)
def test_C02_evidence_supported_uses_same_eligibility_and_no_inherited_trust(reader,values):
    s=reader;b=seed(s);fid=synthetic(s,b,values,'evidence_supported');state=stored(s.admin)
    r=summary(s,b);assert r.status_code==200,r.text
    out=r.json();eligible=values in (LEGACY,VALID[3])
    assert bool(out['confirmed'])==eligible and out['incomplete']==(not eligible)
    assert bool(out['reviewed_non_contributions'])==(not eligible)
    data=export(s,b);assert data.status_code==200,data.text
    f=next(f for f in data.json()['data']['facts'] if f['id']==str(fid))
    assert f['status']=='evidence_supported' and f['evidence_id'] is not None
    assert f['classification_citations']==[]
    assert len(f['current_statement_citations'])==1
    q=f['current_statement_citations'][0]
    assert q['end']==len(q['quote']) and '🧪' in q['quote'] and '\r\n' in q['quote'] and 'e\u0301' in q['quote']
    assert stored(s.admin)==state


def test_C02_reviewed_reason_order_rejected_pending_and_complete_backup(reader):
    s=reader;b=seed(s,status='user_confirmed')
    fids=[synthetic(s,b,VALID[i]) for i in (4,2,6,7,1,5)]
    rejected=synthetic(s,b,VALID[3],'rejected');pending=synthetic(s,b,VALID[3],'pending')
    r=summary(s,b);assert r.status_code==200,r.text
    body=r.json()
    assert [e['fact']['id'] for e in body['reviewed_non_contributions']]==list(map(str,fids))
    assert [e['reason'] for e in body['reviewed_non_contributions']]==[
        'plan_not_contribution','action_in_progress','background_context','boundary_limitation',
        'classification_unreviewed','plan_not_contribution']
    assert [f['id'] for f in body['confirmed']]==[str(b.fid)] and [f['id'] for f in body['pending']]==[str(pending)]
    data=export(s,b);assert data.status_code==200,data.text
    assert str(rejected) in [f['id'] for f in data.json()['data']['facts']]


@pytest.mark.parametrize('table',READ_TABLES)
def test_C03_missing_table_select_is_fixed_failure_even_when_table_empty(reader,table):
    s=reader;b=seed(s);before=stored(s.admin)
    with s.admin.begin() as db:db.execute(text(f'REVOKE SELECT ON {table} FROM "{s.read_role}"'))
    for request in (summary,export):
        r=request(s,b);assert r.status_code==503,r.text
        assert set(r.json())=={'error'}
    assert stored(s.admin)==before


@pytest.mark.parametrize('fault',['role_update','role_paid_select','function_owner','public_execute','rls','admin_factory'])
def test_C03_runtime_and_acl_admission_has_no_admin_fallback(reader,fault):
    s=reader;b=seed(s);state=stored(s.admin)
    with s.admin.begin() as db:
        if fault=='role_update':db.execute(text(f'GRANT UPDATE(statement) ON experience_facts TO "{s.read_role}"'))
        elif fault=='role_paid_select':db.execute(text(f'GRANT SELECT ON paid_funding TO "{s.read_role}"'))
        elif fault=='function_owner':db.execute(text(f'ALTER FUNCTION classification_current() OWNER TO "{s.read_role}"'))
        elif fault=='public_execute':db.execute(text('GRANT EXECUTE ON FUNCTION classification_value(jsonb) TO PUBLIC'))
        elif fault=='rls':db.execute(text('ALTER TABLE experience_facts ENABLE ROW LEVEL SECURITY'))
    if fault=='admin_factory':app.dependency_overrides[get_read_factory]=lambda:s.admin
    for request in (summary,export):error(request(s,b),503,'experience_read_runtime_unapproved')
    assert stored(s.admin)==state


@pytest.mark.parametrize('fault',['source_missing','source_quote','created_version','history_gap','snapshot_type','snapshot_scalar','classification_partial','created_ai_missing'])
def test_C06_complete_schema_but_damaged_history_sources_is_not_a_backup(reader,fault):
    s=reader;b=seed(s);t=typed(s,b)
    if fault=='source_missing':corrupt(s,'fact_sources','DELETE FROM fact_sources WHERE fact_id=:id',{'id':t.fid})
    elif fault=='source_quote':corrupt(s,'fact_sources',"UPDATE fact_sources SET citations=CAST(:bad AS jsonb) WHERE fact_id=:id",{'id':t.fid,'bad':json.dumps([dict(turn_id='bad',start=0,end=1,quote='错')])})
    elif fault=='created_version':corrupt(s,'fact_changes',"UPDATE fact_changes SET after=jsonb_set(after,'{version}','2') WHERE fact_id=:id AND action='created'",{'id':t.fid})
    elif fault=='history_gap':corrupt(s,'fact_changes',"DELETE FROM fact_changes WHERE fact_id=:id AND action<>'created'",{'id':t.fid})
    elif fault=='snapshot_type':corrupt(s,'fact_changes',"UPDATE fact_changes SET after=jsonb_set(after,'{version}','\"2\"') WHERE fact_id=:id AND action<>'created'",{'id':t.fid})
    elif fault=='snapshot_scalar':corrupt(s,'fact_changes',"UPDATE fact_changes SET after='[]' WHERE fact_id=:id AND action<>'created'",{'id':t.fid})
    elif fault=='created_ai_missing':corrupt(s,'fact_changes',"UPDATE fact_changes SET after=after-'ai_run_id' WHERE fact_id=:id AND action='created'",{'id':t.fid})
    else:corrupt(s,'fact_changes',"UPDATE fact_changes SET after=after-'classification_contract' WHERE fact_id=:id",{'id':t.fid})
    before=stored(s.admin)
    for request in (summary,export):error(request(s,b),503,'experience_read_integrity_unavailable')
    assert stored(s.admin)==before


@pytest.mark.parametrize('later_manual',[False,True])
def test_C05_correction_current_sources_never_become_classification_evidence(reader,later_manual):
    s=reader;b=seed(s);result=post(s,b,command(b));assert result.status_code==201,result.text
    if later_manual:
        with s.admin.begin() as db:facts.change_fact(db,b.fid,b.token,statement='我制作了后续图。',expected_version=2)
    typed(s,b,VALID[4])
    state=stored(s.admin)
    out=export(s,b);assert out.status_code==200,out.text
    data=out.json()['data'];f=next(f for f in data['facts'] if f['id']==str(b.fid))
    assert f['classification_citations']==[] and f['classification_basis_status']=='legacy_unclassified'
    assert bool(f['current_statement_citations'])==(not later_manual)
    if not later_manual:
        assert f['current_statement_citations'][0]['quote']=='我测试了2个导出按钮。'
        assert f['current_statement_citations'][0]['source_kind']=='conversation_change'
    else:assert f['current_statement_source_turn_ids']==[]
    assert len(data['fact_change_sources'])==2 and len(data['conversation_operations'])==1
    assert len(data['fact_sources'])==2
    assert 'key_digest' not in data['conversation_operations'][0]
    assert 'request_tag' not in data['conversation_operations'][0]
    assert 'access_token_hash' not in data
    error(s.client.get(f'/api/v1/experience/sessions/{b.sid}',headers={'Authorization':'Bearer '+b.token}),409,'fact_contract_upgrade_required')
    assert stored(s.admin)==state


def test_C05_append_created_citation_is_current_statement_but_not_classification(reader):
    s=reader;b=seed(s);r=append_post(s,b);assert r.status_code==201,r.text
    state=stored(s.admin);out=export(s,b);assert out.status_code==200,out.text
    data=out.json()['data'];new_id=r.json()['effects'][0]['fact_id']
    f=next(f for f in data['facts'] if f['id']==new_id)
    assert f['current_statement_citations'][0]['source_kind']=='original_source'
    assert f['current_statement_citations'][0]['quote']==f['statement']
    assert f['classification_citations']==[] and f['classification_contract']=='legacy-v0'
    assert len(data['fact_change_sources'])==3 and data['conversation_operations'][0]['contract_version']==2
    assert sorted(src['effect_slot'] for src in data['fact_change_sources'])==[1,2,3]
    assert {src['fact_id'] for src in data['fact_change_sources']}=={effect['fact_id'] for effect in r.json()['effects']}
    assert stored(s.admin)==state


@pytest.mark.parametrize('fault',['fcs_quote','co_version','co_target_version','snapshot_nested_bool','before_drift','created_trust'])
def test_C06_no_partial_export_of_invalid_audit_or_trust(reader,fault):
    s=reader;b=seed(s)
    if fault in ('fcs_quote','co_version','co_target_version'):
        result=post(s,b,command(b));assert result.status_code==201,result.text
        if fault=='fcs_quote':corrupt(s,'fact_change_sources',"UPDATE fact_change_sources SET quote='错误引用' WHERE fact_id=:id",{'id':b.fid})
        elif fault=='co_target_version':corrupt(s,'conversation_operations','UPDATE conversation_operations SET target_version=99 WHERE session_id=:id',{'id':b.sid})
        else:
            with s.admin.begin() as db:
                db.execute(text('ALTER TABLE conversation_operations DROP CONSTRAINT ck_co_identity'))
                db.execute(text('ALTER TABLE conversation_operations DROP CONSTRAINT ck_co_shape'))
            corrupt(s,'conversation_operations','UPDATE conversation_operations SET contract_version=9 WHERE session_id=:id',{'id':b.sid})
    else:
        fid=synthetic(s,b)
        if fault=='snapshot_nested_bool':sql="UPDATE fact_changes SET after=jsonb_set(after,'{citations,0,start}','false') WHERE fact_id=:id AND action<>'created'"
        elif fault=='before_drift':sql="UPDATE fact_changes SET before=jsonb_set(before,'{memory_state}','\"certain\"') WHERE fact_id=:id AND action<>'created'"
        else:sql="UPDATE fact_changes SET after=jsonb_set(after,'{status}','\"user_confirmed\"') WHERE fact_id=:id AND action='created'"
        corrupt(s,'fact_changes',sql,{'id':fid})
    state=stored(s.admin)
    for request in (summary,export):error(request(s,b),503,'experience_read_integrity_unavailable')
    assert stored(s.admin)==state


def test_C06_repeatable_read_has_no_session_lock_or_mixed_revision(reader):
    s=reader;b=seed(s);fired=False
    def writer():
        with s.admin.begin() as db:facts.change_fact(db,b.fid,b.token,status='user_confirmed',expected_version=1)
    def interleave(conn,cursor,sql,params,context,many):
        nonlocal fired
        if not fired and 'FROM experience_facts' in sql:
            fired=True
            # The reader already established its snapshot at authorization.
            # A real second connection must commit without a reader row lock.
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(writer).result(timeout=10)
    event.listen(s.read_engine,'before_cursor_execute',interleave)
    try:r=summary(s,b)
    finally:event.remove(s.read_engine,'before_cursor_execute',interleave)
    assert fired and r.status_code==200,r.text
    assert r.json()['confirmed']==[] and r.json()['pending'][0]['version']==1
    assert r.json()['context_revision']==b.revision
    with s.admin() as db:assert db.get(ExperienceFact,b.fid).version==2


def test_C05_public_http_fixture_is_lossless_in_the_python_and_ts_contract():
    path=Path(__file__).resolve().parents[2]/'web/src/test/experience-read-fixtures.json'
    data=json.loads(path.read_text(encoding='utf8'))
    assert read_contract.SummaryV2.model_validate(data['summary']).model_dump(mode='json')==data['summary']
    assert read_contract.ExportV2.model_validate(data['export']).model_dump(mode='json')==data['export']
    assert 'access_token_hash' not in json.dumps(data)
    assert 'key_digest' not in json.dumps(data) and 'request_tag' not in json.dumps(data)


@pytest.mark.parametrize('with_run',[False,True])
def test_C05_typed_origin_run_identity_and_history_remain_separate_from_classification(reader,with_run):
    s=reader;b=seed(s);t=typed(s,b,with_run=with_run)
    out=export(s,b);assert out.status_code==200,out.text
    data=out.json()['data'];f=next(f for f in data['facts'] if f['id']==str(t.fid))
    assert f['origin']==('ai_extracted' if with_run else 'manual')
    assert bool(f['ai_run_id'])==with_run and len(data['mining_runs'])==int(with_run)
    assert f['classification_citations']==[]
    corrupt(s,'fact_changes',"UPDATE fact_changes SET after=jsonb_set(after,'{ai_run_id}','{}') WHERE fact_id=:id AND action='created'",{'id':t.fid})
    before=stored(s.admin)
    error(export(s,b),503,'experience_read_integrity_unavailable')
    assert stored(s.admin)==before


def test_C06_get_is_business_readonly_even_for_expired_audit_and_supplied_key(reader):
    s=reader;b=seed(s);result=append_post(s,b);assert result.status_code==201,result.text
    corrupt(s,'conversation_operations',"UPDATE conversation_operations SET created_at=created_at-interval '26 hours',completed_at=created_at-interval '26 hours',expires_at=created_at-interval '2 hours' WHERE session_id=:id",{'id':b.sid})
    calls=[]
    def provider():
        calls.append('provider');raise AssertionError('GET requested a Provider')
    app.dependency_overrides[get_provider]=provider
    def all_business():
        with s.admin() as db:
            return {table:db.scalars(text(f'SELECT to_jsonb(t)::text FROM {table} t ORDER BY to_jsonb(t)::text')).all()
                    for table in (*READ_TABLES,'idempotency_operations','ai_mining_receipts')}
    before=all_business()
    h={'Authorization':'Bearer '+b.token,'Idempotency-Key':'not-a-write-or-registration'}
    for url in (f'{V2}/projects/{b.pid}/experience-summary',f'{V2}/sessions/{b.sid}/export'):
        r=s.client.get(url,headers=h);assert r.status_code==200,r.text
        assert r.headers['cache-control']=='no-store'
    assert calls==[] and all_business()==before


def test_C05_v1_clarification_parent_and_resolution_keep_the_original_input_sources(reader):
    s=reader;b=seed(s);parent,_,_=ambiguous(s,b)
    result=resolve(s,b,parent);assert result.status_code==201,result.text
    before=stored(s.admin);out=export(s,b);assert out.status_code==200,out.text
    data=out.json()['data'];operations=data['conversation_operations']
    assert len(operations)==2 and len(data['fact_change_sources'])==2
    root=next(o for o in operations if o['kind']=='root')
    child=next(o for o in operations if o['kind']=='resolution')
    assert child['parent_operation_id']==root['id'] and child['input_turn_id']==root['input_turn_id']
    assert all(s['turn_id']==root['input_turn_id'] for s in data['fact_change_sources'])
    assert stored(s.admin)==before


@pytest.mark.parametrize('precise',[False,True])
def test_C06_typed_source_must_support_the_initial_statement_not_just_have_valid_coordinates(reader,precise):
    s=reader;b=seed(s)
    # Existing 0015 accepts this internally consistent synthetic history: the
    # source and its saved quote agree, but the fact's initial text is different.
    # The new GET must refuse, not present that quote as current statement support.
    synthetic(s,b,statement='我制作了28张图。',precise=precise)
    before=stored(s.admin)
    responses=[request(s,b) for request in (summary,export)]
    assert [r.status_code for r in responses]==[503,503]
    for response in responses:error(response,503,'experience_read_integrity_unavailable')
    assert stored(s.admin)==before


@pytest.mark.parametrize('fault',['missing_status','unknown_status','text_without_edit','historical_source_shape','historical_evidence_missing'])
def test_C06_historical_core_and_statement_transition_are_not_opaque_backup_data(reader,fault):
    s=reader;b=seed(s,status='user_confirmed')
    if fault=='text_without_edit':
        fid=synthetic(s,b)
        corrupt(s,'experience_facts',"UPDATE experience_facts SET statement='我制作了28张图。' WHERE id=:id",{'id':fid})
        corrupt(s,'fact_changes',"UPDATE fact_changes SET after=jsonb_set(after,'{statement}',CAST(:body AS jsonb)) WHERE fact_id=:id AND action<>'created'",{'id':fid,'body':json.dumps('我制作了28张图。')})
    elif fault in ('historical_source_shape','historical_evidence_missing'):
        with s.admin.begin() as db:facts.change_fact(db,b.fid,b.token,memory_state='certain',expected_version=2)
        field='original_source_turn_ids' if fault=='historical_source_shape' else 'evidence_id'
        value=json.dumps('not-a-turn-list' if fault=='historical_source_shape' else str(uuid4()))
        corrupt(s,'fact_changes',f"UPDATE fact_changes SET after=CASE WHEN after->>'version'='2' THEN jsonb_set(after,'{{{field}}}',CAST(:bad AS jsonb)) ELSE after END,before=CASE WHEN after->>'version'='3' THEN jsonb_set(before,'{{{field}}}',CAST(:bad AS jsonb)) ELSE before END WHERE fact_id=:id",{'id':b.fid,'bad':value})
    else:
        operation="{column}-'status'" if fault=='missing_status' else "jsonb_set({column},'{status}','\"future_reviewed\"')"
        # Keep the adjacent snapshots equally damaged, so agreement alone is
        # insufficient; the recognized historical trust enum must be validated.
        after=operation.replace('{column}','after');before=operation.replace('{column}','before')
        corrupt(s,'fact_changes',f"UPDATE fact_changes SET after=CASE WHEN action='created' THEN {after} ELSE after END,before=CASE WHEN action<>'created' THEN {before} ELSE before END WHERE fact_id=:id",{'id':b.fid})
    state=stored(s.admin)
    responses=[request(s,b) for request in (summary,export)]
    assert [r.status_code for r in responses]==[503,503]
    assert stored(s.admin)==state
