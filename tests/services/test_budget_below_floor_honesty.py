"""The budget advisor must not affirm "Yes, $50 covers these laptops" for a device query whose
budget is below the category floor — that pointed at $8 accessory/junk fallback (Hand Sanitiser).
Guards the honest short verdict + the accessory/gaming exemptions."""
from __future__ import annotations

from src.app.services.recommend_budget_advisor import (
    _build_brand_budget_answer_v2 as answer,
    _below_device_floor_verdict as verdict,
)

_JUNK = [{"sku": "X", "name": "Hand Sanitiser 500ml", "price_cents": 800}]
_SLEEVE = [{"sku": "S", "name": "Laptop Sleeve", "price_cents": 3000}]
_LAPTOP = [{"sku": "L", "name": "Asus TUF Gaming", "price_cents": 120000}]


def _cons(query, bmax, tags):
    return {"budget_max": bmax, "query": query, "budget_tier_tags": tags}


def test_below_floor_laptop_is_honest_no_not_yes():
    out = answer("laptop under $50", _JUNK,
                 _cons("laptop under $50", 50, ["budget_too_low_for_laptop"]))
    assert out.lower().startswith("no")
    assert "short for a laptop" in out
    assert "covers these" not in out          # the hallucination is gone
    assert "hand sanitiser" not in out.lower()


def test_accessory_query_below_50_is_not_blocked():
    # A shopper asking for a sleeve at $50 legitimately gets an answer — not "no laptop".
    assert verdict(_cons("laptop sleeve under $50", 50, ["budget_too_low_for_laptop"])) is None
    out = answer("laptop sleeve under $50", _SLEEVE,
                 _cons("laptop sleeve under $50", 50, ["budget_too_low_for_laptop"]))
    assert "short for a laptop" not in out


def test_gaming_keeps_its_specific_message():
    # The gaming-specific floor message must win (guard is placed AFTER the gaming check).
    out = answer("gaming laptop under $50", _JUNK,
                 {"budget_max": 50, "query": "gaming laptop under $50", "use_case": "gaming",
                  "budget_tier_tags": ["budget_too_low_for_laptop"]})
    assert "gaming-laptop budget" in out


def test_verdict_none_when_budget_ok():
    assert verdict(_cons("laptop under 1500", 1500, [])) is None


def test_verdict_none_for_accessory_tokens():
    for q in ("mouse under $50", "usb hub under $40", "keyboard under $30"):
        assert verdict(_cons(q, 50, ["budget_too_low_for_laptop"])) is None


def test_verdict_category_from_tag():
    out = verdict(_cons("laptop under $50", 50, ["budget_too_low_for_new_laptop"]))
    assert out is not None and "short for a laptop" in out
