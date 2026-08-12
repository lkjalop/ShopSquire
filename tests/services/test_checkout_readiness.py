from src.app.services.checkout_readiness import buyer_checkout_readiness
from fastapi.testclient import TestClient

from src.app.main import create_app


def test_local_checkout_is_honestly_demo_and_shipping_estimate(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("AUSPOST_API_KEY", raising=False)
    monkeypatch.delenv("STARTRACK_API_KEY", raising=False)
    monkeypatch.delenv("EASYPOST_API_KEY", raising=False)
    monkeypatch.delenv("SHIPSTATION_API_KEY", raising=False)

    readiness = buyer_checkout_readiness()

    assert readiness["payment"]["status"] == "demo_only"
    assert readiness["payment"]["methods"] == ["demo"]
    assert readiness["shipping"]["status"] == "estimated_plan_only"


def test_unavailable_payment_exposes_no_methods(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_DEMO_CHECKOUT", "0")
    monkeypatch.setenv("PAYMENT_EXECUTION_ENABLED", "0")

    readiness = buyer_checkout_readiness()

    assert readiness["payment"]["status"] == "unavailable"
    assert readiness["payment"]["methods"] == []


def test_buyer_checkout_readiness_endpoint_is_public_and_safe(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    response = TestClient(create_app()).get("/api/v1/payments/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["payment"]["label"] in {"Demo only", "Configured", "Unavailable"}
    assert body["shipping"]["label"] in {"Estimated plan only", "Live carrier verified"}
    assert "configured" not in body["shipping"]
