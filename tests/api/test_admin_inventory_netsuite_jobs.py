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


def test_netsuite_delta_and_outbound_jobs(monkeypatch):
    os.environ["OWNER_API_KEY"] = "local-owner-key"
    os.environ["NETSUITE_BASE_URL"] = "https://netsuite.example"

    seen = {"delta_calls": 0, "cursor_values": []}

    def _request(method, url, params=None, json=None, headers=None, timeout=None):
        _ = headers, timeout
        if method.upper() == "GET" and "inventory/delta" in url:
            seen["delta_calls"] += 1
            seen["cursor_values"].append((params or {}).get("cursor"))
            if seen["delta_calls"] == 1:
                return _Resp(
                    200,
                    {
                        "items": [{"sku": "NS-1", "warehouse": "main", "stock": 9, "updated_at": "2026-02-13T00:00:00Z"}],
                        "next_cursor": "cur-2",
                    },
                )
            return _Resp(200, {"items": [], "next_cursor": "cur-2"})
        if method.upper() == "POST" and "customers/upsert" in url:
            return _Resp(200, {"ok": True})
        if method.upper() == "POST" and "sales_orders/upsert" in url:
            return _Resp(200, {"ok": True})
        return _Resp(200, {"items": []})

    monkeypatch.setattr("src.app.erp.connectors.netsuite.requests.request", _request)

    app = create_app()
    client = TestClient(app)

    d1 = client.post(
        "/api/v1/admin/inventory/sync/netsuite/delta",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "tns", "dry_run": False, "upsert_products": False},
    )
    assert d1.status_code == 200
    out1 = d1.json()
    assert int(out1.get("delta_count") or 0) >= 1
    assert (out1.get("cursor") or {}).get("next") == "cur-2"

    d2 = client.post(
        "/api/v1/admin/inventory/sync/netsuite/delta",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "tns", "dry_run": False, "upsert_products": False},
    )
    assert d2.status_code == 200
    # Second call should send the previous cursor (stateful delta sync).
    assert "cur-2" in seen["cursor_values"]

    eq = client.post(
        "/api/v1/admin/inventory/sync/netsuite/outbound/enqueue",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "tns", "entity_type": "customer", "payload": {"external_id": "c-1", "email": "a@b.c", "name": "A B"}},
    )
    assert eq.status_code == 200
    run = client.post(
        "/api/v1/admin/inventory/sync/netsuite/outbound/run",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "tns", "limit": 10},
    )
    assert run.status_code == 200
    rout = run.json()
    assert int(rout.get("processed") or 0) >= 1
    assert int(rout.get("sent") or 0) >= 1

