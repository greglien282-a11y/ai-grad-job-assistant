"""Owner-only synthetic provisioning. Never imported by the production app.

The HTTP child receives only a SELECT-only LOGIN. Provisioning requires the
disposable CI service credential or an explicit same-database local test URL.
"""
import os
import re
import secrets
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def owner_engine(url, schema):
    if not re.fullmatch(r'pathwise_e2e_[0-9a-f]{32}',schema):raise ValueError('Invalid test schema')
    if os.getenv('CI')=='true':
        owner=url.set(username='postgres',password=os.environ['E2E_ADMIN_PASSWORD'],query={})
    else:
        owner=make_url(os.environ['PATHWISE_E2E_PROVISION_URL'])
    if (owner.get_backend_name()!='postgresql' or owner.host not in ('127.0.0.1','localhost')
        or owner.database not in ('pathwise_test','pathwise_e2e') or owner.query
        or (owner.host,owner.port,owner.database)!=(url.host,url.port,url.database)):
        raise ValueError('Provisioner must target the same disposable database')
    engine=create_engine(owner,hide_parameters=True,connect_args={'options':f'-csearch_path={schema}'})
    with engine.connect() as db:
        if db.scalar(text('SELECT current_database()'))!=url.database:raise ValueError('Test database mismatch')
        if db.scalar(text('SELECT current_schema()'))!=schema:raise ValueError('Test schema mismatch')
    return engine


def provision(url,schema):
    from app.read_permissions import READ_TABLES
    engine=owner_engine(url,schema)
    role='c2c_read_'+uuid4().hex;owner='c2c_owner_'+uuid4().hex;password=secrets.token_urlsafe(32)
    try:
        with engine.begin() as db:
            db.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD \'{password}\' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT'))
            db.execute(text(f'CREATE ROLE "{owner}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT'))
            # CI revokes PUBLIC CONNECT on its disposable database. Do not rely
            # on a developer cluster's default ACL for the actual reader LOGIN.
            db.execute(text(f'GRANT CONNECT ON DATABASE "{url.database}" TO "{role}"'))
            db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}","{owner}"'))
            for t in READ_TABLES:db.execute(text(f'GRANT SELECT ON "{schema}".{t} TO "{role}","{owner}"'))
            db.execute(text(f'GRANT UPDATE(updated_at,context_revision) ON experience_sessions TO "{owner}"'))
            db.execute(text(f'GRANT UPDATE ON conversation_operations TO "{owner}"'))
            for fn in db.scalars(text("SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND (proname LIKE 'maintenance_%' OR proname LIKE 'classification_%')")):
                db.execute(text(f'ALTER FUNCTION {fn} OWNER TO "{owner}"'))
        return dict(reader_url=url.set(username=role,password=password).render_as_string(hide_password=False),read_role=role,read_owner=owner)
    finally:engine.dispose()


def cleanup(url,schema,config):
    engine=owner_engine(url,schema)
    try:
        with engine.begin() as db:
            # Restore only the functions in this run-owned schema before role cleanup.
            for fn in db.scalars(text("SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND (proname LIKE 'maintenance_%' OR proname LIKE 'classification_%')")):
                db.execute(text(f'ALTER FUNCTION {fn} OWNER TO "{url.username}"'))
            for key,prefix in (('read_role','c2c_read_'),('read_owner','c2c_owner_')):
                role=config[key]
                if not re.fullmatch(prefix+'[0-9a-f]{32}',role):raise ValueError('Invalid run role')
                db.execute(text(f'DROP OWNED BY "{role}" RESTRICT'));db.execute(text(f'DROP ROLE "{role}"'))
    finally:engine.dispose()
