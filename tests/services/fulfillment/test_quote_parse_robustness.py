"""Robust supplier-quote parsing: real-world formats (currency codes/symbols, thousands separators,
named-month dates, lead-time-in-days, per-unit price preference, qty synonyms) parse correctly, while
ambiguous numeric dates are deliberately NOT guessed. The RAW body stays authoritative; nothing invented.
"""
from __future__ import annotations

from src.app.services.fulfillment import external_comms as ec


def test_currency_code_after_amount_with_thousands_separator():
    pq = ec.parse_quote("We can supply 100 units at 1,250.00 USD each. Valid until 2026-07-15.")
    assert pq["quoted_quantity"] == 100
    assert pq["unit_amount_cents"] == 125000
    assert pq["currency"] == "USD"


def test_currency_code_before_amount():
    pq = ec.parse_quote("Price USD 1250 per unit for 10 units.")
    assert pq["unit_amount_cents"] == 125000 and pq["currency"] == "USD"


def test_euro_symbol_and_decimals():
    pq = ec.parse_quote("Quote: 5 units at €1,234.50 each")
    assert pq["unit_amount_cents"] == 123450 and pq["currency"] == "EUR"


def test_named_month_dispatch_date_is_normalised_to_iso():
    pq = ec.parse_quote("12 units at $900 each, ready to dispatch on 3 July 2026, valid until 2026-07-31.")
    assert pq["dispatch_ready_at"] == "2026-07-03"
    assert pq["quote_expires_at"] == "2026-07-31"


def test_month_first_named_date():
    pq = ec.parse_quote("6 units at $900 each. Valid until July 3, 2026.")
    assert pq["quote_expires_at"] == "2026-07-03"


def test_lead_time_in_days_is_extracted():
    pq = ec.parse_quote("8 units at $500 each. Lead time 14 business days. Valid until 2026-07-15.")
    assert pq["lead_time_days"] == 14


def test_per_unit_price_preferred_over_line_total():
    pq = ec.parse_quote("6 units. Order total $6000. Price $1000 per unit. Valid until 2026-07-15.")
    assert pq["unit_amount_cents"] == 100000  # the per-unit price, not the $6000 total


def test_qty_synonyms_and_thousands_separator():
    assert ec.parse_quote("qty: 50 at $10 each")["quoted_quantity"] == 50
    assert ec.parse_quote("quantity of 50 at $10 each")["quoted_quantity"] == 50
    assert ec.parse_quote("50 pcs at $10 each")["quoted_quantity"] == 50
    assert ec.parse_quote("1,000 units at $10 each")["quoted_quantity"] == 1000


def test_ambiguous_numeric_date_is_not_guessed():
    # DD/MM vs MM/DD is unsafe — leave it None rather than emit a wrong date
    pq = ec.parse_quote("6 units at $900 each. Valid until 07/03/2026.")
    assert pq["quote_expires_at"] is None


def test_no_signal_body_has_zero_confidence():
    pq = ec.parse_quote("Thanks, we will get back to you shortly.")
    assert pq["confidence"] == 0 and pq["unit_amount_cents"] is None


def test_parsed_lead_time_feeds_the_quote_comparator():
    # the new lead_time_days connects parse_quote → rfq_fanout.compare_quotes
    from src.app.services.fulfillment.rfq_fanout import compare_quotes
    a = ec.parse_quote("10 units at $1200 each. Lead time 20 days.")
    b = ec.parse_quote("10 units at $1200 each. Lead time 5 days.")
    r = compare_quotes([
        {"supplier_ref": "slow", "unit_price_cents": a["unit_amount_cents"], "lead_time_days": a["lead_time_days"]},
        {"supplier_ref": "fast", "unit_price_cents": b["unit_amount_cents"], "lead_time_days": b["lead_time_days"]},
    ])
    assert r["recommended"]["supplier_ref"] == "fast"  # same price, shorter lead wins
