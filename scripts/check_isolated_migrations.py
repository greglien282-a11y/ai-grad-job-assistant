"""CI migration/check/cleanup smoke, only a fresh test schema."""
import os
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from sqlalchemy import text
from app.offline_evaluation import isolated_database
from app.cleanup_idempotency import run

with isolated_database(os.environ.get('TEST_DATABASE_URL')) as factory:
    with factory() as db:
        schema=db.scalar(text('SELECT current_schema()'))
        if not schema.startswith('test_eval_'): raise SystemExit('isolation_required')
    # Exercise the unchanged maintenance function with the scoped engine, never
    # let build_engine resolve daily DATABASE_URL or .env as a fallback.
    with patch('app.cleanup_idempotency.build_engine',return_value=factory.kw['bind']):run()
print('Isolated migration upgrade/check and existing cleanup smoke passed')
