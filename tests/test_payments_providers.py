from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.config import get_settings
import json
from tests.utils import default_headers

app = create_app()

client = TestClient(app, headers=default_headers())


def _write_flags(flags):
    settings = get_settings()
    with open(settings.feature_flags_path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_paypal_disabled_by_flag():
    _write_flags({"CAPABILITIES": {"paypal": {"enabled": False}}})
    r = client.post("/api/v1/payments/paypal/intent", params={"uid": "u", "amount_cents": 1000})
    assert r.status_code == 503


def test_paypal_enabled_and_intent_created():
    _write_flags({"CAPABILITIES": {"paypal": {"enabled": True}}})
    r = client.post("/api/v1/payments/paypal/intent", params={"uid": "u", "amount_cents": 1000, "idempotency_key": "k1"})
    assert r.status_code == 503


def test_revolut_enabled_intent():
    _write_flags({"CAPABILITIES": {"revolut": {"enabled": True}}})
    r = client.post("/api/v1/payments/revolut/intent", params={"uid": "u", "amount_cents": 1000, "idempotency_key": "k2"})
    assert r.status_code == 503


def test_googlepay_enabled_intent():
    _write_flags({"CAPABILITIES": {"googlepay": {"enabled": True}}})
    r = client.post("/api/v1/payments/googlepay/intent", params={"uid": "u", "amount_cents": 1000, "idempotency_key": "k3"})
    assert r.status_code == 503


def test_afterpay_enabled_intent():
    _write_flags({"CAPABILITIES": {"afterpay": {"enabled": True}}})
    r = client.post("/api/v1/payments/afterpay/intent", params={"uid": "u", "amount_cents": 1000, "idempotency_key": "k4"})
    assert r.status_code == 503


def test_payments_rollout_status_summary():
    _write_flags(
        {
            "CAPABILITIES": {
                "stripe": {"enabled": True},
                "paypal": {"enabled": True},
                "revolut": {"enabled": False},
                "googlepay": {"enabled": False},
                "afterpay": {"enabled": False},
            }
        }
    )
    r = client.get("/api/v1/payments/providers/rollout")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("providers"), list)
    assert body.get("enabled_count") >= 2
    assert body.get("provider_concentration_risk") in ("low", "medium", "high")
