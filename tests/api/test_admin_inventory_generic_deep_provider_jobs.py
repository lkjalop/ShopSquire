import os

from fastapi.testclient import TestClient

from src.app.main import create_app


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"content-type": "application/json"}
        self.text = str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")


def test_generic_provider_delta_and_outbound(monkeypatch):
    os.environ["OWNER_API_KEY"] = "local-owner-key"
    os.environ["SAP_BASE_URL"] = "https://sap.example"

    def _request(method, url, params=None, json=None, headers=None, timeout=None):
        _ = headers, timeout
        if method.upper() == "GET" and "/inventory/delta" in url:
            return _Resp(
                200,
                {"items": [{"sku": "SAP-1", "warehouse": "w1", "stock": 3, "updated_at": "2026-02-13T00:00:00Z"}], "next_cursor": "c2"},
            )
        if method.upper() == "POST" and "/business-partners/upsert" in url:
            return _Resp(200, {"ok": True})
        return _Resp(200, {"ok": True})

    monkeypatch.setattr("src.app.erp.connectors.provider_sync.requests.request", _request)

    app = create_app()
    client = TestClient(app)

    d = client.post(
        "/api/v1/admin/inventory/sync/erp/delta",
        headers={"x-api-key": "local-owner-key"},
        json={"provider": "sap", "tenant_id": "t-sap", "dry_run": False, "upsert_products": False},
    )
    assert d.status_code == 200
    out = d.json()
    assert int(out.get("delta_count") or 0) >= 1
    assert (out.get("cursor") or {}).get("next") == "c2"

    e = client.post(
        "/api/v1/admin/inventory/sync/erp/outbound/enqueue",
        headers={"x-api-key": "local-owner-key"},
        json={"provider": "sap", "tenant_id": "t-sap", "entity_type": "customer", "payload": {"external_id": "bp-1", "email": "x@y.z", "name": "X Y"}},
    )
    assert e.status_code == 200

    r = client.post(
        "/api/v1/admin/inventory/sync/erp/outbound/run",
        headers={"x-api-key": "local-owner-key"},
        json={"provider": "sap", "tenant_id": "t-sap", "limit": 10},
    )
    assert r.status_code == 200
    rout = r.json()
    assert int(rout.get("processed") or 0) >= 1
    assert int(rout.get("sent") or 0) >= 1

