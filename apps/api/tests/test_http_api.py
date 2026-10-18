"""HTTP regressions use independent connections to the real migrated database."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError

from app.experience_api import get_db
from app.main import app
from app.models import ExperienceFact, FactChange, FactStatus


@pytest.fixture
def api(migrated_connection):
    connection, _ = migrated_connection
    schema = connection.scalar(text("SELECT current_schema()"))
    connection.commit()
    engine = create_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool,
                           connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True)
    factory = sessionmaker(engine, expire_on_commit=False)

    def test_db():
        with factory() as db, db.begin():
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def create(client):
    response = client.post("/api/v1/experience/sessions", json={"raw_input": "Synthetic A: built a course tracker."})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    return data, {"Authorization": "Bearer " + data["access_token"]}


def add(client, data, headers):
    response = client.post(f'/api/v1/experience/projects/{data["project_id"]}/facts', headers=headers,
                           json={"statement": "Built a course tracker", "source_turn_ids": [data["initial_turn_id"]]})
    assert response.status_code == 201
    assert response.json()["version"] == 1
    return response.json()


def patch(client, fact, headers, action, **kwargs):
    return client.patch(f'/api/v1/experience/facts/{fact["id"]}', headers=headers,
                        json={"action": action, "expected_version": fact["version"], **kwargs})


def test_http_provenance_export_end_and_delete(api):
    client, factory = api
    data, headers = create(client)
    fact = add(client, data, headers)
    assert fact["source_kind"] == "conversation_turns"
    fact = patch(client, fact, headers, "confirm").json()
    assert fact["version"] == 2 and fact["status"] == "user_confirmed"
    fact = patch(client, fact, headers, "edit", statement="Synthetic B: handled deployment").json()
    assert fact["version"] == 3 and fact["status"] == "pending"
    fact = patch(client, fact, headers, "confirm").json()
    assert fact["version"] == 4
    assert fact["source_kind"] == "user_edit" and fact["source_turn_ids"] == []
    edit_id = fact["source_change_id"]
    fact = patch(client, fact, headers, "verify_material", material_reference="synthetic-report:2", basis="User reviewed section 2").json()
    assert fact["version"] == 5 and fact["status"] == "evidence_supported"
    url = f'/api/v1/experience/sessions/{data["session_id"]}'
    exported = client.get(url + "/export", headers=headers)
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    assert data["access_token"] not in exported.text and "access_token_hash" not in exported.text
    stored = exported.json()["data"]
    assert stored["facts"][0]["source_change_id"] == edit_id
    assert stored["facts"][0]["original_source_turn_ids"] == [data["initial_turn_id"]]
    assert stored["turns"][0]["content"] == stored["projects"][0]["raw_input"]
    assert [item["after"]["version"] for item in stored["history"]] == [1, 2, 3, 4, 5]
    assert stored["evidence"][0]["verification_label"] == "用户提供材料并自行核实"
    assert client.post(url + "/end", headers=headers).json()["status"] == "ended"
    assert client.post(url + "/end", headers=headers).status_code == 200
    assert client.post(url + "/turns", headers=headers, json={"content": "Synthetic later answer"}).status_code == 409
    assert patch(client, fact, headers, "reject").status_code == 409
    assert client.get(url, headers=headers).status_code == 200
    assert client.get(url + "/export", headers=headers).status_code == 200
    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404
    assert client.get(url + "/export", headers=headers).status_code == 404
    with factory() as db:
        for name in ("experience_sessions", "experience_projects", "conversation_turns", "experience_facts", "fact_sources", "fact_changes", "fact_evidence"):
            assert db.scalar(text(f"SELECT count(*) FROM {name}")) == 0


def test_stale_edit_confirmation_rejection_and_verification_are_atomic(api):
    client, factory = api
    data, headers = create(client)
    old = add(client, data, headers)
    current = patch(client, old, headers, "edit", statement="Synthetic B: handled deployment").json()
    for action, extra in [("edit", {"statement": "Stale edit"}), ("confirm", {}), ("reject", {}),
                          ("verify_material", {"material_reference": "report", "basis": "User reviewed"})]:
        response = patch(client, old, headers, action, **extra)
        assert response.status_code == 409 and response.json()["error"]["code"] == "version_conflict"
    with factory() as db:
        assert len(db.scalars(select(FactChange)).all()) == 2
        stored = db.scalar(select(ExperienceFact))
        assert stored.version == 2 and stored.statement == current["statement"] and stored.status == "pending"


def test_transaction_failure_before_response_rolls_back_creation(api):
    client, factory = api

    def failed_transaction():
        with factory() as db, db.begin():
            yield db
            raise OperationalError("synthetic failure", {}, Exception("synthetic database issue"))

    app.dependency_overrides[get_db] = failed_transaction
    response = client.post("/api/v1/experience/sessions", json={"raw_input": "Synthetic rollback"})
    assert response.status_code == 503
    assert "access_token" not in response.text
    with factory() as db:
        assert db.scalar(text("SELECT count(*) FROM experience_sessions")) == 0


def test_parallel_requests_using_same_version_have_one_winner(api):
    client, factory = api
    data, headers = create(client)
    fact = add(client, data, headers)
    gate = Barrier(2)

    def send(action):
        gate.wait(timeout=10)
        return patch(client, fact, headers, action).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, ["confirm", "reject"]))
    assert sorted(results) == [200, 409]
    with factory() as db:
        assert db.scalar(select(ExperienceFact)).version == 2
        assert len(db.scalars(select(FactChange)).all()) == 2


def test_authorization_covers_all_read_write_export_and_delete_paths(api):
    client, _ = api
    data, headers = create(client)
    other, other_headers = create(client)
    fact = add(client, data, headers)
    url = f'/api/v1/experience/sessions/{data["session_id"]}'
    calls = [("get", url, None), ("get", url + "/export", None), ("delete", url, None),
             ("post", url + "/end", None), ("post", url + "/turns", {"content": "Synthetic"}),
             ("post", f'/api/v1/experience/projects/{data["project_id"]}/facts',
              {"statement": "Synthetic", "source_turn_ids": [data["initial_turn_id"]]}),
             ("patch", f'/api/v1/experience/facts/{fact["id"]}', {"action": "confirm", "expected_version": 1})]
    for method, path, body in calls:
        options = {"json": body} if body is not None else {}
        assert client.request(method, path, **options).status_code == 401
        response = client.request(method, path, headers=other_headers, **options)
        assert response.status_code == 404 and data["access_token"] not in response.text
    unknown = client.get(f"/api/v1/experience/sessions/{uuid4()}", headers=headers)
    wrong = client.get(url, headers=other_headers)
    assert unknown.json() == wrong.json()
    assert client.post(f'/api/v1/experience/projects/{data["project_id"]}/facts', headers=headers,
                       json={"statement": "Other claim", "source_turn_ids": [other["initial_turn_id"]]}).status_code == 422
    assert client.get(url, headers=headers).json()["facts"][0]["version"] == 1


@pytest.mark.parametrize("body", [
    {"action": "confirm"}, {"action": "confirm", "expected_version": True},
    {"action": "confirm", "expected_version": 0}, {"action": "confirm", "expected_version": "1"},
    {"action": "edit", "expected_version": 1, "statement": " "},
    {"action": "edit", "expected_version": 1, "statement": "a" * 10001},
    {"action": "confirm", "expected_version": 1, "statement": "Must not edit and confirm"},
    {"action": "verify_material", "expected_version": 1, "material_reference": " ", "basis": "Synthetic"},
])
def test_fact_request_contract_rejects_invalid_or_combined_operations(api, body):
    client, _ = api
    data, headers = create(client)
    fact = add(client, data, headers)
    response = client.patch(f'/api/v1/experience/facts/{fact["id"]}', headers=headers, json=body)
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_request", "message": "Request does not match the API contract"}}


def test_illegal_state_and_rejected_fact_edit(api):
    client, factory = api
    data, headers = create(client)
    fact = add(client, data, headers)
    assert patch(client, fact, headers, "verify_material", material_reference="report", basis="User reviewed").status_code == 409
    fact = patch(client, fact, headers, "reject").json()
    assert patch(client, fact, headers, "confirm").status_code == 409
    response = patch(client, fact, headers, "edit", statement="Synthetic clarified claim")
    assert response.status_code == 409 and response.json()["error"]["code"] == "state_conflict"
    with factory() as db:
        stored = db.get(ExperienceFact, fact["id"])
        assert stored.status == "rejected" and stored.version == 2
        assert stored.statement == fact["statement"]
        assert db.scalar(select(text('count(*)')).select_from(FactChange)) == 2
