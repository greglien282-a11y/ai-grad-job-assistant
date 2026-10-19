"""Subprocess-only crash/recovery fixture; accepts only synthetic test LOGINs."""
import ctypes
import json
import os
import socket
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))


def main():
    warnings.filterwarnings('ignore', category=DeprecationWarning)
    import httpx
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    def forbidden(*args, **kwargs):
        raise RuntimeError('offline_test_access_denied')

    data = json.load(sys.stdin)
    url = make_url(data['url'])
    assert url.host == '127.0.0.1' and url.database in ('pathwise_test', 'pathwise_e2e')
    assert url.username.startswith('b2b_run_') and data['schema'].startswith('test_')
    assert len(data['schema']) == 37 and all(c in '0123456789abcdef' for c in data['schema'][5:])
    lookup = socket.getaddrinfo
    def database_only(host, port, *args, **kwargs):
        if host != url.host or str(port) != str(url.port or 5432):
            return forbidden()
        return lookup(host, port, *args, **kwargs)
    socket.getaddrinfo = database_only
    socket.create_connection = forbidden
    ctypes.WinDLL = forbidden
    httpx.HTTPTransport.handle_request = forbidden
    httpx.AsyncHTTPTransport.handle_async_request = forbidden
    with warnings.catch_warnings(record=True) as notices:
        from fastapi.testclient import TestClient
        from app.main import app
        from app.maintenance_api import get_maintenance_factory
    if any(not str(w.message).startswith('Using `httpx` with `starlette.testclient` is deprecated') for w in notices):
        raise RuntimeError('offline_worker_import_warning')

    engine = create_engine(url, hide_parameters=True, poolclass=NullPool,
                           connect_args={'options': '-csearch_path='+data['schema']})
    factory = sessionmaker(engine, expire_on_commit=False)
    app.dependency_overrides[get_maintenance_factory] = lambda: factory
    if data['mode'] in ('before_commit', 'after_commit'):
        event.listen(factory, data['mode'], lambda db: os._exit(71 if data['mode']=='before_commit' else 72))
    with TestClient(app) as client:
        path = '/api/v1/experience/sessions/'+data['sid']+'/conversation-operations'
        if data['mode'] == 'recover':
            response = client.get(path+'/recovery', headers=data['headers'])
        else:
            response = client.post(path, headers=data['headers'], json=data['body'])
        print(json.dumps({'status': response.status_code, 'result': response.json()}))
    engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('OFFLINE_WORKER_STOPPED')
        sys.exit(90)
