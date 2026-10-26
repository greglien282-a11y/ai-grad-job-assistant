import http.client
import json
import os
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import psycopg
from psycopg import sql
import pytest
from research.g3_choice_protocol.runtime import command, apply, Refused
from research.g4_trusted_boundary.runtime import seal
from research.g4_disposable_demo.test_demo import payload
from research.g4_0e_hardening.guard import install as install_guard
from research.g4_0f_demo import audit
from research.g4_0f_demo.server import SourceBoundDemo, integrated_server, SUBMIT

pytestmark=pytest.mark.parametrize('boundary',['credential'],indirect=True)


@pytest.fixture
def source_ttl(request):
    return getattr(request,'param',120)


@pytest.fixture
def live(boundary,tmp_path,source_ttl):
    x=boundary; install_guard(x); audit.install(x); demo=None; server=None; thread=None
    try:
        demo=SourceBoundDemo(x,source_ttl=source_ttl)
        (tmp_path/'index.html').write_text('Synthetic source-bound demo',encoding='utf8')
        server=integrated_server(demo,0,tmp_path); thread=Thread(target=server.serve_forever); thread.start()
        port=server.server_port; first=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
        first.request('GET','/'); r=first.getresponse(); cookie=r.getheader('Set-Cookie').split(';')[0]; r.read(); first.close()
        def request(method,path='/candidate',*,key=None,body=None,foreign=False,raw=None):
            headers={'Cookie':'g4_demo=wrong' if foreign else cookie,'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json'}
            if key: headers['X-Research-Key']=key
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
            try:
                connection.request(method,path,body=raw if raw is not None else json.dumps(body) if body else None,headers=headers)
                response=connection.getresponse(); return response.status,json.loads(response.read())
            finally: connection.close()
        yield x,demo,request
    finally:
        if server: server.shutdown(); server.server_close()
        if thread: thread.join(timeout=10)
        if demo: demo.close()
        x.model.admin.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(x.audit_schema)))


def body(content='我部署了服务。',kind='personal_action',stage='completed',lose=False):
    return {**payload(content,kind,stage,lose),'demo_contract':SUBMIT}


@pytest.mark.parametrize('n',[1,3,5])
def test_real_http_commits_source_audit_graph_and_reads_zero_effect(live,n):
    x,demo,request=live
    assert len({os.getpid(),demo.ingress.process.pid,demo.signer.process.pid})==3
    assert not hasattr(demo.ingress,'_key') and not hasattr(demo.signer,'_signing')
    texts=['我部署了服务。','我编写了脚本。','我制作了👩‍💻原型图。','我测试了导出按钮。','我整理了27条缺失记录。']
    key=str(uuid4()); status,result=request('POST',key=key,body=body('\r\n'.join(texts[:n])))
    assert status==201 and result['demo_contract']=='g4-source-bound-disposable-read-v1'
    assert len(result['facts'])==n and len(result['source_receipt']['selection_ids'])==n
    saved=x.model.snapshot(); assert len(saved['g4_source_receipts'])==len(saved['g4_permits'])==1
    assert len(saved['ref_facts'])==n and result['truth_verified'] is result['persistence_authorized'] is False
    assert 'STRICT_COMMIT_DEADLINE_BLOCK' in result['blocks']
    assert request('GET','/recover',key=key)==(200,result) and x.model.snapshot()==saved


def test_actual_lost_response_recovers_with_both_services_dead_and_same_key_replay(live):
    x,demo,request=live; key=str(uuid4())
    with pytest.raises(http.client.RemoteDisconnected): request('POST',key=key,body=body(lose=True))
    saved=x.model.snapshot()
    for service in (demo.ingress,demo.signer): service.process.kill(); service.process.wait(timeout=10)
    status,result=request('GET','/recover',key=key); assert status==200
    assert request('POST',key=key,body=body())==(201,result)
    assert x.model.snapshot()==saved


def test_same_key_replay_uses_database_receipt_when_transient_request_cache_is_lost(live):
    x,demo,request=live; key=str(uuid4())
    status,saved_result=request('POST',key=key,body=body()); assert status==201
    before=x.model.snapshot(); del demo.request
    for service in (demo.ingress,demo.signer): service.process.kill(); service.process.wait(timeout=10)
    assert request('POST',key=key,body=body())==(201,saved_result)
    assert request('POST',key=str(uuid4()),body=body())[0]==409
    assert x.model.snapshot()==before


@pytest.mark.parametrize('service',['ingress','signer'])
def test_private_service_death_is_real_http503_and_full_rollback(live,service):
    x,demo,request=live; before=x.model.snapshot(); process=getattr(demo,service).process
    process.kill(); process.wait(timeout=10)
    assert request('POST',key=str(uuid4()),body=body())==(503,{'code':'demo_not_saved'})
    assert x.model.snapshot()==before


