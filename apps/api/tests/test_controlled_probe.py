"""All approvals, secrets and invoices here are fictional isolated fixtures."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
import multiprocessing
import os
import ssl
import logging
import ctypes
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from tokenizers import Tokenizer, models, pre_tokenizers

from app.controlled_probe import (ExperimentPolicy,ExperimentAdmin,ExperimentControl,RISK_ACCEPTANCE,
    TOKENIZER_ARCHIVE_SHA,verify_bytes)
from app.controlled_probe_models import ControlledProbe
from app.controlled_probe_io import orchestrate,FakeExperimentSecret,WindowsCredentialSecret,validate_response,_post_once,_https_options
from app.paid_models import PaidFunding
from app.deepseek_contract import ProbeError,FAKE_SECRET,ENDPOINT
from app.deepseek_bridge import synthetic_request
from app.cost_ledger import digest,canonical
from app.models import utcnow
from app.probe_estimate import count_json,estimate
from test_cost_ledger import ledger_stack
from test_http_api import api
from test_deepseek_bridge import role_capability,response


def policy(ledger_id,**changes):
    now=utcnow()
    data=dict(execution='offline_mock',account_ref='fictional-not-an-account',currency='CNY',
        currency_evidence_sha=digest('fictional CNY statement, NOT verified account'),
        secret_ref='Pathwise/DeepSeek/fictional-not-an-account',secret_revision=1,
        ledger_id=ledger_id,operation_hash=digest('one fixed fictional operation'),approver='test-only',
        approval_sha=digest(str(uuid4())+' TEST NOT AN APPROVAL'),starts_at=now-timedelta(seconds=1),
        expires_at=now+timedelta(minutes=20),price_expires_at=now+timedelta(hours=1),
        price_evidence_sha=digest('test-only applicable pricing'),peak_input_miss_cny_per_million='2',
        peak_output_cny_per_million='8',tokenizer_archive_sha=TOKENIZER_ARCHIVE_SHA,
        estimated_input_tokens=812,planned_cny='0.10',risk_acceptance=RISK_ACCEPTANCE)
    data.update(changes);return ExperimentPolicy.model_validate(data)


@pytest.fixture
def experiment(request,role_capability):
    if not role_capability:
        if os.getenv('CI'):pytest.fail('restricted LOGIN required in CI')
        pytest.skip('isolated test role creation unavailable')
    _,factory,schema=request.getfixturevalue('ledger_stack')
    engine=factory.kw['bind'];admin=ExperimentAdmin(factory)
    with factory() as db:ledger_id=db.get(PaidFunding,1).ledger_id
    p=policy(ledger_id);admin.authorize(p)
    role='controlled_test_'+uuid4().hex;password=uuid4().hex
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('pathwise.fixture_password',:p,true)"),{'p':password})
        conn.execute(text(f'''DO $$ BEGIN EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
            '{role}',current_setting('pathwise.fixture_password')); END $$'''))
    runtime=create_engine(engine.url.set(username=role,password=password),poolclass=NullPool,hide_parameters=True)
    try:
        admin.provision_runtime(schema,role)
        control=ExperimentControl(runtime,schema,ledger_id);control.check_role(live=False)
        yield admin,control,factory,schema,p
    finally:
        runtime.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'));conn.execute(text(f'DROP ROLE "{role}"'))


def run(experiment,handler):
    return asyncio.run(orchestrate(experiment[1],execution='offline_mock',mock=httpx.MockTransport(handler)))


def ok_handler(request):
    assert str(request.url)==ENDPOINT and request.method=='POST'
    assert request.content==synthetic_request().body
    assert request.headers['Authorization']=='Bearer '+FAKE_SECRET
    return httpx.Response(200,json=response())


def test_success_is_not_invoice_and_cannot_repeat(experiment):
    seen=[]
    def handler(req):seen.append(req.content);return ok_handler(req)
    result=run(experiment,handler)
    assert result['state']=='response_received' and result['actual_cny'] is None, result
    assert result['execution']=='offline_mock' and result['held_cny']=='0.100000'
    assert result['frozen'] is True and result['diagnostic']['validated'] is True
    assert result['estimated_cost_cny']=='0.003672'
    assert result['usage_estimated_cost_cny'] is not None
    with pytest.raises(ProbeError,match='controlled_already_attempted'):run(experiment,handler)
    assert len(seen)==1
    with pytest.raises(ProbeError,match='real_invoice_requires_live_record'):
        experiment[0].reconcile('0.003',digest('fake'),digest('fake'))


@pytest.mark.parametrize('status',[301,401,429,500,503])
def test_http_errors_stop_keep_reserve_and_do_not_retry(experiment,status):
    count=[]
    def handler(req):count.append(1);return httpx.Response(status,text='DO NOT LOG: public fake credential')
    report=run(experiment,handler)
    assert report['state']=='unknown' and report['held_cny']=='0.100000'
    assert report['actual_cny'] is None and report['diagnostic']['http_status']==status
    assert 'credential' not in canonical(report) and len(count)==1
    with pytest.raises(ProbeError,match='already_attempted'):run(experiment,handler)


@pytest.mark.parametrize('fault',['timeout','disconnect','invalid_json','length','usage','source','too_large','refusal','model','id','index_type','fingerprint'])
def test_response_faults_preserve_unknown(experiment,fault):
    def handler(req):
        if fault=='timeout':raise httpx.ReadTimeout('private fake exception')
        if fault=='disconnect':raise httpx.ConnectError('private fake exception')
        if fault=='invalid_json':return httpx.Response(200,content=b'not json')
        if fault=='too_large':return httpx.Response(200,content=b'x'*262145)
        packet=response()
        if fault=='length':packet['choices'][0]['finish_reason']='length'
        if fault=='usage':packet['usage']['total_tokens']+=1
        if fault=='refusal':packet['choices'][0]['message']['refusal']='private refusal'
        if fault=='model':packet['model']='different-model'
        if fault=='id':packet['id']=42
        if fault=='index_type':packet['choices'][0]['index']=False
        if fault=='fingerprint':packet['system_fingerprint']={}
        if fault=='source':
            value=json.loads(packet['choices'][0]['message']['content'])
            value['candidates'][0]['citation']['quote']='a fabricated statement'
            packet['choices'][0]['message']['content']=json.dumps(value)
        return httpx.Response(200,json=packet)
    result=run(experiment,handler)
    assert result['state']=='unknown' and result['actual_cny'] is None and result['frozen'] is True
    assert result['held_cny']=='0.100000' and 'private' not in canonical(result)


def test_cancel_after_send_and_read_only_recovery(experiment):
    async def handler(req):raise asyncio.CancelledError('private cancel message')
    with pytest.raises(asyncio.CancelledError):run(experiment,handler)
    first=experiment[1].report();second=experiment[1].report()
    assert first==second and first['state']=='unknown' and first['held_cny']=='0.100000'


def test_reserved_without_permit_never_resumes(experiment):
    _,control,_,_,p=experiment
    assert control.action(p,'reserve')['created']
    with patch.object(FakeExperimentSecret,'resolve',side_effect=AssertionError('secret forbidden')):
        with pytest.raises(ProbeError,match='already_attempted'):run(experiment,ok_handler)
    assert control.report()['state']=='reserved'
    experiment[0].close_unsent(digest('test owner proves no permit'))
    assert control.report()['held_cny']=='0.000000'
    with pytest.raises(ProbeError):experiment[0].authorize(p)


def test_revoked_and_budget_exceeded_never_resolve(experiment):
    admin,control,factory,_,_=experiment
    with factory.begin() as db:db.get(PaidFunding,1).ceiling=0
    with patch.object(FakeExperimentSecret,'resolve',side_effect=AssertionError('secret forbidden')):
        with pytest.raises(ProbeError,match='budget_unavailable'):run(experiment,ok_handler)
        admin.revoke(digest('test revoke'))
        with pytest.raises(ProbeError,match='inactive'):run(experiment,ok_handler)
    assert control.report()['state']=='approved'


def test_no_authorization_or_owner_or_live_fixture_can_send(ledger_stack):
    _,factory,schema=ledger_stack
    with factory() as db:lid=db.get(PaidFunding,1).ledger_id
    control=ExperimentControl(factory.kw['bind'],schema,lid)
    assert control.report()['state'] is None
    with patch.object(WindowsCredentialSecret,'resolve',side_effect=AssertionError('real secret forbidden')):
        with pytest.raises(ProbeError,match='restricted_login'):asyncio.run(orchestrate(control,execution='offline_mock',mock=httpx.MockTransport(ok_handler)))
        with pytest.raises(ProbeError,match='live_database'):asyncio.run(orchestrate(control,execution='controlled_live_probe'))
    with pytest.raises(ProbeError,match='approval_missing'):control.policy('offline_mock')


def test_immutable_and_restricted_runtime_cannot_approve_or_unfreeze(experiment):
    _,control,_,schema,p=experiment
    runtime_factory=sessionmaker(control.engine)
    with pytest.raises(DBAPIError):ExperimentAdmin(runtime_factory).authorize(p)
    with control.engine.connect() as conn:
        for sql in [f'UPDATE "{schema}".paid_funding SET ceiling=1',f'DELETE FROM "{schema}".controlled_probe',
                    f'UPDATE "{schema}".controlled_probe SET revoked=false']:
            with pytest.raises(DBAPIError):conn.execute(text(sql))
            conn.rollback()
    run(experiment,ok_handler)
    with experiment[2].begin() as db:
        with pytest.raises(DBAPIError,match='unreconciled'):
            db.execute(text(f'UPDATE "{schema}".paid_funding SET frozen=false'))


def test_body_and_operation_binding(experiment):
    _,control,_,_,p=experiment
    with pytest.raises(ProbeError,match='request_changed'):verify_bytes(synthetic_request().body+b' ')
    with pytest.raises(DBAPIError,match='binding_changed'):
        control.action(p,'reserve',{'request_sha':p.request_sha,'operation':digest('other key')})
    with pytest.raises(DBAPIError,match='binding_changed'):control.action(p,'reserve',{})
    assert control.report()['held_cny']=='0.000000'


@pytest.mark.parametrize('change',[{'currency':'USD'},{'risk_acceptance':'yes'},{'estimated_input_tokens':500},
    {'output_cap':257},{'endpoint':'https://other.invalid/chat'},{'planned_cny':'0.001'},
    {'planned_cny':'0.11'},{'secret_ref':'Pathwise/DeepSeek/other'},{'peak_input_miss_cny_per_million':'1'}])
def test_invalid_soft_policy_is_not_accepted(change):
    with pytest.raises(ValueError):policy(uuid4(),**change)


def test_no_env_secret_lookup_and_live_mock_separation(experiment):
    with patch('os.getenv',side_effect=AssertionError('no env key')), \
         patch.object(WindowsCredentialSecret,'resolve',side_effect=AssertionError('real secret forbidden')):
        with pytest.raises(ProbeError,match='mode_mismatch'):
            asyncio.run(orchestrate(experiment[1],execution='controlled_live_probe',mock=httpx.MockTransport(ok_handler)))
        result=run(experiment,ok_handler)
    assert result['state']=='response_received'


def test_tokenizer_data_only_and_archive_tamper(tmp_path):
    tokenizer=Tokenizer(models.WordLevel({'[UNK]':0,'hello':1},unk_token='[UNK]'))
    tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
    assert count_json(tokenizer.to_str(),b'hello hello')==2
    bad=tmp_path/'not-official.zip';bad.write_bytes(b'bad archive')
    with pytest.raises(ProbeError,match='archive_changed'):estimate(bad,synthetic_request().body)


def worker(url,schema,lid,pjson,barrier,crash=False):
    engine=create_engine(url,poolclass=NullPool,hide_parameters=True)
    control=ExperimentControl(engine,schema,lid)
    p=ExperimentPolicy.model_validate_json(pjson)
    try:
        if barrier:barrier.wait(timeout=20)
        reserved=control.action(p,'reserve')
        if not reserved['created']:return False
        result=control.action(p,'permit')['permitted']
        if crash and result:os._exit(23)
        return result
    except Exception:return False
    finally:engine.dispose()


def test_two_processes_one_permit_and_crash_persists(experiment):
    _,control,_,schema,p=experiment
    ctx=multiprocessing.get_context('spawn')
    with ctx.Manager() as manager:
        barrier=manager.Barrier(2)
        with ProcessPoolExecutor(2,mp_context=ctx) as executor:
            futures=[executor.submit(worker,control.engine.url.render_as_string(hide_password=False),schema,
                control.ledger_id,p.model_dump_json(),barrier) for _ in range(2)]
            assert sum(f.result(timeout=45) for f in futures)==1
    assert control.report()['state']=='sent' and control.report()['held_cny']=='0.100000'


def test_process_exit_after_permit_and_expired_read_does_not_release(experiment):
    _,control,factory,schema,p=experiment
    ctx=multiprocessing.get_context('spawn')
    proc=ctx.Process(target=worker,args=(control.engine.url.render_as_string(hide_password=False),schema,
        control.ledger_id,p.model_dump_json(),None,True))
    proc.start();proc.join(30)
    assert proc.exitcode==23
    with factory.begin() as db:db.get(ControlledProbe,1).lease_until=utcnow()-timedelta(seconds=1)
    assert control.report()['state']=='unknown' and control.report()['held_cny']=='0.100000'
    with factory() as db:assert db.get(ControlledProbe,1).state=='sent'  # report is read-only


def test_migration_0008_roundtrip_preserves_zero_pool(migrated_connection):
    conn,cfg=migrated_connection
    before=conn.execute(text('SELECT ledger_id,ceiling,held,spent FROM paid_funding')).one();conn.commit()
    command.downgrade(cfg,'0008_paid_authority');conn.commit()
    command.upgrade(cfg,'head');conn.commit()
    assert conn.execute(text('SELECT ledger_id,ceiling,held,spent FROM paid_funding')).one()==before
    assert conn.scalar(text('SELECT count(*) FROM controlled_probe'))==0
    conn.commit();command.check(cfg)


@pytest.mark.parametrize('amount',['0','0.003672123456','0.12'])
def test_native_cny_invoice_contract_in_random_schema_only(ledger_stack,amount):
    # SQL contract fixture ONLY. Cannot reach live IO: wrong DB/schema and no
    # Windows secret. No mock execution can be reconciled as a real invoice.
    _,factory,schema=ledger_stack
    with factory() as db:lid=db.get(PaidFunding,1).ledger_id
    admin=ExperimentAdmin(factory);p=policy(lid,execution='controlled_live_probe')
    admin.authorize(p);control=ExperimentControl(factory.kw['bind'],schema,lid)
    with patch.object(WindowsCredentialSecret,'resolve',side_effect=AssertionError('no key')), \
         patch('httpx.AsyncClient',side_effect=AssertionError('no HTTP')):
        control.action(p,'reserve');control.action(p,'permit')
        invoice,review=digest('synthetic invoice SQL contract only'),digest('synthetic review')
        assert admin.reconcile(amount,invoice,review) is True
        assert admin.reconcile(amount,invoice,review) is False
        with pytest.raises(ProbeError,match='invoice_conflict'):admin.reconcile('0.000001',invoice,review)
    report=control.report()
    assert report['state']=='reconciled' and Decimal(report['actual_cny'])==Decimal(amount)
    assert report['held_cny']=='0.000000' and report['frozen'] is True
    assert Decimal(report['spent_cny'])>=Decimal(amount)  # conservative micro-CNY total
    with factory() as db:
        assert db.get(ControlledProbe,1).actual_cny==Decimal(amount)


def test_raw_errors_and_debug_logging_never_leak(experiment,caplog):
    with caplog.at_level(logging.DEBUG):
        def handler(req):
            logging.getLogger('httpcore').debug('must not expose '+FAKE_SECRET)
            raise RuntimeError('private body '+FAKE_SECRET)
        report=run(experiment,handler)
    assert report['state']=='unknown'
    assert FAKE_SECRET not in caplog.text and FAKE_SECRET not in canonical(report)
    assert 'private body' not in caplog.text


def test_production_http_options_with_factory_replaced_by_memory_mock(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://invalid-proxy.invalid:9')
    captured=[]
    def factory(**kwargs):
        assert kwargs['retries']==0 and kwargs['trust_env'] is False
        assert kwargs['verify'].verify_mode==ssl.CERT_REQUIRED and kwargs['verify'].check_hostname
        captured.append(kwargs)
        return httpx.MockTransport(ok_handler)
    with patch('app.controlled_probe_io.httpx.AsyncHTTPTransport',side_effect=factory):
        # Test the exact TLS/no-retry factory without opening a real path.
        memory_transport=httpx.AsyncHTTPTransport(**_https_options())
        status,body=asyncio.run(_post_once(synthetic_request().body,FAKE_SECRET,mock=memory_transport))
    assert status==200 and len(captured)==1 and body


def test_policy_cannot_be_mutated_or_sensitive_diagnostic_persisted(experiment):
    _,control,factory,schema,p=experiment
    with factory.begin() as db:
        with pytest.raises(DBAPIError,match='immutable'):
            db.execute(text(f'UPDATE "{schema}".controlled_probe SET policy=\'{{}}\'::jsonb'))
    control.action(p,'reserve');control.action(p,'permit')
    with pytest.raises(DBAPIError,match='diagnostic_invalid'):
        control.action(p,'unknown',{'validated':False,'safe_code':'secret-do-not-store','http_status':None})
    assert control.report()['diagnostic'] is None


def crash_inside_http(url,schema,lid):
    engine=create_engine(url,poolclass=NullPool,hide_parameters=True)
    control=ExperimentControl(engine,schema,lid)
    def handler(req):os._exit(24)
    asyncio.run(orchestrate(control,execution='offline_mock',mock=httpx.MockTransport(handler)))


def test_process_exit_inside_mock_http_keeps_unknown_cost(experiment):
    _,control,factory,schema,_=experiment
    ctx=multiprocessing.get_context('spawn')
    proc=ctx.Process(target=crash_inside_http,args=(control.engine.url.render_as_string(hide_password=False),schema,control.ledger_id))
    proc.start();proc.join(30)
    assert proc.exitcode==24
    with factory.begin() as db:db.get(ControlledProbe,1).lease_until=utcnow()-timedelta(seconds=1)
    assert control.report()['state']=='unknown' and control.report()['held_cny']=='0.100000'


@pytest.mark.parametrize('mismatch',[None,'account','revision','target'])
def test_windows_secret_protocol_with_fake_native_memory_only(mismatch):
    p=policy(uuid4(),secret_revision=(1<<32)|2)
    blobs=[];freed=[]
    class Read:
        def __call__(self,target,kind,flags,output):
            struct=self.argtypes[-1]._type_._type_
            c=struct();c.TargetName=p.secret_ref if mismatch!='target' else 'other'
            c.UserName=p.account_ref if mismatch!='account' else 'other'
            c.LastWritten.dwHighDateTime=1;c.LastWritten.dwLowDateTime=2 if mismatch!='revision' else 3
            raw=FAKE_SECRET.encode('utf-16-le');blob=(ctypes.c_byte*len(raw)).from_buffer_copy(raw)
            c.CredentialBlobSize=len(raw);c.CredentialBlob=blob
            blobs.append((c,blob))
            ctypes.cast(output,self.argtypes[-1])[0]=ctypes.pointer(c)
            return True
    class Free:
        def __call__(self,ptr):freed.append(True)
    class FakeNative:
        CredReadW=Read();CredFree=Free()
    with patch('app.controlled_probe_io.os.name','nt'), \
         patch('app.controlled_probe_io.ctypes.WinDLL',return_value=FakeNative(),create=True):
        if mismatch:
            with pytest.raises(ProbeError,match='binding_changed'):WindowsCredentialSecret().resolve(p)
        else:assert WindowsCredentialSecret().resolve(p)==FAKE_SECRET
    assert freed==[True] and all(byte==0 for byte in blobs[0][1])


def test_repository_template_cannot_authorize_and_estimate_is_not_a_bound():
    root=Path(__file__).resolve().parents[3]
    with pytest.raises(ValueError):
        ExperimentPolicy.model_validate_json((root/'docs/evaluation/controlled-probe-approval.template.json').read_text())
    record=json.loads((root/'docs/evaluation/controlled-probe-estimate.json').read_text())
    assert record['approved_real_cny']=='0' and record['approved_real_calls']==0
    assert record['estimate']['certified_upper_bound'] is False and record['actual_cost_cny'] is None
    assert Decimal(record['cost_estimated_cny'])==policy(uuid4()).estimate_cny()


@pytest.mark.parametrize('script,args',[('controlled_live_probe.py',['prepare','--config']),
    ('setup_probe_ledger.py',['--runtime-role','unused','--owner-config'])])
def test_operator_clis_reject_daily_database_before_connect(tmp_path,script,args):
    root=Path(__file__).resolve().parents[3]
    config=tmp_path/'config.json'
    value={'database_url':'postgresql+psycopg://fake:do-not-log@127.0.0.1:9/pathwise_dev'}
    if script=='controlled_live_probe.py':value['ledger_id']=str(uuid4())
    config.write_text(json.dumps(value),encoding='utf-8-sig')
    result=subprocess.run([sys.executable,'-X','utf8',str(root/'scripts'/script),*args,str(config)],capture_output=True,encoding='utf8')
    assert result.returncode==2
    assert 'do-not-log' not in result.stdout+result.stderr and 'Traceback' not in result.stderr
    if script=='controlled_live_probe.py':
        assert json.loads(result.stdout)['safe_code']=='controlled_live_database_required'


def test_revoke_during_fake_secret_resolution_stops_before_http(experiment):
    admin,control,_,_,_=experiment
    sent=[]
    def resolve_fake(self,p):
        admin.revoke(digest('test revoke during resolution'))
        return FAKE_SECRET
    with patch.object(FakeExperimentSecret,'resolve',resolve_fake):
        def forbidden(req):
            sent.append(True)
            raise AssertionError('must never send')
        report=run(experiment,forbidden)
    assert report['state']=='unknown' and report['held_cny']=='0.100000' and sent==[]
