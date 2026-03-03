from fastapi.testclient import TestClient

from src.app.main import create_app


def _client_with_env(monkeypatch) -> TestClient:
    monkeypatch.setenv("EGRESS_ALLOWLIST_ENABLED", "0")
    monkeypatch.setenv("INVENTORY_DATA_READINESS_REQUIRED", "0")
    return TestClient(create_app())


def test_inventory_reorder_bola_tenant_owner_scope_enforced(monkeypatch):
    client = _client_with_env(monkeypatch)
    body = {
        "sku": "SKU-BOLA-1",
        "supplier_id": "SUP-1",
        "quantity": 2,
        "tenant_id": "tenant-a",
        "owner_id": "user-a",
        "supplier_trust_score": 0.8,
        "supplier_trust_band": "high",
    }
    bad_tenant = client.post(
        "/api/v1/inventory/reorder",
        headers={"x-api-key": "local-merchant-key", "x-tenant-id": "tenant-b", "x-user-id": "user-a"},
        json=body,
    )
    assert bad_tenant.status_code == 403

    bad_owner = client.post(
        "/api/v1/inventory/reorder",
        headers={"x-api-key": "local-merchant-key", "x-tenant-id": "tenant-a", "x-user-id": "user-b"},
        json=body,
    )
    assert bad_owner.status_code == 403
