import json

from fastapi.testclient import TestClient

from src.app.config import get_settings
from src.app.main import create_app
from tests.utils import default_headers


def _write_flags(flags):
    settings = get_settings()
    with open(settings.feature_flags_path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_paypal_intent_blocked_on_unauthorized_pattern():
    # Reset the in-process velocity windows so this is DETERMINISTIC regardless of suite order —
    # a suspicious 'stolen card testing' description now hard-blocks (403) on its own via the
    # transaction firewall's explicit-block floor, independent of accumulated counters.
    from src.app.security.payment_threats import reset_counters
    reset_counters()
    app = create_app()
    client = TestClient(app, headers=default_headers())
    _write_flags({"CAPABILITIES": {"paypal": {"enabled": True}}})
    r = client.post(
        "/api/v1/payments/paypal/intent",
        params={
            "uid": "u-bad",
            "amount_cents": 250000,
            "description": "stolen card testing bypass 3ds unauthorized",
            "idempotency_key": "k-pay-risk-1",
        },
    )
    assert r.status_code == 403, r.text  # explicit fraud description → hard block
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        sec = detail.get("security") or {}
        if sec:
            assert sec.get("action") == "hard_block"
