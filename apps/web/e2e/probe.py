"""Direct PostgreSQL audit for E2E; outputs no tokens, hashes or connection data."""
import json
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from environment import validate_url


def main():
    config = json.loads(Path(os.environ['PATHWISE_E2E_RUN_FILE']).read_text(encoding='utf-8'))
    url = make_url(config['database_url'])
    validate_url(url.set(query={}).render_as_string(hide_password=False))
    schema = config['schema']
    import re
    if not re.fullmatch(r'pathwise_e2e_[0-9a-f]{32}', schema) or url.query.get('options') != f'-csearch_path={schema} -cstatement_timeout=10000':
        raise ValueError('Invalid isolated schema configuration')
    engine = create_engine(url, hide_parameters=True)
    with engine.connect() as db:
        if db.scalar(text('SELECT current_schema()')) != schema:
            raise ValueError('Schema mismatch')
        if sys.argv[1] == 'preflight':
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0008_paid_authority'
            return
        if sys.argv[1] == 'reset':
            db.execute(text('DELETE FROM ai_mining_receipts'))
            # Only this validated run-owned schema; remove live receipt FKs first.
            db.execute(text('DELETE FROM idempotency_operations'))
            db.execute(text('DELETE FROM experience_sessions'))
            db.commit()
            return
        if sys.argv[1] == 'mining-audit':
            print(json.dumps({
                'runs': [dict(r) for r in db.execute(text('SELECT id::text,input_turn_id::text,state FROM ai_mining_runs ORDER BY created_at')).mappings()],
                'answers': [dict(r) for r in db.execute(text('SELECT turn_id::text,question_id::text,question_version FROM ai_answer_questions ORDER BY slot')).mappings()],
                'questions': [dict(r) for r in db.execute(text('SELECT id::text,state,content,version FROM ai_mining_questions ORDER BY created_at')).mappings()],
                'user_turns': db.scalar(text("SELECT count(*) FROM conversation_turns WHERE role='user'")),
            }, ensure_ascii=True))
            return
        output = {'sessions': [dict(r) for r in db.execute(text('SELECT id::text,status FROM experience_sessions ORDER BY created_at')).mappings()],
                  'facts': [dict(r) for r in db.execute(text('SELECT id::text,statement,status,version FROM experience_facts ORDER BY created_at')).mappings()],
                  'turns': db.scalar(text('SELECT count(*) FROM conversation_turns')),
                  'history': db.scalar(text('SELECT count(*) FROM fact_changes')),
                  'changes': [dict(r) for r in db.execute(text('SELECT id::text,action,"before","after" FROM fact_changes ORDER BY created_at')).mappings()],
                  'materials': [dict(r) for r in db.execute(text('SELECT material_reference,basis,reviewer FROM fact_evidence ORDER BY created_at')).mappings()],
                  'original_sources': sorted(db.scalars(text('SELECT turn_id::text FROM fact_sources')).all()),
                  'evidence': db.scalar(text('SELECT count(*) FROM fact_evidence')),
                  'sources': db.scalar(text('SELECT count(*) FROM fact_sources')),
                  'projects': db.scalar(text('SELECT count(*) FROM experience_projects'))}
        print(json.dumps(output, ensure_ascii=True))
    engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Isolated database probe failed', file=sys.stderr)
        sys.exit(2)
