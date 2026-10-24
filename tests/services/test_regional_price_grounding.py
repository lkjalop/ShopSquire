"""Regional money controls use dated manufacturer observations, never live offers."""
from datetime import datetime, timezone
from pathlib import Path
import json
import itertools

import pytest

from src.app.services.shopping_case_commercial_projection import project_case_commercial_decision

DATA = json.loads((Path(__file__).parents[1] / "fixtures/regional_price_observations_2026-10-24.json").read_text(encoding="utf-8"))
OBSERVATIONS = DATA["observations"]
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def project(price, budget_currency, *, scope="total", price_currency="observed"):
    observed = price["offers"][0]["pack_price_minor"]
    quantity = 4
    return project_case_commercial_decision(
        state_data={"selected_sku": "FICTIONAL-SKU", "requested_quantity": quantity,
                    "budget": {"amount_minor": observed * (quantity if scope == "total" else 1),
                               "currency": budget_currency, "scope": scope}},
        fulfilment={"unit_price_cents": observed,
                    "currency": price["currency"] if price_currency == "observed" else price_currency,
                    "available_now": quantity},
        evaluation_time=NOW)


@pytest.mark.parametrize("price", OBSERVATIONS, ids=lambda item: item["country"])
@pytest.mark.parametrize("scope", ["total", "per_unit"])
def test_observed_same_currency_price_keeps_the_positive(price, scope):
    result = project(price, price["currency"], scope=scope)
    assert result["budget_outcome"] == "within"
    assert result["cart_authority"] == result["supplier_send_authority"] == "none"


PAIRS = [(price, budget["currency"]) for price, budget in itertools.permutations(OBSERVATIONS, 2)]
@pytest.mark.parametrize("price,budget_currency", PAIRS, ids=[f"{p['currency']}-price-{c}-budget" for p,c in PAIRS])
@pytest.mark.parametrize("scope", ["total", "per_unit"])
def test_raw_minor_units_in_different_currencies_cannot_establish_budget_fit(price, budget_currency, scope):
    result = project(price, budget_currency, scope=scope)
    assert result["budget_outcome"] == "unknown"
    assert result["status"] == "UNVERIFIED"
    assert any("currency" in reason.lower() for reason in result["reasons"])


@pytest.mark.parametrize("price", OBSERVATIONS, ids=lambda item: item["country"])
def test_missing_budget_currency_requires_clarification(price):
    assert project(price, None)["budget_outcome"] == "unknown"


@pytest.mark.parametrize("price", OBSERVATIONS, ids=lambda item: item["country"])
def test_missing_price_currency_cannot_default_to_aud(price):
    assert project(price, price["currency"], price_currency=None)["budget_outcome"] == "unknown"


@pytest.mark.parametrize("second_price,second_currency", [(8000, "EUR"), (8000, "USD")])
def test_conflicting_quotes_cannot_be_minimized_into_one_order_price(second_price, second_currency):
    offers = [{"offered_sku": "FICTIONAL-SKU", "relationship": "exact", "quantity_available": 2,
               "lead_time_days": 2, "unit_price_cents": amount, "currency": currency,
               "trust_status": "trusted", "response_status": "accepted"}
              for amount, currency in [(9900, "USD"), (second_price, second_currency)]]
    result = project_case_commercial_decision(
        state_data={"selected_sku": "FICTIONAL-SKU", "requested_quantity": 4,
                    "budget": {"amount_minor": 40000, "currency": "USD", "scope": "total"}},
        fulfilment={"available_now": 0, "offers": offers}, evaluation_time=NOW)
    assert result["quantity_outcome"] == "complete_by_deadline"
    assert result["budget_outcome"] == "unknown"
    assert result["status"] == "UNVERIFIED"


def test_identical_declared_quote_prices_keep_the_price_positive():
    offer = {"offered_sku": "FICTIONAL-SKU", "relationship": "exact", "quantity_available": 4,
             "lead_time_days": 2, "unit_price_cents": 9900, "currency": "USD",
             "trust_status": "trusted", "response_status": "accepted"}
    result = project_case_commercial_decision(
        state_data={"selected_sku": "FICTIONAL-SKU", "requested_quantity": 4,
                    "budget": {"amount_minor": 40000, "currency": "USD", "scope": "total"}},
        fulfilment={"available_now": 0, "offers": [offer]}, evaluation_time=NOW)
    assert result["quantity_outcome"] == "complete_by_deadline"
    assert result["budget_outcome"] == "within"
