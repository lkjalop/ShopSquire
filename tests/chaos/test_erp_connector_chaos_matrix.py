from __future__ import annotations

import os

from fastapi.testclient import TestClient

from src.app.erp.connectors.http_inventory import HTTPInventoryConnector
from src.app.main import create_app


class _Resp:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {"items": []}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")


def test_http_connector_health_429_and_5xx(monkeypatch):
    os.environ["NETSUITE_BASE_URL"] = "https://erp.example"
    c = HTTPInventoryConnector(provider_id="netsuite", env_prefix="NETSUITE")

    monkeypatch.setattr("src.app.erp.connectors.http_inventory.requests.get", lambda *a, **k: _Resp(429))
    h1 = c.health()
    assert h1.get("ok") is False
    assert h1.get("error") == "provider_rate_limited"

    monkeypatch.setattr("src.app.erp.connectors.http_inventory.requests.get", lambda *a, **k: _Resp(503))
    h2 = c.health()
    assert h2.get("ok") is False
    assert h2.get("error") == "provider_5xx"


def test_admin_sync_rejects_unhealthy_erp_connector(monkeypatch):
    os.environ["OWNER_API_KEY"] = "local-owner-key"
    os.environ["NETSUITE_BASE_URL"] = "https://erp.example"

    def _rl(*_a, **_k):
        return _Resp(429)

    monkeypatch.setattr("src.app.erp.connectors.netsuite.requests.request", _rl)

    app = create_app()
    client = TestClient(app)
    r = client.post(
        "/api/v1/admin/inventory/sync",
        headers={"x-api-key": "local-owner-key"},
        json={"connector": "netsuite", "dry_run": False, "upsert_products": False},
    )
    assert r.status_code == 400
    assert "provider_rate_limited" in str(r.text)
