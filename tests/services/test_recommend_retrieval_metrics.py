"""Tier 2 — retrieval parity metrics (pure)."""
from __future__ import annotations

from src.app.services.recommend_retrieval_metrics import (
    compute_parity,
    in_budget_fraction,
    overlap_at_k,
    skus_of,
)


def test_skus_of_filters_blanks():
    assert skus_of([{"sku": "A"}, {"sku": ""}, {"x": 1}, {"sku": "B"}]) == ["A", "B"]


def test_overlap_at_k():
    assert overlap_at_k([], []) == 1.0
    assert overlap_at_k(["A"], []) == 0.0
    assert overlap_at_k(["A", "B", "C"], ["A", "B", "C"]) == 1.0
    # top-3: {A,B,C} vs {A,B,D} -> 2/4
    assert overlap_at_k(["A", "B", "C"], ["A", "B", "D"], k=3) == 0.5
    # k limits the window
    assert overlap_at_k(["A", "B"], ["A", "Z"], k=1) == 1.0


def test_in_budget_fraction():
    items = [{"price": 1000}, {"price": 2000}, {"price": 500}]
    assert in_budget_fraction(items, 800, 1500) == round(1 / 3, 4)
    assert in_budget_fraction([{"name": "x"}], 0, 9999) is None  # no priced items
    assert in_budget_fraction(items, None, None) == 1.0


def test_compute_parity_record():
    shadow = ["A", "B", "C"]
    primary = [{"sku": "A", "price": 1200}, {"sku": "D", "price": 4000}]
    out = compute_parity(
        shadow_skus=shadow, primary_items=primary, shadow_count=20, shadow_latency_ms=420,
        budget_min=None, budget_max=1500, k=5,
    )
    assert out["overlap_at_k"] == round(1 / 4, 4)  # {A,B,C} vs {A,D}
    assert out["primary_count"] == 2 and out["shadow_count"] == 20
    assert out["primary_in_budget"] == 0.5  # 1200 ok, 4000 out
    assert out["shadow_latency_ms"] == 420
    assert out["primary_top_skus"] == ["A", "D"]
