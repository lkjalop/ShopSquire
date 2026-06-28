"""Budget-band ranking truth: over-budget is classified + DEMOTED with a dominating penalty so it can
never outrank an in-budget unit (the $4,500-for-$1,900 trust bug), and filter_to_band never empties."""
from __future__ import annotations

from src.app.services.recommend_budget_band import band_status, budget_rank_penalty, filter_to_band


def test_band_status_in_stretch_over_under():
    # budget 1300-1900 (dollars); price in cents
    assert band_status(150000, 1300, 1900) == "in"
    assert band_status(200000, None, 1900) == "stretch"   # $2000 = 5% over 1900 (<=10% tol)
    assert band_status(450000, None, 1900) == "over"      # $4500 way over
    assert band_status(50000, 1300, None) == "under"      # $500 < 40% of 1300 floor
    assert band_status(None, 1300, 1900) == "unknown"
    assert band_status(150000, None, None) == "in"        # no budget -> in by default


def test_over_budget_penalty_dominates_max_use_case_score():
    # a perfect use-case + brand + bonuses tops out around ~+100; the over penalty must swamp it
    max_positive = 30 + 35 + 22 + 12 + 8 + 10 + 6  # laptop+meets+brand+known+budget bonuses
    assert budget_rank_penalty("over") + max_positive < budget_rank_penalty("in")
    assert budget_rank_penalty("over") <= -1000.0
    assert budget_rank_penalty("in") == 0.0
    assert budget_rank_penalty("stretch") < 0 and budget_rank_penalty("stretch") > -100


def test_filter_to_band_drops_over_and_tags():
    cands = [{"sku": "A", "price_cents": 140000}, {"sku": "B", "price_cents": 180000},
             {"sku": "C", "price_cents": 450000}]  # C is over $1900
    out = filter_to_band(cands, 1300, 1900, min_keep=2)
    assert [c["sku"] for c in out] == ["A", "B"]
    assert all(c["budget_fit"] in ("in", "stretch", "under") for c in out)


def test_filter_to_band_never_empties_readds_cheapest_over_as_stretch():
    # all over budget → keep the cheapest, tagged stretch (never an empty result)
    cands = [{"sku": "X", "price_cents": 500000}, {"sku": "Y", "price_cents": 300000},
             {"sku": "Z", "price_cents": 400000}]
    out = filter_to_band(cands, None, 1900, min_keep=2)
    assert len(out) == 2
    assert out[0]["sku"] == "Y" and out[0]["budget_fit"] == "stretch"  # cheapest re-added first
    assert all(c["budget_fit"] == "stretch" for c in out)


def test_filter_to_band_no_budget_keeps_all():
    cands = [{"sku": "A", "price_cents": 140000}, {"sku": "B", "price_cents": 450000}]
    out = filter_to_band(cands, None, None)
    assert len(out) == 2 and all(c["budget_fit"] == "in" for c in out)
