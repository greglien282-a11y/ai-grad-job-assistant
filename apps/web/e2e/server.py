"""Test-only ASGI identity wrapper. The real app/contracts remain unchanged."""
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url
from environment import validate_url
from app.main import app as real_app

config = json.loads(Path(os.environ['PATHWISE_E2E_RUN_FILE']).read_text(encoding='utf-8'))
url = make_url(os.environ['DATABASE_URL'])
validate_url(url.set(query={}).render_as_string(hide_password=False))
if url.render_as_string(hide_password=False) != config['database_url']:
    raise RuntimeError('E2E API database configuration mismatch')


class IsolatedApp:
    async def __call__(self, scope, receive, send):
        async def marked(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': message.get('headers', []) + [(b'x-pathwise-e2e-run', config['schema'].encode())]}
            await send(message)
        await real_app(scope, receive, marked)


app = IsolatedApp()
