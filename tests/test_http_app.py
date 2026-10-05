from fastapi.testclient import TestClient

from gateway.gateway_app import build_app


def make_client() -> TestClient:
    app = build_app(database_url="sqlite:///:memory:", secret=b"test-secret")
    return TestClient(app)


def test_registry_endpoint_reports_4_domains_24_tools():
    client = make_client()
    r = client.get("/registry")
    assert r.status_code == 200
    body = r.json()
    assert body["domain_count"] == 4
    assert body["tool_count"] == 24


def test_token_then_read_call_over_http():
    client = make_client()
    token = client.post("/auth/token", json={"group": "catalog-ops"}).json()["token"]
    r = client.post("/tools/get_pin/call", json={"token": token, "params": {"pin_id": 0}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_mutating_call_over_http_is_pending_not_applied():
    client = make_client()
    token = client.post("/auth/token", json={"group": "catalog-ops"}).json()["token"]
    r = client.post("/tools/delete_pin/call", json={"token": token, "params": {"pin_id": 0}})
    assert r.json()["status"] == "pending_approval"
    approval_id = r.json()["approval_id"]
    pending_ids = {e["approval_id"] for e in client.get("/approvals").json()["pending"]}
    assert approval_id in pending_ids


def test_approving_over_http_applies_the_effect():
    client = make_client()
    token = client.post("/auth/token", json={"group": "catalog-ops"}).json()["token"]
    approval_id = client.post("/tools/delete_pin/call", json={"token": token, "params": {"pin_id": 1}}).json()["approval_id"]
    r = client.post(f"/approvals/{approval_id}/decide", json={"approve": True})
    assert r.json()["decision"] == "approved"
    read = client.post("/tools/get_pin/call", json={"token": token, "params": {"pin_id": 1}})
    assert read.json()["data"]["deleted"] is True


def test_unauthorized_call_returns_403_over_http():
    client = make_client()
    token = client.post("/auth/token", json={"group": "ads-ops"}).json()["token"]
    r = client.post("/tools/delete_pin/call", json={"token": token, "params": {"pin_id": 0}})
    assert r.status_code == 403
