"""HTTP token admission against an owned API with startup-bound limits."""

import os
import uuid

import pytest
import requests

from tests.owned_security_runtime import _owned_runtime


@pytest.fixture(scope="module")
def admitted_budget_runtime(pytestconfig, tmp_path_factory):
    parent = {key: value for key, value in os.environ.items() if key.startswith("TOKEN_BUDGET_")}
    directory = tmp_path_factory.mktemp("budget-parent") / "admitted"
    with _owned_runtime(
        pytestconfig,
        artifact_directory=directory,
        publish_base_url=False,
        env_overrides={
            "TOKEN_BUDGET_ENABLED": "1",
            "TOKEN_BUDGET_GUEST_DAILY_TOKENS": "10000",
            "TOKEN_BUDGET_GUEST_DAILY_USD": "1",
        },
    ) as runtime:
        yield runtime
    assert {
        key: value for key, value in os.environ.items() if key.startswith("TOKEN_BUDGET_")
    } == parent


def test_rate_limit_headers_present(admitted_budget_runtime):
    r = requests.get(
        admitted_budget_runtime["base_url"] + "/api/v1/recommend/suggest",
        headers={"x-api-key": "local-merchant-key"},
        params={"uid": "guest-" + uuid.uuid4().hex, "query": "laptop"},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:500]
    assert r.headers["X-Rate-Limit-Reason"] == "ok"
    assert float(r.headers["X-Rate-Limit-Tokens-Remaining"]) == 10000
    assert float(r.headers["X-Rate-Limit-Cost-Remaining-USD"]) == 1


def test_budget_exceeded_when_limits_low(pytestconfig, tmp_path):
    with _owned_runtime(
        pytestconfig,
        artifact_directory=tmp_path / "denied",
        publish_base_url=False,
        env_overrides={
            "TOKEN_BUDGET_ENABLED": "1",
            "TOKEN_BUDGET_GUEST_DAILY_TOKENS": "50",
            "TOKEN_BUDGET_GUEST_DAILY_USD": "0.00001",
        },
    ) as runtime:
        r = requests.get(
            runtime["base_url"] + "/api/v1/recommend/suggest",
            headers={"x-api-key": "local-merchant-key"},
            params={"uid": "guest-" + uuid.uuid4().hex, "query": "laptop"},
            timeout=15,
        )
        assert r.status_code == 429, r.text[:500]
        assert r.json()["detail"]["reason"] == "quota:daily_token_limit"
        assert r.headers["X-Rate-Limit-Reason"] == "daily_token_limit"
        assert float(r.headers["X-Rate-Limit-Tokens-Remaining"]) == 50
        assert not r.json().get("products")
