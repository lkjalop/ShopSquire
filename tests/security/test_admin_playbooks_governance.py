import json

from fastapi.testclient import TestClient

from src.app.main import create_app


def _owner_headers() -> dict:
    return {"x-api-key": "local-owner-key"}


def test_publish_requires_approval_then_succeeds():
    app = create_app()
    client = TestClient(app)

    req = {
        "playbook_id": "PB-PAYMENT-FRAUD",
        "updates": {"enabled": True},
    }
    r = client.post("/api/v1/admin/playbooks/publish", headers=_owner_headers(), content=json.dumps(req))
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "pending_approval"
    aid = body.get("approval_id")
    assert aid

    a = client.post(f"/api/v1/approvals/{aid}/approve", headers=_owner_headers())
    assert a.status_code == 200

    req["approval_id"] = aid
    r2 = client.post("/api/v1/admin/playbooks/publish", headers=_owner_headers(), content=json.dumps(req))
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2.get("status") == "ok"
    assert body2.get("playbook_id") == "PB-PAYMENT-FRAUD"


def test_rollback_requires_approval():
    app = create_app()
    client = TestClient(app)

    req = {
        "playbook_id": "PB-PAYMENT-FRAUD",
        "target_version": "1.0.0",
    }
    r = client.post("/api/v1/admin/playbooks/rollback", headers=_owner_headers(), content=json.dumps(req))
    assert r.status_code == 200
    assert r.json().get("status") == "pending_approval"
