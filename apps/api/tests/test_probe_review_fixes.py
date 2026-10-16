"""PR17 fixes: retained verified output, durable send claims, no ledger erasure."""
import asyncio
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import socket
import stat
from types import SimpleNamespace
from unittest.mock import patch

from alembic import command
from alembic.script import ScriptDirectory
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.controlled_probe_io import DispatchPermit,_post_once,orchestrate,validate_response
from app.controlled_probe_models import ControlledProbe
from app.deepseek_bridge import synthetic_request
from app.deepseek_contract import FAKE_SECRET,ProbeError
from app.probe_preview import LocalPreviewStore,_acl
from app.windows_operator import powershell
from app.models import utcnow
from test_controlled_probe import experiment,policy,ok_handler
from test_cost_ledger import ledger_stack
from test_http_api import api
from test_deepseek_bridge import role_capability,response


def packet():
    value=response()
    out=json.loads(value['choices'][0]['message']['content'])
    assert out['candidates']
    tid=out['candidates'][0]['citation']['turn_id']
    out.update(stop=False,stop_reason=None,questions=[{'text':'你能补充本地筛选的实现过程吗？',
        'purpose':'detail','source_turn_ids':[tid]}])
    value['choices'][0]['message']['content']=json.dumps(out,ensure_ascii=False)
    return value,out


def test_first_success_retains_candidates_quotes_questions_and_report_without_http(experiment,tmp_path):
    _,control,factory,_,_=experiment
    store=LocalPreviewStore(tmp_path/'private')
    value,expected=packet();calls=[]
    def handler(req):calls.append(1);return httpx.Response(200,json=value)
    result=asyncio.run(orchestrate(control,execution='offline_mock',mock=httpx.MockTransport(handler),preview_store=store))
    assert result['state']=='response_received' and result['validated_preview']==expected
    assert result['validated_preview']['candidates'][0]['citation']['quote']=='我实现了本地筛选。'
    assert result['validated_preview']['questions'][0]['text']==expected['questions'][0]['text']
    with patch('httpx.AsyncHTTPTransport',side_effect=AssertionError('report must never send')):
        recovered=control.report(preview_store=store)
    assert recovered['validated_preview']==expected and len(calls)==1
    row=control.read();path=store.root/(str(row['grant_id'])+'.json')
    _acl(store.root);_acl(path)
    content=path.read_text(encoding='utf8')
    assert FAKE_SECRET not in content and 'system_fingerprint' not in content and 'choices' not in content
    with factory() as db:
        assert db.scalar(text('SELECT count(*) FROM experience_facts'))==0
        assert db.scalar(text('SELECT count(*) FROM conversation_turns'))==0
    assert 'validated_output' not in json.dumps(control.read()['diagnostic'])  # digest only in DB


@pytest.mark.parametrize('fault',['secret','pii','quote','raw_invalid'])
def test_errors_do_not_retain_raw_or_secret_output(experiment,tmp_path,caplog,fault):
    value,out=packet()
    if fault=='secret':out['questions'][0]['text']='请确认 '+FAKE_SECRET
    if fault=='pii':out['questions'][0]['text']='联系 fake@example.com'
    if fault=='quote':out['candidates'][0]['citation']['quote']='fabricated private text'
    value['choices'][0]['message']['content']=json.dumps(out)
    store=LocalPreviewStore(tmp_path/'private')
    with caplog.at_level(logging.DEBUG):
        mock=httpx.MockTransport(lambda req:httpx.Response(200,content=b'private raw '+FAKE_SECRET.encode()) if fault=='raw_invalid' else httpx.Response(200,json=value))
        result=asyncio.run(orchestrate(experiment[1],execution='offline_mock',mock=mock,preview_store=store))
    assert result['state']=='unknown' and 'validated_preview' not in result
    assert list(store.root.iterdir())==[]
    assert FAKE_SECRET not in caplog.text+json.dumps(result)
    assert 'fabricated private text' not in caplog.text+json.dumps(result)


def test_valid_preview_is_still_returned_if_local_retention_fails(experiment,tmp_path):
    store=LocalPreviewStore(tmp_path/'private');value,expected=packet()
    with patch.object(LocalPreviewStore,'save',side_effect=OSError('private path not exposed')):
        result=asyncio.run(orchestrate(experiment[1],execution='offline_mock',mock=httpx.MockTransport(lambda req:httpx.Response(200,json=value)),preview_store=store))
    assert result['validated_preview']==expected and result['state']=='unknown'
    assert result['preview_error']=='controlled_preview_retention_failed_no_retry'
    assert 'private path' not in json.dumps(result)


def test_corrupted_or_overpermissive_preview_is_hidden(experiment,tmp_path):
    store=LocalPreviewStore(tmp_path/'private');value,_=packet()
    asyncio.run(orchestrate(experiment[1],execution='offline_mock',mock=httpx.MockTransport(lambda req:httpx.Response(200,json=value)),preview_store=store))
    row=experiment[1].read();path=store.root/(str(row['grant_id'])+'.json')
    if os.name=='nt':
        import base64
        encoded=base64.b64encode(str(path).encode('utf8')).decode('ascii')
        code=f"$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'));"
        code+="$a=Get-Acl -LiteralPath $p;$sid=New-Object Security.Principal.SecurityIdentifier('S-1-1-0');"
        code+="$a.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid,'Read','Allow')));[IO.File]::SetAccessControl($p,$a)"
        assert powershell(code).returncode==0
    else:os.chmod(path,0o644)
    try:
        assert experiment[1].report(preview_store=store)['validated_preview'] is None
    finally:_acl(path,create=True)
    path.write_text('untrusted raw response must not print',encoding='utf8')
    report=experiment[1].report(preview_store=store)
    assert report['validated_preview'] is None and 'untrusted raw' not in json.dumps(report)


