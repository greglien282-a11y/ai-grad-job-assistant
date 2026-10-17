"""TEST ONLY plaintext synthetic body appliance. NOT production secure storage.

Lives solely in a disposable test DB/random schema, has no secret or HTTP code.
Do not import from API, provider, CLI or any production storage factory.
"""
import re
from uuid import UUID
from sqlalchemy import select,text
from app import facts
from app.models import ExperienceSession,MiningRun,utcnow
from app.request_manifest_models import RequestManifest
from app.request_manifest import (persist_metadata,manifest_record,verify_recovered,ManifestError)


def guard(db):
    name,schema=db.execute(text('SELECT current_database(),current_schema()')).one()
    if name not in ('pathwise_test','pathwise_e2e') or not re.fullmatch(r'test_[a-f0-9]{32}',schema):
        raise ManifestError('manifest_unavailable')


def install(db):
    guard(db)
    db.execute(text('''CREATE TABLE test_synthetic_request_bodies (
      run_id uuid PRIMARY KEY REFERENCES mining_request_manifests(run_id) ON DELETE CASCADE,
      fixture_kind text NOT NULL CHECK(fixture_kind='synthetic-only-no-production'),
      body bytea NOT NULL CHECK(octet_length(body) BETWEEN 1 AND 192000))'''))
    db.execute(text('REVOKE ALL ON test_synthetic_request_bodies FROM PUBLIC'))
    grantees=db.execute(text('''SELECT DISTINCT r.rolname FROM pg_class c
      CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
      JOIN pg_roles r ON r.oid=a.grantee
      WHERE c.oid='test_synthetic_request_bodies'::regclass AND a.grantee<>c.relowner''')).scalars()
    for name in grantees:
        quoted=db.get_bind().dialect.identifier_preparer.quote_identifier(name)
        db.execute(text(f'REVOKE ALL ON test_synthetic_request_bodies FROM {quoted}'))


def put(db,current,prepared,*,crash_at=None):
    guard(db)
    db.scalar(select(ExperienceSession).where(ExperienceSession.id==current.session_id)
        .with_for_update().execution_options(populate_existing=True))
    prior=db.get(RequestManifest,current.run_id)
    row=persist_metadata(db,current,prepared)
    body=db.scalar(text('SELECT body FROM test_synthetic_request_bodies WHERE run_id=:r'),{'r':row.run_id})
    if body is None:
        if prior is not None: raise ManifestError('manifest_bytes_unavailable')
        db.execute(text("INSERT INTO test_synthetic_request_bodies VALUES(:r,'synthetic-only-no-production',:b)"),
            {'r':row.run_id,'b':prepared.body})
    elif bytes(body)!=prepared.body:
        raise ManifestError('manifest_conflict')
    if crash_at: crash_at()  # injected only by isolated test worker
    return manifest_record(row)


def recover(db,sid,token,rid,root,operation):
    """SELECT-only, locking transaction; NOT PostgreSQL READ ONLY mode.

    Session SHARE -> Run SHARE -> Manifest SHARE serializes with deletion.
    Returned memory is a point-in-time copy, not revocable future dispatch power.
    """
    # SELECT ORM queries would otherwise autoflush an unrelated dirty caller.
    if db.new or db.dirty or db.deleted: raise ManifestError('manifest_unavailable')
    guard(db)
    session=db.scalar(select(ExperienceSession).where(ExperienceSession.id==sid)
        .with_for_update(read=True).execution_options(populate_existing=True))
    if session is None: raise ManifestError('manifest_unavailable')
    try: facts.authorize(db,sid,token)
    except Exception: raise ManifestError('manifest_unavailable') from None
    run=db.scalar(select(MiningRun).where(MiningRun.id==rid)
        .with_for_update(read=True).execution_options(populate_existing=True))
    if (run is None or run.session_id!=sid or run.state!='running' or run.lease_until<=utcnow()
        or session.status!='active' or session.mining_status!='active'
        or session.context_revision!=run.reserved_revision): raise ManifestError('manifest_business_inactive')
    row=db.scalar(select(RequestManifest).where(RequestManifest.run_id==rid)
        .with_for_update(read=True).execution_options(populate_existing=True))
    if (row is None or row.session_id!=sid or row.root_run_id!=root or row.operation_hash!=operation
        or row.context_revision!=session.context_revision): raise ManifestError('manifest_unavailable')
    body=db.scalar(text('SELECT body FROM test_synthetic_request_bodies WHERE run_id=:r'),{'r':rid})
    if body is None: raise ManifestError('manifest_bytes_unavailable')
    return verify_recovered(manifest_record(row),bytes(body),lookup=(sid,rid,root,operation))
