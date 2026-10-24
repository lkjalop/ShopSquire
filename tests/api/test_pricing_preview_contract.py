"""Versioned advisory prices preserve region, authority and rejection boundaries."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


@pytest.fixture
def pricing_client(monkeypatch):
    flags = {"USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 100,
             "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}},
             "KILL_SWITCH": False, "DECISION_LOG_WRITES_ENABLED": False,
             "DEGRADATION": {"enabled": False}, "CHAOS": {"enabled": False}}
    monkeypatch.setattr("src.app.routers.pricing._ff_get_flags", lambda: flags)
    with TestClient(create_app(), headers=default_headers()) as client:
        yield client, flags


@pytest.mark.parametrize("currency,amount", [("AUD", 4900), ("USD", 2900), ("EUR", 3500)])
def test_observed_regional_amount_is_a_preview_without_transaction_authority(pricing_client, currency, amount):
    client, _ = pricing_client
    response = client.get("/api/v1/pricing/suggest", params={
        "uid": "owned-preview-" + uuid4().hex, "cart_total_cents": amount, "currency": currency,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema_version"] == "pricing-preview-v2"
    assert result["currency"] == currency
    assert result["executed"] is False
    assert result["action_authority"] == "none"
    assert result["execution_status"] == "review_required"
    assert result["price_basis"] == "unverified_cart_amount"
    if currency != "AUD":
        # The historical AUD discount thresholds are not regional price policy.
        assert result["proposal"].get("discount_percent") is None


@pytest.mark.parametrize("currency", ["GBP", "XXX", "AUD;DROP TABLE prices"])
def test_unqualified_currency_is_rejected_instead_of_relabelled_aud(pricing_client, currency):
    client, _ = pricing_client
    response = client.get("/api/v1/pricing/suggest", params={
        "uid": "owned-preview-" + uuid4().hex, "cart_total_cents": 4900, "currency": currency,
    })
    assert response.status_code == 422


def test_regional_preview_keeps_the_autonomy_kill_switch(pricing_client):
    client, flags = pricing_client
    flags["KILL_SWITCH"] = True
    response = client.get("/api/v1/pricing/suggest", params={
        "uid": "owned-preview-" + uuid4().hex, "cart_total_cents": 3500, "currency": "EUR",
    })
    assert response.status_code == 503


def test_regional_preview_keeps_the_capability_gate(pricing_client):
    client, flags = pricing_client
    flags["CAPABILITIES"]["pricing"]["enabled"] = False
    response = client.get("/api/v1/pricing/suggest", params={
        "uid": "owned-preview-" + uuid4().hex, "cart_total_cents": 3500, "currency": "EUR",
    })
    assert response.status_code == 503


def test_preview_still_requires_an_operator_identity():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/pricing/suggest", params={
            "uid": "owned-preview-" + uuid4().hex, "cart_total_cents": 3500, "currency": "EUR",
        })
    assert response.status_code == 401
