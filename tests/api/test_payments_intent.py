import os
from fastapi.testclient import TestClient

from src.app.main import create_app


def test_payment_intent_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv("DISABLE_UI_ROUTES", "1")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_123")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path/'pay.sqlite'}")
    from src.app.services.payments import StripeClient
    monkeypatch.setattr(StripeClient, "__init__", lambda self, api_key: None)
    monkeypatch.setattr(
        StripeClient,
        "create_payment_intent",
        lambda self, amount_cents, currency="USD", metadata=None: {
            "id": "pi_mock_123",
            "amount": amount_cents,
            "currency": currency,
            "status": "requires_payment_method",
        },
    )
    from src.app.config import get_settings
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    app = create_app()
    client = TestClient(app)

    # First intent should succeed
    r1 = client.post("/api/v1/payments/intent", params={"amount_cents": 9999, "currency": "USD", "idempotency_key": "abc123"}, headers={"x-api-key": "local-merchant-key"})
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1.get("status") in ("requires_payment_method", "requires_confirmation", None)

    # Second with same idempotency_key should 409
    r2 = client.post("/api/v1/payments/intent", params={"amount_cents": 9999, "currency": "USD", "idempotency_key": "abc123"}, headers={"x-api-key": "local-merchant-key"})
    assert r2.status_code == 409


def test_payment_intent_requires_configured_provider(tmp_path, monkeypatch):
    # Non-stripe-like key should fail closed (no stubbed success responses).
    monkeypatch.setenv("STRIPE_API_KEY", "test_key_no_sk_")
    monkeypatch.setenv("DISABLE_UI_ROUTES", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path/'pay2.sqlite'}")
    from src.app.config import get_settings
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/v1/payments/intent", params={"amount_cents": 12345, "currency": "USD", "idempotency_key": "new123"}, headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 503
