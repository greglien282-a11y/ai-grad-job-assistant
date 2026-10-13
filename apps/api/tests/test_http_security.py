import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.experience_api import configured_factory, get_db
from app.http_security import MAX_BODY_BYTES, RequestBoundary
from app.main import app


def test_validation_never_echoes_sensitive_input(caplog):
    with TestClient(app) as client:
        # UUID is invalid and no credential is supplied; response must not include input.
        marker = "synthetic-private-credential"
        response = client.get(f"/api/v1/experience/sessions/{uuid4()}?access_token={marker}")
        assert response.status_code == 400
        assert marker not in response.text and marker not in caplog.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get(f"/api/v1/experience/sessions/{uuid4()}").status_code == 401


def test_database_failure_is_safe_and_cors_allows_bearer(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    configured_factory.cache_clear()
    with TestClient(app) as client:
        response = client.post("/api/v1/experience/sessions", json={"raw_input": "Synthetic input"})
        assert response.status_code == 503 and response.json()["error"]["code"] == "database_unavailable"
        response = client.options("/api/v1/experience/sessions", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        response = client.post("/api/v1/experience/sessions", content=b"x" * (MAX_BODY_BYTES + 1),
                               headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 413
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    configured_factory.cache_clear()


def test_database_exception_does_not_reveal_sql_or_credentials(caplog):
    def broken_db():
        raise OperationalError("PRIVATE SQL", {"secret": "synthetic-credential"}, Exception("synthetic-credential"))
        yield

    app.dependency_overrides[get_db] = broken_db
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/experience/sessions", json={"raw_input": "Synthetic"})
            assert response.status_code == 503
            assert "PRIVATE" not in response.text and "synthetic-credential" not in response.text
            assert "synthetic-credential" not in caplog.text
    finally:
        app.dependency_overrides.clear()


def test_production_requires_https_and_does_not_trust_arbitrary_forwarded_header(monkeypatch):
    monkeypatch.setenv("REQUIRE_HTTPS", "true")
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-Forwarded-Proto": "https"})
        assert response.status_code == 400 and response.json()["error"]["code"] == "https_required"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/health").status_code == 200


@pytest.mark.parametrize("length", [None, "1", str(MAX_BODY_BYTES + 1), "-1", "invalid"])
def test_request_boundary_limits_actual_chunks_without_trusting_content_length(length):
    reached = False
    sent = []
    chunks = [{"type": "http.request", "body": b"x" * MAX_BODY_BYTES, "more_body": True},
              {"type": "http.request", "body": b"x", "more_body": False}]

    async def endpoint(scope, receive, send):
        nonlocal reached
        reached = True

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/v1/experience/sessions",
             "scheme": "http", "query_string": b"", "headers": [] if length is None else [(b"content-length", length.encode())]}
    asyncio.run(RequestBoundary(endpoint)(scope, receive, send))
    expected = 400 if length in ("-1", "invalid") else 413
    assert not reached and sent[0]["status"] == expected
    assert json.loads(sent[1]["body"])["error"]["code"] in ("body_too_large", "invalid_request")