def test_changed_original_is_refused_by_real_bound_signer_process(live):
    x,demo,request=live; key=str(uuid4()); b=demo.b
    original=command(b.sid,b.pid,['我计划部署服务。'],kind='plan',stage='planned')
    source=demo.ingress.capture(key,original); before=x.model.snapshot()
    changed=command(b.sid,b.pid,['我部署了服务。'])
    with pytest.raises(Refused,match='authenticated_source_mismatch'),x.model.connect() as db:
        result,_=apply(db,b.sid,b.token,key,changed)
        audit.insert(db,x,result['operation_id'],b.sid,source)
        demo.signer.issue(seal(db,x.gate,result['operation_id']),source)
    assert x.model.snapshot()==before


def test_foreign_http_cookie_unknown_contract_duplicate_json_and_formal_routes_refuse(live):
    x,demo,request=live; before=x.model.snapshot(); key=str(uuid4())
    assert request('POST',key=key,body=body(),foreign=True)[0]==403
    assert request('GET','/recover',key=key,foreign=True)[0]==401
    assert request('POST','/api/v3/typed-append',key=key,body=body())[0]==404
    assert request('POST',key=key,raw='{"synthetic":true,"synthetic":false}')[0]==422
    assert request('POST',key=key,body={**body(),'demo_contract':'future-v99'})[0]==409
    assert x.model.snapshot()==before


def test_wrong_key_or_changed_body_never_creates_second_source_receipt(live):
    x,demo,request=live; key=str(uuid4()); assert request('POST',key=key,body=body())[0]==201
    saved=x.model.snapshot()
    assert request('POST',key=str(uuid4()),body=body())[0]==409
    assert request('POST',key=key,body=body('我编写了脚本。'))[0]==409
    assert x.model.snapshot()==saved


def test_concurrent_same_key_http_replays_one_operation(live):
    x,demo,request=live; key=str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:request('POST',key=key,body=body()),range(2)))
    assert results[0]==results[1] and results[0][0]==201
    saved=x.model.snapshot(); assert len(saved['ref_facts'])==len(saved['g4_source_receipts'])==1


def test_audit_is_immutable_and_read_permission_loss_has_no_partial_response(live):
    x,demo,request=live; key=str(uuid4()); assert request('POST',key=key,body=body())[0]==201
    saved=x.model.snapshot()
    with pytest.raises(psycopg.errors.InsufficientPrivilege),x.model.connect() as db:
        db.execute(sql.SQL('UPDATE {} SET source_record=source_record').format(sql.Identifier(x.audit_schema,'receipts')))
    assert x.model.snapshot()==saved
    # Deployment fault outside requests, not owner impersonating the reader.
    x.model.admin.execute(sql.SQL('REVOKE SELECT ON {} FROM {}').format(sql.Identifier(x.audit_schema,'receipts'),sql.Identifier(x.model.roles['reader'])))
    status,error=request('GET','/recover',key=key)
    assert status==409 and error=={'code':'demo_recovery_unavailable'} and x.model.snapshot()==saved


@pytest.mark.parametrize('source_ttl',[3],indirect=True)
def test_genuinely_expired_private_ingress_credential_refuses_before_permit(live):
    x,demo,request=live; key=str(uuid4()); b=demo.b
    original=command(b.sid,b.pid,['我部署了服务。'])
    source=demo.ingress.capture(key,original); before=x.model.snapshot()
    with pytest.raises(Refused,match='authenticated_source_required'),x.model.connect() as db:
        db.execute('SELECT pg_sleep(GREATEST(0,%s-extract(epoch FROM clock_timestamp())+0.08))',(source.expires,))
        result,_=apply(db,b.sid,b.token,key,original)
        audit.insert(db,x,result['operation_id'],b.sid,source)
        demo.signer.issue(seal(db,x.gate,result['operation_id']),source)
    assert x.model.snapshot()==before


def test_pipe_disconnect_refuses_safely_without_body_or_secret_in_http_error(live):
    x,demo,request=live; before=x.model.snapshot()
    demo.signer.process.stdin.close(); demo.signer.process.wait(timeout=10)
    status,error=request('POST',key=str(uuid4()),body=body())
    assert status==503 and error=={'code':'demo_not_saved'} and x.model.snapshot()==before


def test_reference_erase_does_not_claim_approved_source_retention_or_formal_delete(live):
    x,demo,request=live; key=str(uuid4()); assert request('POST',key=key,body=body())[0]==201
    with x.model.connect('eraser') as db: db.execute('SELECT ref_erase(%s,%s)',(demo.b.sid,demo.b.token))
    rows=x.model.snapshot()
    assert len(rows['ref_facts'])==0 and len(rows['g4_source_receipts'])==1
    assert request('GET','/recover',key=key)[0]==409
    # Retained source row is an explicit policy BLOCK. No HTTP DELETE is added;
    # teardown drops the entire disposable schema. Formal DELETE is unchanged.
