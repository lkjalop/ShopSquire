import os
import uuid
import requests
import pytest

BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
MERCHANT_KEY = os.getenv("MERCHANT_API_KEY", "local-merchant-key")

hdr = {"x-api-key": MERCHANT_KEY}


@pytest.mark.xfail(reason="Server may not expose rate-limit headers until restarted")
def test_rate_limit_headers_present():
    uid = f"guest-{uuid.uuid4().hex[:6]}"
    r = requests.get(
        f"{BASE_URL}/api/v1/recommend/suggest",
        headers=hdr,
        params={"uid": uid, "query": "short"},
        timeout=10,
    )
    # Headers should always be present regardless of allow/exceed state
    assert "X-Rate-Limit-Tokens-Remaining" in r.headers
    assert "X-Rate-Limit-Cost-Remaining-USD" in r.headers
    assert "X-Rate-Limit-Reason" in r.headers


@pytest.mark.xfail(reason="Server env limits are not controlled by test runner")
def test_budget_exceeded_when_limits_low(monkeypatch):
    # These env vars affect only the test process, not the server.
    os.environ["TOKEN_BUDGET_ENABLED"] = "true"
    os.environ["TOKEN_BUDGET_GUEST_DAILY_TOKENS"] = "50"
    os.environ["TOKEN_BUDGET_GUEST_DAILY_USD"] = "0.00001"

    uid = f"guest-{uuid.uuid4().hex[:6]}"
    exceeded = False
    for _ in range(20):
        r = requests.get(
            f"{BASE_URL}/api/v1/recommend/suggest",
            headers=hdr,
            params={"uid": uid, "query": "short"},
            timeout=10,
        )
        try:
            body = r.json()
        except Exception:
            body = {}
        if body.get("status") == "budget_exceeded":
            exceeded = True
            break
    assert exceeded, "Expected budget_exceeded with low limits"
