"""catalog_scoring (CORE) — the fast-path scorer + shared candidate assembly, extracted from the
two copy-pasted loops in recommend.py. The category boost is QUERY-ANCHORED on the profile's
category_keywords groups (the old scorer hardcoded one vertical's words for every query)."""
from __future__ import annotations

from src.app.services.catalog_scoring import (build_candidate, category_match_boost, coerce_specs,
                                              score_candidate)

_HINTS: dict = {"brand_hints": []}


def _row(price_cents=120000, name="ProBook 14 business laptop", stock=5, specs=None):
    return {"sku": "X-1", "name": name, "price_cents": price_cents, "stock": stock,
            "specs": specs or {}}


def test_coerce_specs_variants():
    assert coerce_specs({"a": 1}) == {"a": 1}
    assert coerce_specs('{"ram_gb": 16}') == {"ram_gb": 16}
    assert coerce_specs("not json") == {}
    assert coerce_specs(None) == {}


def test_category_boost_is_query_anchored():
    # electronics profile: query names the laptop group AND the item matches it -> +30
    assert category_match_boost("probook 14 business laptop", "work laptops budget 1200") == 30.0
    # item matches but the QUERY names no category group -> no boost (the old vertical bias)
    assert category_match_boost("probook 14 business laptop", "something nice for the office") == 0.0
    # query names the group but the item is from another group -> no boost
    assert category_match_boost("tower workstation 32gb", "work laptops budget 1200") == 0.0


def test_over_budget_dominated_below_in_budget():
    fit = {"use_case": "office", "meets": True, "reasons": [], "gaps": []}
    in_budget = score_candidate(_row(price_cents=140000), "work laptops", safe_hints=_HINTS,
                                budget_min=1200, budget_max=1500, use_case_fit=fit)
    over = score_candidate(_row(price_cents=450000), "work laptops", safe_hints=_HINTS,
                           budget_min=1200, budget_max=1500, use_case_fit=fit)
    assert in_budget > over, "an over-budget unit must never outrank an in-budget one"


def test_build_candidate_assembly_contract():
    item = _row()
    out = build_candidate(item, "work laptops budget 1200 to 1500", safe_hints=_HINTS,
                          budget_min=1200, budget_max=1500,
                          use_case_fit_fn=lambda r, q: {"use_case": "office", "meets": True,
                                                        "reasons": ["business_class"], "gaps": []})
    assert out is item  # mutates + returns the same dict (both loops rely on this)
    assert out["score"] > 0 and 0.15 <= out["confidence"] <= 0.99
    assert out["factors"]["positive"][0] == "price_fit"
    assert "business_class" in out["factors"]["positive"]
    assert "in_stock" in out["factors"]["positive"]
    assert 1.0 <= out["score_norm"] <= 99.0


def test_out_of_stock_and_gaps_flow_to_factors():
    out = build_candidate(_row(stock=0), "work laptops", safe_hints=_HINTS,
                          budget_min=None, budget_max=None,
                          use_case_fit_fn=lambda r, q: {"use_case": "gaming", "meets": False,
                                                        "reasons": [], "gaps": ["needs_discrete_gpu"]})
    assert "in_stock" not in out["factors"]["positive"]
    assert out["factors"]["negative"] == ["needs_discrete_gpu"]
