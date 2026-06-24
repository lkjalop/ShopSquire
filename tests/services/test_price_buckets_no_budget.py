"""#3 within_budget leak — price buckets must not claim "within budget" when no budget was supplied.

GPT-5.5 saw "within budget" on a no-budget query: build_price_buckets fell through to putting every
product in within_budget when both bounds were None. With no budget there is no budget-relative
bucket, so all buckets stay empty.
"""
from __future__ import annotations

from src.app.services.recommend_budget_parsing import build_price_buckets


def _rows():
    return [
        {"id": "1", "sku": "A", "name": "Laptop A", "price_cents": 119900},
        {"id": "2", "sku": "B", "name": "Laptop B", "price_cents": 219900},
        {"id": "3", "sku": "C", "name": "Laptop C", "price_cents": 89900},
    ]


def test_no_budget_yields_empty_within_budget():
    out = build_price_buckets(results=_rows(), constraints={})
    assert out["within_budget"] == []
    assert out["closest_above_budget"] == [] and out["closest_below_budget"] == []


def test_no_budget_explicit_nulls_also_empty():
    out = build_price_buckets(results=_rows(), constraints={"budget_min": None, "budget_max": None})
    assert out["within_budget"] == []


def test_budget_max_buckets_correctly():
    out = build_price_buckets(results=_rows(), constraints={"budget_max": 1500})
    within_skus = {r["sku"] for r in out["within_budget"]}
    assert within_skus == {"A", "C"}            # 1199, 899 <= 1500
    assert [r["sku"] for r in out["closest_above_budget"]] == ["B"]  # 2199 > 1500


def test_budget_range_buckets_correctly():
    out = build_price_buckets(results=_rows(), constraints={"budget_min": 1000, "budget_max": 1500})
    assert {r["sku"] for r in out["within_budget"]} == {"A"}   # only 1199 in [1000,1500]
    assert {r["sku"] for r in out["closest_below_budget"]} == {"C"}  # 899 < 1000
    assert {r["sku"] for r in out["closest_above_budget"]} == {"B"}  # 2199 > 1500
