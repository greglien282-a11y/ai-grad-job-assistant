"""Test-only ASGI identity wrapper. The real app/contracts remain unchanged."""
import json
import os
import asyncio
from pathlib import Path

from sqlalchemy.engine import make_url
from environment import validate_url
from app.main import app as real_app
from fastapi import Request
from app.mining_api import get_provider, get_mining_factory
from app.experience_api import get_db
from app.mining_provider import ScriptedProvider, MiningOutput
from app.experience_read_api import get_read_factory
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

config = json.loads(Path(os.environ['PATHWISE_E2E_RUN_FILE']).read_text(encoding='utf-8'))
url = make_url(os.environ['DATABASE_URL'])
validate_url(url.set(query={}).render_as_string(hide_password=False))
if url.render_as_string(hide_password=False) != config['database_url']:
    raise RuntimeError('E2E API database configuration mismatch')


class ScenarioScriptedProvider(ScriptedProvider):
    """Explicit zero-cost fault fixtures, only in this isolated test server.

    No adapter, HTTP transport or real model. Production get_provider is unchanged.
    """
    def __init__(self, scenario):
        self.scenario = scenario

    async def mine(self, context):
        if self.scenario == 'invalid':
            raise ValueError('Synthetic invalid output')
        if self.scenario == 'unknown':
            raise asyncio.TimeoutError()
        if self.scenario == 'delayed':
            await asyncio.sleep(2)
        result = await super().mine(context)
        if self.scenario == 'empty':
            return MiningOutput(candidates=[], questions=result.questions)
        return result


def isolated_provider(request: Request):
    provider = get_provider()  # Keep original enabled/scripted configuration gate.
    scenario = request.headers.get('x-pathwise-e2e-scenario')
    if not scenario:
        return provider
    if os.environ.get('PATHWISE_E2E') != '1' or scenario not in ('invalid', 'unknown', 'delayed', 'empty') or type(provider) is not ScriptedProvider:
        raise RuntimeError('Isolated synthetic fixture refused')
    return ScenarioScriptedProvider(scenario)


real_app.dependency_overrides[get_provider] = isolated_provider

# Only this isolated ASGI wrapper injects the run-owned SELECT-only LOGIN.
if 'reader_url' in config:
    reader_url=make_url(config['reader_url'])
    if (reader_url.host,reader_url.port,reader_url.database,reader_url.query)!=(url.host,url.port,url.database,url.query):
        raise RuntimeError('Isolated reader target mismatch')
    reader=sessionmaker(create_engine(reader_url,poolclass=NullPool,hide_parameters=True),expire_on_commit=False)
    def isolated_reader(request:Request):
        if request.headers.get('x-pathwise-e2e-read-disabled')=='1':return get_read_factory()
        return reader
    real_app.dependency_overrides[get_read_factory]=isolated_reader

if 'legacy_read_url' in config:
    legacy_url=make_url(config['legacy_read_url'])
    if (legacy_url.host,legacy_url.port,legacy_url.database,legacy_url.query)!=(url.host,url.port,url.database,url.query):
        raise RuntimeError('Isolated legacy reader target mismatch')
    legacy_reader=sessionmaker(create_engine(legacy_url,poolclass=NullPool,hide_parameters=True),expire_on_commit=False)
    def isolated_legacy_db(request:Request):
        if request.method=='GET' and request.headers.get('x-pathwise-e2e-legacy-read')=='1':
            with legacy_reader() as db,db.begin():yield db
        else:yield from get_db()
    def isolated_mining_factory(request:Request):
        return legacy_reader if request.method=='GET' and request.headers.get('x-pathwise-e2e-legacy-read')=='1' else get_mining_factory()
    real_app.dependency_overrides[get_db]=isolated_legacy_db
    real_app.dependency_overrides[get_mining_factory]=isolated_mining_factory


class IsolatedApp:
    async def __call__(self, scope, receive, send):
        async def marked(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': message.get('headers', []) + [(b'x-pathwise-e2e-run', config['schema'].encode())]}
            await send(message)
        await real_app(scope, receive, marked)


app = IsolatedApp()
