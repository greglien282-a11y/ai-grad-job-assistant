"""C2d: real v1 HTTP reads with restricted LOGIN, synthetic typed transitions.

No writer or production factory changes. The existing v1 row lock requires
UPDATE on two Session columns; this identity has no fact/Turn/Run/key DML.
"""
import hashlib
import json

import pytest
from sqlalchemy import text

from app.experience_api import get_db
from app.main import app
from app.mining_api import get_mining_factory
from test_http_api import api
from test_maintenance_api import service, seed
from test_append_api import append_service
from test_fact_classification import legacy_mining_runtime, VALID
from test_experience_read import synthetic, corrupt


def digest(factory):
    with factory() as db:
        names=db.scalars(text('SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename')).all()
        rows={name:db.scalars(text(f'SELECT to_jsonb(t)::text FROM "{name}" t ORDER BY to_jsonb(t)::text')).all() for name in names}
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize('history_only',[False,True])
def test_restricted_legacy_reads_refuse_typed_transition_without_effects(append_service,legacy_mining_runtime,history_only):
    s=append_service;b=seed(s,status='user_confirmed');foreign=seed(s)
    runtime=legacy_mining_runtime
    with runtime() as db:role=db.scalar(text('SELECT current_user'))
    with s.admin.begin() as db:
        for table in ('ai_mining_questions','ai_answer_questions'):
            db.execute(text(f'GRANT SELECT ON "{table}" TO "{role}"'))
    def limited_db():
        with runtime() as db,db.begin():yield db
    app.dependency_overrides[get_db]=limited_db
    app.dependency_overrides[get_mining_factory]=lambda:runtime
    paths=[(f'/sessions/{b.sid}','fact'),(f'/projects/{b.pid}/experience-summary','summary'),(f'/sessions/{b.sid}/export','export')]
    def get(path,token=b.token):
        return s.client.get('/api/v1/experience'+path,headers={'Authorization':'Bearer '+token})
    try:
        with runtime() as db:
            assert db.scalar(text('SELECT current_user'))!=s.role
            assert not db.scalar(text("SELECT rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user"))
            assert not db.scalar(text("SELECT has_table_privilege(current_user,'experience_facts','INSERT,UPDATE,DELETE')"))
        before=digest(s.admin)
        old=[get(path) for path,_ in paths]
        assert [r.status_code for r in old]==[200,200,200]
        assert old[0].json()['facts'][0]['statement']=='我测试了3个导出按钮。'
        assert old[1].json()['confirmed'][0]['id']==str(b.fid)
        assert old[2].json()['format_version']==1
        assert digest(s.admin)==before
        with s.admin() as db:
            legacy=db.scalars(text('SELECT to_jsonb(c)::text FROM fact_changes c WHERE fact_id=:id ORDER BY created_at,id'),{'id':b.fid}).all()
        ids=[synthetic(s,b,VALID[i]) for i in (4,6)]
        if history_only:
            for fid in ids:
                corrupt(s,'experience_facts',"UPDATE experience_facts SET fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0' WHERE id=:id",{'id':fid})
        before=digest(s.admin)
        for path,kind in paths:
            denied=get(path,foreign.token)
            assert denied.status_code==404
            assert 'upgrade_required' not in denied.text
            response=get(path)
            assert response.status_code==409
            assert response.json()['error']['code']==kind+'_contract_upgrade_required'
            assert '我制作' not in response.text
            assert digest(s.admin)==before
        with s.admin() as db:
            assert db.scalars(text('SELECT to_jsonb(c)::text FROM fact_changes c WHERE fact_id=:id ORDER BY created_at,id'),{'id':b.fid}).all()==legacy
    finally:
        app.dependency_overrides.pop(get_mining_factory,None)
