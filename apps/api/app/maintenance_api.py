"""Default-closed local commands. No environment switch enables this factory.

An approved deployment must independently provide/verify a restricted factory.
This implementation supplies none. Tests inject real isolated role connections.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import fact_maintenance as maintenance
from app.experience_api import Token, operation_key
from app.maintenance_contract import Command, Resolution
from app.maintenance_errors import ConversationError
from app.maintenance_permissions import check_runtime

router = APIRouter(prefix='/api/v1/experience', tags=['local fact maintenance (disabled)'])


def get_maintenance_factory():
    raise ConversationError(503, 'conversation_maintenance_disabled')


Factory = Annotated[object, Depends(get_maintenance_factory)]


def write(factory, sid, token, key, body, parent_id=None):
    try:
        with factory() as db, db.begin():
            check_runtime(db)
            result, fresh = maintenance.apply(db, sid, token, key, body, parent_id=parent_id)
        return result, fresh
    except IntegrityError:
        # Also catches deferred integrity failure at COMMIT. No SQL/params/text.
        raise ConversationError(500, 'conversation_integrity_failed') from None


@router.post('/sessions/{sid}/conversation-operations', status_code=201)
def submit(sid: UUID, body: Command, token: Token, request: Request, response: Response, factory: Factory):
    key, _ = operation_key(request, maintenance.KIND, f'session:{sid}', token, required=True)
    result, fresh = write(factory, sid, token, key, body)
    if not fresh:
        response.status_code = 200
        response.headers['Idempotency-Replayed'] = 'true'
    return result


@router.post('/sessions/{sid}/conversation-operations/{parent_id}/resolution', status_code=201)
def resolve(sid: UUID, parent_id: UUID, body: Resolution, token: Token,
            request: Request, response: Response, factory: Factory):
    key, _ = operation_key(request, maintenance.KIND, f'session:{sid}', token, required=True)
    result, fresh = write(factory, sid, token, key, body, parent_id)
    if not fresh:
        response.status_code = 200
        response.headers['Idempotency-Replayed'] = 'true'
    return result


def read(factory, sid, token, *, key=None, oid=None):
    with factory() as db:
        # One actual connection for role, authentication and receipt projection.
        # Closing rolls back this read-only transaction; never register deadlines.
        db.connection(execution_options={'isolation_level': 'REPEATABLE READ', 'postgresql_readonly': True})
        if db.scalar(text('SHOW transaction_read_only')) != 'on' or db.scalar(text('SHOW transaction_isolation')) != 'repeatable read':
            raise ConversationError(503, 'conversation_readonly_required')
        check_runtime(db)
        return maintenance.recover(db, sid, token, key=key, oid=oid)


@router.get('/sessions/{sid}/conversation-operations/recovery')
def recovery(sid: UUID, token: Token, request: Request, factory: Factory):
    key, _ = operation_key(request, maintenance.KIND, f'session:{sid}', token, required=True)
    return read(factory, sid, token, key=key)


@router.get('/sessions/{sid}/conversation-operations/{oid}')
def operation(sid: UUID, oid: UUID, token: Token, factory: Factory):
    return read(factory, sid, token, oid=oid)
