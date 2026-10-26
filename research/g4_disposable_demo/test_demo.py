import http.client
import json
from threading import Thread
from uuid import uuid4
import pytest
from research.g4_disposable_demo.server import Demo, server_for


@pytest.fixture
def live(boundary, tmp_path):
    (tmp_path / "index.html").write_text("Synthetic demo", encoding="utf8")
    demo = Demo(boundary)
    server = server_for(demo, 0, tmp_path)
    thread = Thread(target=server.serve_forever)
    thread.start()
    port = server.server_port
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    client.request("GET", "/")
    r = client.getresponse()
    cookie = r.getheader("Set-Cookie").split(";")[0]
    r.read()
    client.close()

    def request(method, path, *, key=None, body=None, origin=True):
        h = {
            "Cookie": cookie,
            "Origin": (
                f"http://127.0.0.1:{port}" if origin else "https://attacker.invalid"
            ),
            "Content-Type": "application/json",
        }
        if key:
            h["X-Research-Key"] = key
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            c.request(method, path, body=json.dumps(body) if body else None, headers=h)
            r = c.getresponse()
            return r.status, json.loads(r.read())
        finally:
            c.close()

    try:
        yield boundary, demo, request
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        demo.close()


def payload(
    content="我部署了服务。", kind="personal_action", stage="completed", lose=False
):
    return dict(
        demo_contract="g4-disposable-submit-v1",
        synthetic=True,
        content=content,
        kind=kind,
        stage=stage,
        lose_response=lose,
    )


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_real_http_plan_rejected_then_explicit_correct_choice_and_get_zero_effect(live):
    x, demo, request = live
    key = str(uuid4())
    before = x.model.snapshot()
    status, error = request(
        "POST", "/candidate", key=key, body=payload("我计划部署服务。")
    )
    assert (
        status == 409
        and error["code"] == "demo_not_saved"
        and x.model.snapshot() == before
    )
    status, saved = request(
        "POST",
        "/candidate",
        key=key,
        body=payload("我计划部署服务。", "plan", "planned"),
    )
    assert status == 201 and saved["facts"][0]["subject"]["status"] == "pending"
    assert saved["facts"][0]["subject"]["fact_kind"] == "plan"
    committed = x.model.snapshot()
    assert request("GET", "/recover", key=key) == (200, saved)
    assert x.model.snapshot() == committed


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_real_http_commit_response_lost_then_get_only_recovers(live):
    x, demo, request = live
    key = str(uuid4())
    with pytest.raises(http.client.RemoteDisconnected):
        request("POST", "/candidate", key=key, body=payload(lose=True))
    committed = x.model.snapshot()
    status, result = request("GET", "/recover", key=key)
    assert (
        status == 200
        and result["facts"][0]["basis"]["event"]["source_kind"]
        == "immutable_user_choice_event"
    )
    assert len(committed["ref_facts"]) == 1 and len(committed["g4_permits"]) == 1
    assert result["truth_verified"] is False and x.model.snapshot() == committed


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_real_http_origin_and_pathwise_routes_closed(live):
    x, demo, request = live
    before = x.model.snapshot()
    assert (
        request("POST", "/candidate", key=str(uuid4()), body=payload(), origin=False)[0]
        == 403
    )
    assert (
        request("POST", "/api/v3/typed-append", key=str(uuid4()), body=payload())[0]
        == 404
    )
    assert x.model.snapshot() == before


@pytest.mark.parametrize("boundary", ["credential"], indirect=True)
def test_signer_unavailable_http503_rolls_back_all_tables(live):
    x, demo, request = live
    before = x.model.snapshot()
    demo.signer.process.kill()
    demo.signer.process.wait(timeout=10)
    status, result = request("POST", "/candidate", key=str(uuid4()), body=payload())
    assert status == 503 and result["code"] == "demo_not_saved"
    assert x.model.snapshot() == before
