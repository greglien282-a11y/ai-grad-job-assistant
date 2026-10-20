"""Independent Fact v3: same complete projection, real SELECT-only LOGIN."""
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.experience_read_api import get_read_factory
from app.main import app
from app.read_permissions import READ_TABLES
from test_experience_read import reader, summary, export, corrupt, synthetic
from test_maintenance_api import seed, service, error
from test_append_api import append_service
from test_http_api import api
from test_fact_classification import VALID
from test_fact_source_maintenance import stored


def get(s,b,fid=None,token=None):
    return s.client.get(f'/api/v2/experience/sessions/{b.sid}/facts/{fid or b.fid}',
                        headers={'Authorization':'Bearer '+(token or b.token)})


@pytest.mark.parametrize('values',VALID)
@pytest.mark.parametrize('status',['pending','user_confirmed','evidence_supported','rejected'])
def test_fact_is_exact_same_v3_as_complete_export_and_summary(reader,values,status):
    s=reader;b=seed(s);fid=synthetic(s,b,values,status);state=stored(s.admin)
    r=get(s,b,fid);assert r.status_code==200,r.text
    f=r.json();out=export(s,b).json()['data']
    assert f==next(f for f in out['facts'] if f['id']==str(fid))
    body=summary(s,b).json()
    listed=body['confirmed']+body['pending']+[e['fact'] for e in body['reviewed_non_contributions']]
    assert (f in listed)==(status!='rejected')
    assert f['classification_citations']==[] and r.headers['cache-control']=='no-store'
    assert stored(s.admin)==state


@pytest.mark.parametrize('damage',['history','schema','permission','unrelated_history'])
def test_auth_and_fact_session_ownership_precede_damage(reader,damage):
    s=reader;b=seed(s);other=seed(s);fid=synthetic(s,b);another=synthetic(s,b)
    if damage in ('history','unrelated_history'):
        corrupt(s,'fact_changes',"UPDATE fact_changes SET after=after-'memory_state' WHERE fact_id=:id",{'id':fid if damage=='history' else another})
    with s.admin.begin() as db:
        if damage=='schema':db.execute(text("COMMENT ON TABLE experience_facts IS 'pathwise-classification-schema-v99'"))
        if damage=='permission':db.execute(text(f'REVOKE SELECT ON fact_sources FROM "{s.read_role}"'))
    state=stored(s.admin)
    error(get(s,b,fid,other.token),404,'resource_unavailable')
    error(get(s,b,other.fid),404,'resource_unavailable')
    error(get(s,b,uuid4()),404,'resource_unavailable')
    assert get(s,b,fid).status_code==503
    assert stored(s.admin)==state


@pytest.mark.parametrize('table',READ_TABLES)
def test_missing_read_permission_never_degrades_to_partial_fact(reader,table):
    s=reader;b=seed(s);state=stored(s.admin)
    with s.admin.begin() as db:db.execute(text(f'REVOKE SELECT ON {table} FROM "{s.read_role}"'))
    assert get(s,b).status_code==503
    assert stored(s.admin)==state


def test_default_disabled_no_negotiation_and_real_readonly_transaction(reader):
    s=reader;b=seed(s);queries=[]
    def capture(conn,cursor,sql,params,context,many):queries.append(sql)
    event.listen(s.read_engine,'before_cursor_execute',capture)
    try:assert get(s,b).status_code==200
    finally:event.remove(s.read_engine,'before_cursor_execute',capture)
    assert 'SHOW transaction_read_only' in queries and 'SHOW transaction_isolation' in queries
    assert not any(any(w in q.upper() for w in ('FOR UPDATE','ADVISORY','INSERT ','UPDATE ','DELETE ')) for q in queries)
    url=f'/api/v2/experience/sessions/{b.sid}/facts/{b.fid}'
    h={'Authorization':'Bearer '+b.token,'Accept':'application/vnd.pathwise.v1+json'}
    assert s.client.get(url,headers=h).json()['fact_contract_version']==3
    assert s.client.get(url+'?version=1',headers=h).status_code==400
    app.dependency_overrides.pop(get_read_factory)
    error(get(s,b),503,'experience_read_disabled')
