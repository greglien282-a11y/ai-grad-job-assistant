"""Fail-closed real E2E environment. Never read DATABASE_URL as a fallback.

Only a fresh run-owned schema in a dedicated test database may be modified.
Children receive isolated config; diagnostics never print connection URLs.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / 'apps/api'
WEB = ROOT / 'apps/web'
PRIVATE = ROOT / '.e2e'
PORTS = (18000, 15173)


def validate_url(value):
    if not value:
        raise ValueError('Explicit E2E test database required')
    url = make_url(value)
    if (url.get_backend_name() != 'postgresql' or url.host not in ('localhost', '127.0.0.1')
            or url.database not in ('pathwise_test', 'pathwise_e2e') or url.query
            or url.username in (None, 'postgres', 'pathwise_dev')):
        raise ValueError('E2E requires a loopback dedicated test DB/non-admin role, without URL options')
    return url.set(drivername='postgresql+psycopg')


def validate_ports():
    for port in PORTS:
        with socket.socket() as check:
            check.bind(('127.0.0.1', port))


def stop(child):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def wait_ready(url, child, marker=None):
    for _ in range(100):
        if child.poll() is not None:
            raise RuntimeError('Isolated service exited before readiness')
        try:
            response = httpx.get(url, timeout=1)
            if response.status_code == 200 and (marker is None or response.headers.get('x-pathwise-e2e-run') == marker):
                return
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    raise RuntimeError('Isolated service failed readiness')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manual', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    stop_file = Path(os.environ['PATHWISE_E2E_STOP_FILE'])
    if stop_file.parent.resolve() != PRIVATE.resolve() or not re.fullmatch(r'stop_[0-9a-f-]{36}', stop_file.name):
        raise ValueError('Invalid launcher stop marker')
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Python 3.12 required for E2E')
    # Developer .env is consulted ONLY for its explicit TEST_DATABASE_URL.
    value = os.getenv('PATHWISE_E2E_DATABASE_URL')
    if value is None and not os.getenv('CI'):
        value = dotenv_values(API / '.env').get('TEST_DATABASE_URL')
    url = validate_url(value)
    if os.getenv('VITE_API_BASE_URL'):
        raise ValueError('E2E refuses external frontend API override')
    for name in ('.env', '.env.local', '.env.e2e', '.env.e2e.local'):
        if dotenv_values(WEB / name).get('VITE_API_BASE_URL'):
            raise ValueError('E2E refuses frontend API override in env files')
    engine = create_engine(url, hide_parameters=True, connect_args={'connect_timeout': 3})
    with engine.connect() as db:
        actual = db.execute(text('SELECT current_database(), current_user, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')).one()
        if actual[0] != url.database or actual[1] != url.username or any(actual[2:]):
            raise ValueError('Actual database identity is not a non-admin test environment')
    validate_ports()
    print('Isolation preflight passed: test database, non-admin role, dedicated ports', flush=True)
    if args.preflight:
        engine.dispose()
        return 0
    schema = 'pathwise_e2e_' + uuid4().hex
    created = False
    api = vite = tests = None
    PRIVATE.mkdir(exist_ok=True)
    run_file = PRIVATE / (schema + '.json')
    log = None
    typed_config = None
    try:
        with engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        isolated = url.update_query_dict({'options': f'-csearch_path={schema} -cstatement_timeout=10000'})
        config = {'database_url': isolated.render_as_string(hide_password=False), 'schema': schema,
                  'api_origin': 'http://127.0.0.1:18000', 'web_origin': 'http://127.0.0.1:15173'}
        run_file.write_text(json.dumps(config), encoding='utf-8')
        run_file.chmod(0o600)
        if os.name == 'nt':
            identity = subprocess.check_output(['whoami'], text=True).strip()
            subprocess.run(['icacls', str(run_file), '/inheritance:r', '/grant:r', identity + ':F'], check=True, stdout=subprocess.DEVNULL)
        env = {**os.environ, 'DATABASE_URL': config['database_url'], 'PATHWISE_E2E': '1',
               'PATHWISE_E2E_RUN_FILE': str(run_file), 'CORS_ORIGINS': config['web_origin'], 'REQUIRE_HTTPS': 'false',
               'AI_ENABLED': 'true', 'AI_PROVIDER': 'scripted'}
        # Migration exceptions are suppressed at the outer boundary: no URL/SQL in output.
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=API, env=env,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sys.path.insert(0,str(API))
        from typed_support import provision, cleanup
        if not args.manual:
            typed_config=provision(isolated,schema)
            config.update(typed_config)
            run_file.write_text(json.dumps(config),encoding='utf-8')
        # Owner-only provisioning credentials never reach the HTTP/Vite children.
        service_env={k:v for k,v in env.items() if k not in ('E2E_ADMIN_PASSWORD','PATHWISE_E2E_PROVISION_URL','TEST_DATABASE_URL')}
        log = (PRIVATE / (schema + '.services.log')).open('w', encoding='utf-8')
        api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--app-dir', str(WEB / 'e2e'), '--host', '127.0.0.1', '--port', '18000', '--no-access-log'],
                               cwd=API, env=service_env, stdout=log, stderr=log)
        wait_ready(config['api_origin'] + '/api/v1/health', api, schema)
        # Verify the actual factory and database before allowing a browser to open.
        subprocess.run([sys.executable, str(WEB / 'e2e/probe.py'), 'preflight'], env=env,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        node = os.environ.get('PATHWISE_E2E_NODE')
        if not node:
            raise ValueError('Use the Node E2E launcher')
        web_env = {key: val for key, val in service_env.items() if key not in ('DATABASE_URL', 'PATHWISE_E2E_DATABASE_URL', 'TEST_DATABASE_URL')}
        web_env['VITE_API_BASE_URL'] = ''
        vite = subprocess.Popen([node, str(WEB / 'node_modules/vite/bin/vite.js'), '--mode', 'e2e'], cwd=WEB, env=web_env, stdout=log, stderr=log)
        wait_ready(config['web_origin'], vite)
        wait_ready(config['web_origin'] + '/api/v1/health', vite, schema)
        if args.manual:
            print('Edge manual preview: http://127.0.0.1:15173 (isolated synthetic data only). Ctrl+C stops and removes this run schema.', flush=True)
            while api.poll() is None and vite.poll() is None:
                if stop_file.exists():
                    print('Isolated preview stopping and removing its schema', flush=True)
                    return 0
                time.sleep(.5)
            raise RuntimeError('Manual preview service exited')
        tests = subprocess.Popen([node, str(WEB / 'node_modules/@playwright/test/cli.js'), 'test'], cwd=WEB,
                                 env={**env, 'PATHWISE_E2E_PYTHON': sys.executable})
        while tests.poll() is None:
            if stop_file.exists():
                return 130
            time.sleep(.2)
        return tests.returncode
    finally:
        stop(tests)
        stop(vite)
        stop(api)
        if log:
            log.close()
        if typed_config:cleanup(isolated,schema,typed_config)
        run_file.unlink(missing_ok=True)
        if created:
            # Never accept cleanup targets from a config file or user input.
            if not re.fullmatch(r'pathwise_e2e_[0-9a-f]{32}', schema):
                raise RuntimeError('Refused unsafe cleanup target')
            with engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Isolated preview stopped; cleanup completed', flush=True)
        sys.exit(0)
    except Exception:
        print('E2E environment refused/failed. No fallback to development services. Check test DB/ports/configuration privately.', file=sys.stderr)
        sys.exit(2)
