from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_expected_contract() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_route_returns_404() -> None:
    assert client.get("/api/v1/does-not-exist").status_code == 404


def test_local_dev_origin_is_allowed() -> None:
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_other_origin_is_not_granted_cors() -> None:
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "https://untrusted.example"},
    )
    assert "access-control-allow-origin" not in response.headers
