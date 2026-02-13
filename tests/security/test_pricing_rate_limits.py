import os
import uuid
import requests
import pytest

BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
MERCHANT_KEY = os.getenv("MERCHANT_API_KEY", "local-merchant-key")

hdr = {"x-api-key": MERCHANT_KEY}


@pytest.mark.xfail(reason="Server may not expose rate-limit headers until restarted")
def test_pricing_rate_limit_headers_present():
    uid = f"guest-{uuid.uuid4().hex[:6]}"
    r = requests.get(
        f"{BASE_URL}/api/v1/pricing/suggest",
        headers=hdr,
        params={"uid": uid, "cart_total_cents": 12345},
        timeout=10,
    )
    assert "X-Rate-Limit-Tokens-Remaining" in r.headers
    assert "X-Rate-Limit-Cost-Remaining-USD" in r.headers
    assert "X-Rate-Limit-Reason" in r.headers
