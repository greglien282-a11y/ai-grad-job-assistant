"""M3 real read-only failures, NOT proof of future typed writer transactions."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import ast

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app import facts
from app.experience_read_api import read, get_read_factory
from app.maintenance_errors import ConversationError
from app.models import ExperienceSession
from test_http_api import api
from test_maintenance_api import service, seed
from test_append_api import append_service
from test_experience_read import reader, synthetic, corrupt
from test_legacy_upgrade_handoff import digest


def get(s,b,kind):
    return read(s.reader,b.token,**({'sid':b.sid,'fid':b.fid} if kind=='fact'
        else {'pid':b.pid} if kind=='summary' else {'sid':b.sid}))


@pytest.mark.parametrize('kind',['fact','summary','export'])
@pytest.mark.parametrize('fault',['source_deleted','source_permission','turn_permission','labels',
    'history_version','unknown_schema','source_range','missing_created'])
def test_executable_isolated_read_failure_no_partial_or_business_effect(reader,kind,fault):
    s=reader;b=seed(s);fid=synthetic(s,b)
    if fault=='source_deleted':corrupt(s,'fact_sources','DELETE FROM fact_sources WHERE fact_id=:id',{'id':fid})
    elif fault=='source_range':corrupt(s,'fact_sources',"UPDATE fact_sources SET citations=jsonb_set(citations,'{0,start}','false') WHERE fact_id=:id",{'id':fid})
    elif fault=='history_version':corrupt(s,'fact_changes',"UPDATE fact_changes SET after=jsonb_set(after,'{version}','\"2\"') WHERE fact_id=:id AND action<>'created'",{'id':fid})
    elif fault=='missing_created':corrupt(s,'fact_changes',"DELETE FROM fact_changes WHERE fact_id=:id AND action='created'",{'id':fid})
    elif fault=='labels':corrupt(s,'experience_facts',"UPDATE experience_facts SET fact_kind='legacy_unspecified',progress_stage='legacy_unknown',classification_contract='legacy-v0' WHERE id=:id",{'id':fid})
    else:
        with s.admin.begin() as db:
            if fault=='unknown_schema':db.execute(text("COMMENT ON TABLE experience_facts IS 'pathwise-classification-schema-v99'"))
            else:db.execute(text(f'REVOKE SELECT ON {"conversation_turns" if fault=="turn_permission" else "fact_sources"} FROM "{s.read_role}"'))
    before=digest(s.admin)
    # Even a fact request for an otherwise good legacy fact validates the
    # entire session. Damaged typed siblings cannot disappear in a partial read.
    with pytest.raises(ConversationError) as exc:get(s,b,kind)
    assert exc.value.status==503
    expected=('fact_classification_schema_unavailable' if fault=='unknown_schema'
        else 'experience_read_runtime_unapproved' if fault in ('source_permission','turn_permission')
        else 'experience_read_integrity_unavailable')
    assert exc.value.code==expected
    assert digest(s.admin)==before
    token=b.token;b.token='foreign'
    try:
        with pytest.raises(PermissionError):get(s,b,kind)
    finally:b.token=token
    assert digest(s.admin)==before


@pytest.mark.parametrize('kind',['fact','summary','export'])
def test_observed_typed_basis_is_missing_not_verified_and_reads_are_zero_effect(reader,kind):
    s=reader;b=seed(s);fid=synthetic(s,b);before=digest(s.admin);result=get(s,b,kind)
    if kind=='fact':
        assert result.id==b.fid and result.classification_basis_status=='legacy_unclassified'
        assert result.classification_citations==[]
        assert digest(s.admin)==before
        # The helper reads the legacy sibling; explicitly read the typed fact too.
        typed=read(s.reader,b.token,sid=b.sid,fid=fid)
        assert typed.id==fid
        facts_out=[typed]
    elif kind=='summary':facts_out=[*result.confirmed,*result.pending,*[i.fact for i in result.reviewed_non_contributions]]
    else:facts_out=result.data.facts
    fact=next(f for f in facts_out if f.id==fid)
    assert fact.classification_citations==[] and fact.classification_basis_status=='not_recorded'
    assert all(f.classification_citations==[] for f in facts_out)
    assert digest(s.admin)==before


def test_executable_select_only_login_cannot_remove_source_turn(reader):
    s=reader;b=seed(s);before=digest(s.admin)
    # A capability rejection on the real runtime role. No owner request and no
    # grant/trigger relaxation is used to manufacture a successful deletion.
    with pytest.raises(DBAPIError) as exc,s.reader.begin() as db:
        db.execute(text('DELETE FROM conversation_turns WHERE id=:id'),{'id':b.tid})
    assert exc.value.orig.sqlstate=='42501' and digest(s.admin)==before


def test_default_factory_remains_closed_and_no_test_runtime_is_installed():
    with pytest.raises(ConversationError) as exc:get_read_factory()
    assert exc.value.code=='experience_read_disabled'
    root=Path(__file__).parents[1]/'app'
    for file in root.rglob('*.py'):
        tree=ast.parse(file.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):assert 'overnight_research' not in (node.module or '')
            elif isinstance(node,ast.Import):assert all('overnight_research' not in x.name for x in node.names)


def test_real_snapshot_consistency_does_not_supply_future_write_admission(reader):
    s=reader;b=seed(s);fired=False;queries=[]
    def writer():
        with s.admin.begin() as db:facts.change_fact(db,b.fid,b.token,status='rejected',expected_version=1)
    def interleave(conn,cursor,sql,params,context,many):
        nonlocal fired
        queries.append(sql)
        if not fired and 'FROM experience_facts' in sql:
            fired=True
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(writer).result(timeout=10)
    event.listen(s.read_engine,'before_cursor_execute',interleave)
    try:old=get(s,b,'summary')
    finally:event.remove(s.read_engine,'before_cursor_execute',interleave)
    assert fired and old.pending[0].status=='pending' and old.context_revision==b.revision
    before=digest(s.admin);new=get(s,b,'summary')
    assert new.pending==[] and new.context_revision>old.context_revision
    assert digest(s.admin)==before
    assert not any(word in sql.upper() for sql in queries for word in ('FOR UPDATE','PG_ADVISORY','INSERT ','UPDATE ','DELETE '))
