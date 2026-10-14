"""Provision a restricted role in the fresh CI-only PostgreSQL service."""
import os
from pathlib import Path
import secrets

import psycopg
from psycopg import sql


def main():
    if os.getenv('CI') != 'true' or not os.getenv('GITHUB_ENV'):
        raise ValueError('CI-only database bootstrap')
    password = secrets.token_urlsafe(32)
    # The service password is synthetic, scoped to this disposable CI job.
    with psycopg.connect(host='127.0.0.1', port=5432, dbname='postgres', user='postgres',
                        password=os.environ['E2E_ADMIN_PASSWORD'], autocommit=True) as db:
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname='pathwise_e2e'").fetchone() or db.execute("SELECT 1 FROM pg_database WHERE datname='pathwise_e2e'").fetchone():
            raise ValueError('Refuse to reuse existing database or role')
        db.execute(sql.SQL('CREATE ROLE pathwise_e2e LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Literal(password)))
        db.execute('CREATE DATABASE pathwise_e2e OWNER pathwise_e2e')
        db.execute('REVOKE CONNECT ON DATABASE pathwise_e2e FROM PUBLIC')
    url = f'postgresql+psycopg://pathwise_e2e:{password}@127.0.0.1:5432/pathwise_e2e'
    print('::add-mask::' + password, flush=True)
    print('::add-mask::' + url, flush=True)
    with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as output:
        output.write('PATHWISE_E2E_DATABASE_URL=' + url + '\n')
    print('Created dedicated CI database and restricted role')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('CI database bootstrap refused/failed; connection details suppressed')
