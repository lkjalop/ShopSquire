from fastapi.testclient import TestClient

from src.app.main import create_app


def _owner_headers():
    return {"x-api-key": "local-owner-key"}


def test_playbook_ops_endpoints_available():
    app = create_app()
    client = TestClient(app)
    r1 = client.get("/api/v1/admin/playbooks/ops/reliability?days=7", headers=_owner_headers())
    assert r1.status_code == 200
    body1 = r1.json()
    assert "totals" in body1
    assert "by_action" in body1

    r2 = client.get("/api/v1/admin/playbooks/trail/PB-PAYMENT-FRAUD?limit=10", headers=_owner_headers())
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2.get("playbook_id") == "PB-PAYMENT-FRAUD"
    assert "rows" in body2