def test_preview_reparse_or_symlink_refused_before_cost(experiment,tmp_path):
    store=LocalPreviewStore(tmp_path/'private')
    with patch.object(Path,'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFLNK,st_file_attributes=0)):
        with pytest.raises(ProbeError,match='link_refused'):store.prepare(experiment[1].read()['grant_id'])
    assert experiment[1].report()['state']=='approved'


def test_bare_real_io_refuses_before_transport_or_dns():
    async def check():
        with patch('httpx.AsyncHTTPTransport',side_effect=AssertionError('no client')), \
             patch.object(socket,'socket',side_effect=AssertionError('no socket')), \
             patch.object(socket,'getaddrinfo',side_effect=AssertionError('no DNS')):
            with pytest.raises(ProbeError,match='dispatch_permit_required'):
                await _post_once(synthetic_request().body,FAKE_SECRET)
    asyncio.run(check())


@pytest.mark.parametrize('condition',['before_permit','forged','expired','revoked','wrong_policy'])
def test_dispatch_requires_current_nonforgeable_unique_permit(experiment,condition):
    admin,control,factory,_,p=experiment
    control.action(p,'reserve')
    token='not-a-issued-token'
    if condition!='before_permit':token=control.action(p,'permit')['dispatch_token']
    if condition=='forged':token='forged'
    if condition=='expired':
        with factory.begin() as db:db.get(ControlledProbe,1).lease_until=utcnow()-timedelta(seconds=1)
    if condition=='revoked':admin.revoke('a'*64)
    if condition=='wrong_policy':p=p.model_copy(update={'operation_hash':'b'*64})
    permit=DispatchPermit(control,p,token);calls=[]
    def handler(req):calls.append(1);return ok_handler(req)
    with pytest.raises((ProbeError,DBAPIError)):
        asyncio.run(_post_once(synthetic_request().body,FAKE_SECRET,mock=httpx.MockTransport(handler),permit=permit))
    assert calls==[]


def test_consumed_dispatch_cannot_be_replayed_or_reconstructed_and_no_nonce_logs(experiment,caplog):
    _,control,_,_,p=experiment
    control.action(p,'reserve')
    with caplog.at_level(logging.DEBUG):permission=control.action(p,'permit')
    token=permission['dispatch_token'];assert token not in caplog.text
    assert token not in json.dumps(control.report())
    permit=DispatchPermit(control,p,token);seen=[]
    def handler(req):seen.append(1);return ok_handler(req)
    async def check():
        transport=httpx.MockTransport(handler)
        await _post_once(synthetic_request().body,FAKE_SECRET,mock=transport,permit=permit)
        with pytest.raises(DBAPIError,match='dispatch_denied'):
            await _post_once(synthetic_request().body,FAKE_SECRET,mock=transport,permit=permit)
    asyncio.run(check())
    assert seen==[1]


@pytest.mark.parametrize('state',['approved','reserved','sent','unknown','response_received','reconciled'])
def test_nonempty_ledger_downgrade_refused_in_every_state(experiment,state):
    admin,control,factory,schema,p=experiment
    if state!='approved':control.action(p,'reserve')
    if state in ('sent','unknown','response_received'):control.action(p,'permit')
    if state=='unknown':control.action(p,'unknown',{'http_status':None,'validated':False,'safe_code':'controlled_result_unknown'})
    if state=='response_received':
        diagnostic,_=validate_response(json.dumps(packet()[0]).encode(),synthetic_request().body)
        control.action(p,'received',diagnostic)
    if state=='reconciled':admin.close_unsent('c'*64)
    from alembic.config import Config
    cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    head=ScriptDirectory.from_config(cfg).get_current_head()
    with factory.kw['bind'].connect() as conn:
        conn.execute(text(f'SET search_path TO "{schema}"'));conn.commit()
        before=conn.execute(text('SELECT grant_id,policy,state,dispatch_token_hash,dispatch_claimed_at FROM controlled_probe')).one()
        totals=conn.execute(text('SELECT ledger_id,ceiling,held,spent,frozen FROM paid_funding')).one()
        conn.commit();cfg.attributes['connection']=conn
        with pytest.raises(RuntimeError,match='downgrade_blocked_nonempty_ledger'):
            command.downgrade(cfg,'0008_paid_authority')
        conn.rollback()
        assert conn.scalar(text('SELECT version_num FROM alembic_version'))==head
        assert conn.execute(text('SELECT grant_id,policy,state,dispatch_token_hash,dispatch_claimed_at FROM controlled_probe')).one()==before
        assert conn.execute(text('SELECT ledger_id,ceiling,held,spent,frozen FROM paid_funding')).one()==totals
        conn.commit();command.upgrade(cfg,'head');conn.commit()  # no reset/regrant
    with pytest.raises(ProbeError):admin.authorize(p)
