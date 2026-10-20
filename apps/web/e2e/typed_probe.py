"""Private synthetic fixtures/faults. No HTTP writer and no production imports."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from typed_support import owner_engine


def main():
    config=json.loads(Path(os.environ['PATHWISE_E2E_RUN_FILE']).read_text(encoding='utf-8'))
    url=make_url(config['database_url']);engine=owner_engine(url,config['schema'])
    s=SimpleNamespace(admin=sessionmaker(engine,expire_on_commit=False))
    action=sys.argv[1]
    try:
        if action=='audit':
            import hashlib
            with engine.connect() as db:
                tables=db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename")).all()
                values={t:db.scalars(text(f'SELECT to_jsonb(t)::text FROM "{t}" t ORDER BY to_jsonb(t)::text')).all() for t in tables}
            # Compare every table, including fees/keys/revisions, without emitting content.
            print(json.dumps({'digest':hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()}));return
        api=Path(__file__).resolve().parents[2]/'api'
        sys.path[:0]=[str(api),str(api/'tests')]
        from test_experience_read import synthetic, corrupt
        from test_maintenance_api import seed
        from test_fact_classification import VALID
        if action=='seed':
            b=seed(s,status='user_confirmed');foreign=seed(s)
            ids=[synthetic(s,b,v) for v in VALID]
            pending=synthetic(s,b,VALID[3],'pending');material=synthetic(s,b,VALID[3],'evidence_supported');rejected=synthetic(s,b,VALID[3],'rejected')
            print(json.dumps(dict(sessionId=str(b.sid),projectId=str(b.pid),token=b.token,foreignToken=foreign.token,
                                 ids=list(map(str,ids)),pending=str(pending),material=str(material),rejected=str(rejected))));return
        with engine.begin() as db:
            role=config['read_role']
            if action=='permission-off':db.execute(text(f'REVOKE SELECT ON fact_sources FROM "{role}"'))
            elif action=='permission-on':db.execute(text(f'GRANT SELECT ON fact_sources TO "{role}"'))
            elif action=='schema-off':db.execute(text("COMMENT ON TABLE experience_facts IS 'pathwise-classification-schema-v99'"))
            elif action=='schema-on':db.execute(text("COMMENT ON TABLE experience_facts IS 'pathwise-classification-schema-v1'"))
            elif action!='corrupt':raise ValueError('Unknown fixture action')
        if action=='corrupt':
            with engine.connect() as db:fid=db.scalar(text("SELECT id FROM experience_facts WHERE classification_contract='explicit-typed-v1' ORDER BY created_at LIMIT 1"))
            corrupt(s,'fact_changes',"UPDATE fact_changes SET after=after-'memory_state' WHERE fact_id=:id",{'id':fid})
    finally:engine.dispose()


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Synthetic typed fixture failed; details suppressed')
