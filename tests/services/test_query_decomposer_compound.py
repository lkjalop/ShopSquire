"""Step-1 intent foundation: compound→primary resolution, bare-budget anchor, quantity capture,
plural category, and business/corporate use-case matching. These lock the verified before/after on
the two real compound queries so the gains can't silently regress.
"""
from __future__ import annotations

from src.app.services.query_decomposer import decompose


def test_compound_corporate_or_gaming_retains_both_and_surfaces_products():
    d = decompose(
        "budget is 1400 to 1700, what to get for corporate work or gaming? do i need an external hard drive?"
    ).to_dict()
    assert d["intent"] == "product_search"            # was 'knowledge' (HDD clause hijacked it)
    assert d["answer_without_products"] is False        # must surface laptops, not prose-only
    assert "gaming" in d["use_cases"] and "office" in d["use_cases"]  # both directions kept
    assert d["category"] != "storage"                   # accessory clause no longer hijacks category
    assert d["budget_min"] == 1400 and d["budget_max"] == 1700


def test_bulk_business_query_extracts_qty_budget_category_usecase():
    d = decompose(
        "i am thinking of getting 10 new laptops for business, budget is 1600, what to get? "
        "would there be any in 4 weeks?"
    ).to_dict()
    assert d["category"] == "laptop"                    # plural "laptops" now matches
    assert "office" in d["use_cases"]                   # "business" now matches the office pattern
    assert d["budget_max"] == 1600                      # bare "budget is 1600" anchor
    assert d["quantity"] == 10                          # bulk quantity captured...


def test_quantity_does_not_misread_time_units():
    # "4 weeks" is a duration, never a quantity.
    assert decompose("can you deliver in 4 weeks").to_dict()["quantity"] is None


def test_bare_budget_anchor_and_under_form():
    assert decompose("laptop budget is 1600").to_dict()["budget_max"] == 1600
    assert decompose("laptop budget of 2000").to_dict()["budget_max"] == 2000
    assert decompose("10 business laptops under $1500").to_dict()["budget_max"] == 1500


# ── Step 3a: availability intent + horizon ───────────────────────────────────
def test_compound_product_plus_availability_splits_and_captures_horizon():
    plan = decompose(
        "i am thinking of getting 10 new laptops for business, budget is 1600, what to get? "
        "would there be any in 4 weeks?"
    )
    assert plan.is_compound is True
    assert "availability" in [s.intent for s in plan.sub_questions]
    assert plan.availability_horizon_days == 28          # 4 weeks → 28 days
    assert plan.quantity == 10


def test_availability_rider_keeps_product_primary():
    # An availability rider on a product request must NOT flip the turn to availability-only.
    d = decompose("10 business laptops under $1600, can you deliver in 4 weeks?").to_dict()
    assert d["intent"] == "product_search"
    assert d["category"] == "laptop" and d["quantity"] == 10
    assert d["availability_horizon_days"] == 28


def test_pure_availability_query_stays_availability():
    d = decompose("when can you deliver?").to_dict()
    assert d["intent"] == "availability"
    assert not d["category"] and not d["use_cases"]


def test_exact_bulk_reference_query_keeps_full_structured_state():
    plan = decompose(
        "I am thinking to buy 10 laptops for work in 2 weeks, "
        "what is good for 1300 to 1500? why those?"
    )
    assert plan.category == "laptop"
    assert plan.budget_min == 1300 and plan.budget_max == 1500
    assert plan.quantity == 10 and plan.availability_horizon_days == 14
    assert "office" in plan.use_cases
    assert plan.is_compound is True
    assert plan.intent == "product_search"
    assert plan.answer_without_products is False
