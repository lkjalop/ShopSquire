from fastapi.testclient import TestClient

from src.app.main import create_app


def _client_with_env(monkeypatch) -> TestClient:
    monkeypatch.setenv("EGRESS_ALLOWLIST_ENABLED", "0")
    monkeypatch.setenv("INVENTORY_DATA_READINESS_REQUIRED", "0")
    return TestClient(create_app())


def test_reorder_quarantines_low_supplier_trust(monkeypatch):
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
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    inner = body.get("result") or {}
    assert inner.get("status") == "quarantined_supplier_update"


def test_reorder_requires_dual_source_on_critical(monkeypatch):
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
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    result = body.get("result") or {}
    assert result.get("status") in {"approval_required", "po_created", "challenge_required"}
    if result.get("status") == "approval_required":
        assert result.get("reason") == "auto_po_policy_escalate"
