"""Disposable graph-stability mitigation. NOT a strict COMMIT clock guarantee.

Provisioner only, outside requests. Does not change any formal schema or role.
One operation per xid narrows the demonstrated multi-operation seal drift;
SET CONSTRAINTS can STILL drain clock checks. A trusted commit owner is required.
"""
from psycopg import sql


def install(x):
    m = x.model
    m.admin.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(m.roles['owner'])))
    try:
        m.admin.execute(sql.SQL('CREATE UNIQUE INDEX g4_one_operation_per_transaction ON {}(created_xid)').format(sql.Identifier(m.schema, 'ref_operations')))
    finally:
        m.admin.execute('RESET ROLE')


def verify(db, x):
    # A NOT DEFERRABLE unique index, not another deferred INSERT check.
    index = db.execute('''SELECT i.indisunique,i.indisvalid,i.indimmediate,pg_get_indexdef(i.indexrelid) AS definition
      FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
      WHERE i.indrelid=%s::regclass AND c.relname='g4_one_operation_per_transaction' ''', (x.model.schema+'.ref_operations',)).fetchone()
    if not index or not all(index[k] for k in ('indisunique','indisvalid','indimmediate')) or not index['definition'].endswith('(created_xid)'):
        from research.g3_choice_protocol.runtime import Refused
        raise Refused('transaction_guard_unavailable')
