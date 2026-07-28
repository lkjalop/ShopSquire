from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_onboard_pilot_and_meter_event_flow():
    client = TestClient(create_app())

    r1 = client.post(
        "/api/v1/billing/admin/pilots/onboard",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "pilot-1", "company_name": "Pilot Co", "contact_email": "ops@pilot.co"},
    )
    assert r1.status_code == 200, r1.text
    assert (r1.json() or {}).get("status") == "pilot"

    r2 = client.post(
        "/api/v1/billing/meter-event",
        headers={"x-api-key": "local-merchant-key"},
        json={"tenant_id": "pilot-1", "metric": "recommend_requests", "quantity": 2},
    )
    assert r2.status_code == 200, r2.text
    assert bool((r2.json() or {}).get("event_id"))

    r3 = client.get(
        "/api/v1/billing/admin/usage",
        headers={"x-api-key": "local-owner-key"},
        params={"tenant_id": "pilot-1", "days": 30},
    )
    assert r3.status_code == 200, r3.text
    assert isinstance((r3.json() or {}).get("items"), list)


def test_xero_endpoint_returns_validation_or_config_error():
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/billing/accounting/xero/inventory-adjustment",
        headers={"x-api-key": "local-owner-key"},
        json={"qty": 3, "reason": "stock_count"},
    )
    # Route-level validation requires sku; this confirms endpoint is wired.
    assert r.status_code == 400


def test_xero_direct_writes_are_disabled_by_default():
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/billing/accounting/xero/inventory-adjustment",
        headers={"x-api-key": "local-owner-key"},
        json={"sku": "SKU-1", "qty": 3, "reason": "stock_count"},
    )
    assert r.status_code == 503
    assert "governed_delivery_job" in str(r.json().get("detail") or "")

