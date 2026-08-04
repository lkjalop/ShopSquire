from fastapi.testclient import TestClient

from src.app.main import create_app


def _client_with_env(monkeypatch) -> TestClient:
    monkeypatch.setenv("EGRESS_ALLOWLIST_ENABLED", "0")
    monkeypatch.setenv("INVENTORY_DATA_READINESS_REQUIRED", "0")
    return TestClient(create_app())


def test_reorder_rejects_caller_selected_supplier_trust(monkeypatch):
    client = _client_with_env(monkeypatch)
    r = client.post(
        "/api/v1/inventory/reorder",
        headers={"x-api-key": "local-merchant-key"},
        json={
            "sku": "SKU-LOWTRUST",
            "supplier_id": "SUP-1",
            "quantity": 5,
            "supplier_trust_score": 0.3,
            "supplier_trust_band": "low",
        },
    )
    assert r.status_code == 422


def test_reorder_rejects_caller_selected_confirmation_evidence(monkeypatch):
    client = _client_with_env(monkeypatch)
    r = client.post(
        "/api/v1/inventory/reorder",
        headers={"x-api-key": "local-merchant-key"},
        json={
            "sku": "SKU-DUALCONF",
            "supplier_id": "SUP-2",
            "quantity": 1,
            "supplier_trust_score": 0.9,
            "supplier_trust_band": "high",
            "anomaly_score": 0.8,
            "po_invoice_confirmed": True,
            "carrier_asn_ack": False,
            "erp_ack": False,
        },
    )
    assert r.status_code == 422
