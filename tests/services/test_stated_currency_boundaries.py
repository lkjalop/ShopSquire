"""Currency belongs to money or an explicit currency declaration, not workload acronyms."""
import pytest

from src.app.services.commercial_terms import parse_commercial_terms, stated_currency


@pytest.mark.parametrize("query", [
    "I need 20 laptops for CAD work.",
    "CAD modelling needs 32 GB of RAM.",
    "Keep the CAD workload, change the quantity to 40.",
])
def test_non_monetary_workload_does_not_replace_the_tenant_currency(query):
    assert stated_currency(query) is None
    assert parse_commercial_terms(query, default_currency="AUD").currency == "AUD"


@pytest.mark.parametrize("code", ["AUD", "USD", "EUR", "CAD", "GBP", "JPY"])
@pytest.mark.parametrize("query", ["My total budget is {code} 10,000.", "My total budget is 10,000 {code}."])
def test_amount_prefix_and_suffix_preserve_the_explicit_currency(code, query):
    text = query.format(code=code)
    assert stated_currency(text, money_only=True) == code
    assert parse_commercial_terms(text, default_currency="AUD").currency == code


@pytest.mark.parametrize("query,code", [
    ("Change the currency to EUR", "EUR"),
    ("Quote in CAD, please", "CAD"),
    ("USD", "USD"),
])
def test_currency_declaration_without_an_amount_is_distinct_from_a_money_observation(query, code):
    assert stated_currency(query) == code
    assert stated_currency(query, money_only=True) is None


@pytest.mark.parametrize("query", ["AUD 100 or USD 70", "100 EUR or 100 USD", "$100"])
def test_ambiguous_or_unidentified_money_does_not_invent_an_iso_currency(query):
    assert stated_currency(query) is None
    assert stated_currency(query, money_only=True) is None


@pytest.mark.parametrize("code", ["AUD", "USD", "EUR"])
def test_suffix_currency_is_retained_with_the_total_budget_in_chat_projection(code):
    from src.app.services.chat_turn_projection import _extract_confirmed_slots

    slots = _extract_confirmed_slots(query=f"My total budget is 10,000 {code} for all 40 laptops.")
    assert slots["currency"] == code
    assert slots["budget_scope"] == "total"
    assert slots["total_budget_cents"] == 1_000_000


def test_cad_workload_does_not_conflict_with_an_explicit_australian_budget():
    query = "I need 20 laptops for CAD work, with AUD 40,000 total budget."
    assert stated_currency(query) == "AUD"
    assert parse_commercial_terms(query, default_currency="USD").currency == "AUD"
