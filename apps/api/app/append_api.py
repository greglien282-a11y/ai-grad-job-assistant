"""Independent, default-closed append factory. No environment enables it."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import fact_append, fact_maintenance as maintenance
from app.append_contract import AppendCommand, AppendResult
from app.experience_api import Token, operation_key
from app.maintenance_errors import ConversationError
from app.maintenance_permissions import check_append_runtime

router = APIRouter(prefix='/api/v1/experience', tags=['local batch append (disabled)'])


def get_append_factory():
    raise ConversationError(503, 'conversation_append_disabled')


Factory = Annotated[object, Depends(get_append_factory)]


def write(factory, sid, token, key, body):
    try:
        with factory() as db, db.begin():
            check_append_runtime(db)
            result, fresh = fact_append.apply(db, sid, token, key, body)
        return result, fresh
    except IntegrityError:
        raise ConversationError(500, 'conversation_integrity_failed') from None


def read(factory, sid, token, *, key=None, oid=None):
    with factory() as db:
        db.connection(execution_options={'isolation_level': 'REPEATABLE READ', 'postgresql_readonly': True})
        if (db.scalar(text('SHOW transaction_read_only')) != 'on'
                or db.scalar(text('SHOW transaction_isolation')) != 'repeatable read'):
            raise ConversationError(503, 'conversation_readonly_required')
        check_append_runtime(db)
        return maintenance.recover(db, sid, token, key=key, oid=oid, version=2)


@router.post('/sessions/{sid}/conversation-appends', status_code=201, response_model=AppendResult)
def submit(sid: UUID, body: AppendCommand, token: Token, request: Request, response: Response, factory: Factory):
    key, _ = operation_key(request, maintenance.KIND, f'session:{sid}', token, required=True)
    result, fresh = write(factory, sid, token, key, body)
    if not fresh:
        response.status_code = 200
        response.headers['Idempotency-Replayed'] = 'true'
    return result


@router.get('/sessions/{sid}/conversation-appends/recovery', response_model=AppendResult)
def recovery(sid: UUID, token: Token, request: Request, factory: Factory):
    key, _ = operation_key(request, maintenance.KIND, f'session:{sid}', token, required=True)
    return read(factory, sid, token, key=key)


@router.get('/sessions/{sid}/conversation-appends/{oid}', response_model=AppendResult)
def operation(sid: UUID, oid: UUID, token: Token, factory: Factory):
    return read(factory, sid, token, oid=oid)
