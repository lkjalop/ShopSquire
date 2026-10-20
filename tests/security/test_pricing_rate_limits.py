"""Pricing uses the same real startup-bound token-budget profile."""

import uuid
import requests
from tests.security.test_rate_limits import admitted_budget_runtime


def test_pricing_rate_limit_headers_present(admitted_budget_runtime):
    r = requests.get(
        admitted_budget_runtime["base_url"] + "/api/v1/pricing/suggest",
        headers={"x-api-key": "local-merchant-key"},
        params={"uid": "guest-" + uuid.uuid4().hex, "cart_total_cents": 12345},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:500]
    assert r.headers["X-Rate-Limit-Reason"] == "ok"
    assert float(r.headers["X-Rate-Limit-Tokens-Remaining"]) == 10000
    assert float(r.headers["X-Rate-Limit-Cost-Remaining-USD"]) == 1
