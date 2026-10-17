"""Subprocess crash/restart evidence, strictly synthetic test DB/schema only."""
import json
import os
import re
import socket
import sys
from pathlib import Path
from uuid import UUID
import ctypes
import httpx
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


def forbidden(*args,**kwargs):
    raise RuntimeError('offline_worker_forbidden')


def main():
    data=json.loads(sys.stdin.read())
    url=make_url(os.environ['TEST_DATABASE_URL'])
    schema=data['schema']
    if (url.host not in ('localhost','127.0.0.1') or url.database not in ('pathwise_test','pathwise_e2e')
        or not re.fullmatch(r'test_[a-f0-9]{32}',schema)): raise RuntimeError()
    url=url.set(host='127.0.0.1')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    numeric_lookup=socket.getaddrinfo
    def database_only(host,port,*args,**kwargs):
        if host!='127.0.0.1' or str(port)!=str(url.port or 5432): return forbidden()
        return numeric_lookup('127.0.0.1',port,*args,**kwargs)
    socket.create_connection=forbidden
    socket.getaddrinfo=database_only  # numeric loopback DB only; no supplier DNS
    ctypes.WinDLL=forbidden
    httpx.HTTPTransport.handle_request=forbidden
    httpx.AsyncHTTPTransport.handle_async_request=forbidden
    engine=create_engine(url,poolclass=NullPool,hide_parameters=True,
        connect_args={'options':f'-csearch_path={schema} -cstatement_timeout=5000'})
    factory=sessionmaker(engine,expire_on_commit=False)
    from offline_manifest_store import put,recover
    if data['mode']=='recover':
        from app import prepared_mining_request,model_adapter,mining_context
        prepared_mining_request.prepare_request=forbidden
        model_adapter.Adapter.build_request=forbidden
        mining_context.build_context=forbidden
        with factory.begin() as db:
            result=recover(db,UUID(data['sid']),data['token'],UUID(data['rid']),UUID(data['root']),data['operation'])
            print(json.dumps({'sha':result.request.request_sha,'verified':result.recovered_and_verified,
                'paid_authorized':result.paid_authorized,'dispatch_permitted':result.dispatch_permitted}))
        engine.dispose()
        return
    from app.mining_request_snapshot import read_snapshot
    from app.prepared_mining_request import prepare_request
    snapshot=read_snapshot(factory,UUID(data['sid']),data['token'],UUID(data['rid']),require_metadata=True)
    request=prepare_request(snapshot)
    with factory.begin() as db:
        put(db,snapshot,request,crash_at=(lambda:os._exit(41)) if data['mode']=='before_commit' else None)
    # Abrupt process exit after COMMIT, no finally/dispose; intentional crash.
    os._exit(42)


if __name__=='__main__':
    try: main()
    except Exception:
        print('OFFLINE_MANIFEST_WORKER_STOPPED')
        sys.exit(3)
