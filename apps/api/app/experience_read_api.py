"""Default-closed, explicitly versioned GET candidates. No generic negotiation."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import facts, read_contract as dto
from app.experience_api import Token
from app.experience_read import Projection
from app.maintenance_errors import ConversationError
from app.models import ExperienceProject
from app.read_permissions import check_reader

router=APIRouter(prefix='/api/v2/experience',tags=['versioned experience reads (disabled)'])


def get_read_factory():
    raise ConversationError(503,'experience_read_disabled')


Factory=Annotated[object,Depends(get_read_factory)]


def read(factory,token,*,sid=None,pid=None):
    try:
        with factory() as db:
            db.connection(execution_options={'isolation_level':'REPEATABLE READ','postgresql_readonly':True})
            if db.scalar(text('SHOW transaction_read_only'))!='on' or db.scalar(text('SHOW transaction_isolation'))!='repeatable read':
                raise ConversationError(503,'experience_readonly_required')
            if pid is not None:
                project=db.get(ExperienceProject,pid)
                if project is None:raise PermissionError('Resource unavailable')
                sid=project.session_id
            session=facts.authorize(db,sid,token)
            check_reader(db)
            projection=Projection(db,session)
            return projection.summary(pid) if pid is not None else projection.export()
    except (SQLAlchemyError,ValidationError,KeyError,TypeError,ValueError):
        raise ConversationError(503,'experience_read_integrity_unavailable') from None


@router.get('/projects/{pid}/experience-summary',response_model=dto.SummaryV2)
def summary(pid:UUID,token:Token,factory:Factory):
    return read(factory,token,pid=pid)


@router.get('/sessions/{sid}/export',response_model=dto.ExportV2)
def export(sid:UUID,token:Token,factory:Factory,response:Response):
    result=read(factory,token,sid=sid)
    response.headers['Content-Disposition']=f'attachment; filename="pathwise-v2-{sid}.json"'
    return result
