"""Pathwise HTTP API. No LLM integration."""
import os
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException

from app.experience_api import router
from app.facts import StateConflict, VersionConflict
from app.http_security import RequestBoundary, error_response
from app.idempotency import IdempotencyError


class HealthResponse(BaseModel):
    status: Literal["ok"]


def configured_origins() -> list[str]:
    """Development CORS allowlist; never use wildcard with credentials."""
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="Pathwise API", version="0.1.0")
app.add_middleware(RequestBoundary)
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Idempotency-Key"],
    expose_headers=["Content-Disposition", "Idempotency-Replayed", "Retry-After"],
)
app.include_router(router)


@app.exception_handler(IdempotencyError)
async def idempotency_error(request, exc):
    headers = {'Retry-After': '1'} if exc.code == 'idempotency_busy' else None
    return error_response(exc.status, exc.code, 'Operation recovery requires review', headers)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    codes = {401: "credential_required", 404: "resource_unavailable", 503: "database_unavailable"}
    messages = {401: "Bearer credential required", 404: "Resource unavailable", 503: "Database unavailable"}
    return error_response(exc.status_code, codes.get(exc.status_code, "request_failed"),
                          messages.get(exc.status_code, "Request could not be completed"), exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic's default errors include rejected input, possibly sensitive data.
    return error_response(422, "invalid_request", "Request does not match the API contract")


@app.exception_handler(PermissionError)
async def permission_error(request, exc):
    return error_response(404, "resource_unavailable", "Resource unavailable")


@app.exception_handler(VersionConflict)
@app.exception_handler(StaleDataError)
async def version_error(request, exc):
    return error_response(409, "version_conflict", "Fact changed; reload before retrying")


@app.exception_handler(StateConflict)
async def state_error(request, exc):
    return error_response(409, "state_conflict", "Operation conflicts with the current state")


@app.exception_handler(ValueError)
async def domain_input_error(request, exc):
    return error_response(422, "invalid_request", "Invalid fact source or verification input")


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return error_response(409, "data_conflict", "Operation conflicts with stored data")


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    if getattr(getattr(exc, 'orig', None), 'sqlstate', None) == '55P03':
        return error_response(503, 'idempotency_busy', 'Operation recovery requires review', {'Retry-After': '1'})
    return error_response(503, "database_unavailable", "Database unavailable; retry later")


@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")
