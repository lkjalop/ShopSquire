from fastapi.testclient import TestClient

from src.app.main import create_app


def _client_with_env(monkeypatch) -> TestClient:
    monkeypatch.setenv("EGRESS_ALLOWLIST_ENABLED", "0")
    monkeypatch.setenv("INVENTORY_DATA_READINESS_REQUIRED", "0")
    return TestClient(create_app())


def test_inventory_reorder_rejects_client_selected_scope_and_economics(monkeypatch):
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
    response = client.post(
        "/api/v1/inventory/reorder",
        headers={"x-api-key": "local-merchant-key", "x-tenant-id": "tenant-b", "x-user-id": "user-a"},
        json=body,
    )
    assert response.status_code == 422
    assert any(
        error.get("loc") == ["body", "proposal_id"]
        for error in response.json().get("detail", [])
    )
