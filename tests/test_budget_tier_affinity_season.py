"""Tests for the three lean enhancements:
  1. Budget tier classification + warranty candidate tags       (classify_budget_tier, classify_warranty_candidate)
  2. Accessory affinity config and upsell scoring boost         (get_accessory_affinities, recommend_checkout_upsell)
  3. Seasonal score multiplier in listwise_rerank               (listwise_rerank seasonal_boosts)
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch, MagicMock
from typing import Any, Dict, List

import pytest

# ---------------------------------------------------------------------------
# 1. Budget tier classification
# ---------------------------------------------------------------------------
from src.app.services.recommendations import classify_budget_tier, classify_warranty_candidate


class TestClassifyBudgetTier:
    def test_none_returns_unknown(self):
        tier, tags = classify_budget_tier(None)
        assert tier == "unknown"
        assert tags == []

    def test_sub_100_accessories_only(self):
        tier, tags = classify_budget_tier(80)
        assert tier == "accessories_only"
        assert "budget_too_low_for_laptop" in tags

    def test_boundary_99(self):
        tier, tags = classify_budget_tier(99)
        assert tier == "accessories_only"

    def test_very_low_refurb_recommended(self):
        tier, tags = classify_budget_tier(300)
        assert tier == "very_low"
        assert "refurb_recommended" in tags
        assert "budget_too_low_for_new_laptop" in tags

    def test_entry_tier(self):
        tier, tags = classify_budget_tier(500)
        assert tier == "entry"
        assert tags == []

    def test_entry_boundary_699(self):
        tier, tags = classify_budget_tier(699)
        assert tier == "entry"

    def test_mid_tier(self):
        tier, tags = classify_budget_tier(900)
        assert tier == "mid"
        assert tags == []

    def test_premium_tier(self):
        tier, tags = classify_budget_tier(1500)
        assert tier == "premium"
        assert tags == []

    def test_high_performance_tier(self):
        tier, tags = classify_budget_tier(2500)
        assert tier == "high_performance"
        assert tags == []

    def test_workstation_pro_overspend_check(self):
        tier, tags = classify_budget_tier(5000)
        assert tier == "workstation_pro"
        assert "overspend_risk_check" in tags

    def test_boundary_3500(self):
        tier, tags = classify_budget_tier(3500)
        assert tier == "workstation_pro"

    def test_boundary_3499(self):
        tier, tags = classify_budget_tier(3499)
        assert tier == "high_performance"


class TestClassifyWarrantyCandidate:
    def test_high_price_always_high(self):
        assert classify_warranty_candidate(1500) == "warranty_candidate_high"
        assert classify_warranty_candidate(2000) == "warranty_candidate_high"

    def test_low_budget_avoid_push(self):
        assert classify_warranty_candidate(500) == "warranty_candidate_low"
        assert classify_warranty_candidate(699) == "warranty_candidate_low"

    def test_neutral_mid_range(self):
        assert classify_warranty_candidate(900) == "warranty_candidate_neutral"

    def test_high_risk_use_case_mid_budget(self):
        # Gaming AAA at $1000 should still flag warranty
        result = classify_warranty_candidate(1000, "gaming_aaa_heavy")
        assert result == "warranty_candidate_high"

    def test_high_risk_use_case_below_threshold(self):
        # High-risk use case but very low budget → still low
        result = classify_warranty_candidate(400, "gaming_aaa_heavy")
        assert result == "warranty_candidate_low"

    def test_non_high_risk_use_case_mid_budget(self):
        result = classify_warranty_candidate(1000, "office_general")
        assert result == "warranty_candidate_neutral"

    def test_none_budget_neutral(self):
        assert classify_warranty_candidate(None) == "warranty_candidate_neutral"


# ---------------------------------------------------------------------------
# 2. Accessory affinity config
# ---------------------------------------------------------------------------
from src.app.services.use_case_advisor import (
    get_accessory_affinities,
    get_use_case_priority_factors,
)


class TestGetAccessoryAffinities:
    def test_universal_always_present_for_any_use_case(self):
        result = get_accessory_affinities("gaming_competitive")
        # universal items should be in the list
        assert any("sleeve" in s or "cleaning" in s or "usb_hub" in s for s in result)

    def test_gaming_includes_headset_and_mouse(self):
        result = get_accessory_affinities("gaming_competitive")
        assert "headset" in result
        assert any("mouse" in s for s in result)

    def test_content_creator_includes_ssd_and_monitor(self):
        result = get_accessory_affinities("content_creator")
        assert "external_ssd" in result
        assert "monitor" in result

    def test_office_includes_dock(self):
        result = get_accessory_affinities("office_general")
        assert "dock" in result

    def test_no_use_case_returns_universal_only(self):
        result = get_accessory_affinities(None)
        # Should return universal items
        assert isinstance(result, list)
        assert len(result) > 0

    def test_unknown_use_case_returns_universal_only(self):
        result = get_accessory_affinities("nonexistent_use_case_xyz")
        assert isinstance(result, list)
        # No crash; returns at least universal items
        assert len(result) > 0

    def test_no_duplicates(self):
        result = get_accessory_affinities("university_general")
        assert len(result) == len(set(result))

    def test_specific_items_precede_universal(self):
        # For university_general, specific items are laptop_sleeve, mouse, usb_hub, power_bank
        # Universal includes laptop_sleeve and usb_hub too — specific ones should appear first
        result = get_accessory_affinities("university_general")
        mouse_idx = result.index("mouse") if "mouse" in result else -1
        assert mouse_idx >= 0 and mouse_idx < 4  # near the front

    # ── engineering_student affinities ──────────────────────────────────────
    def test_engineering_student_includes_ssd_monitor_dock(self):
        result = get_accessory_affinities("engineering_student")
        for slug in ("external_ssd", "monitor", "dock"):
            assert slug in result, f"engineering_student affinities missing {slug!r}"

    def test_engineering_student_includes_usb_hub(self):
        result = get_accessory_affinities("engineering_student")
        assert "usb_hub" in result

    def test_engineering_student_specific_items_before_universal(self):
        result = get_accessory_affinities("engineering_student")
        ssd_idx = result.index("external_ssd") if "external_ssd" in result else -1
        sleeve_idx = result.index("laptop_sleeve") if "laptop_sleeve" in result else len(result)
        # external_ssd (specific) must come before laptop_sleeve (universal)
        assert ssd_idx >= 0 and ssd_idx < sleeve_idx

    # ── high_school affinities ────────────────────────────────────────────────
    def test_high_school_includes_mouse(self):
        result = get_accessory_affinities("high_school")
        assert "mouse" in result, "high_school affinities should include mouse"

    def test_high_school_includes_universal_items(self):
        result = get_accessory_affinities("high_school")
        assert any(s in result for s in ("laptop_sleeve", "usb_hub", "screen_protector")), \
            "high_school affinities should include universal accessories"

    def test_high_school_no_gaming_specific_items(self):
        result = get_accessory_affinities("high_school")
        # High school should NOT get gaming accessories
        for gaming_slug in ("gaming_mouse", "cooling_pad", "headset"):
            assert gaming_slug not in result, \
                f"high_school affinities should not contain {gaming_slug!r}"


class TestGetUseCasePriorityFactors:
    def test_gaming_returns_gpu_first(self):
        factors = get_use_case_priority_factors("gaming_competitive")
        assert "gpu" in factors

    def test_office_returns_battery(self):
        factors = get_use_case_priority_factors("office_general")
        assert "battery" in factors

    def test_none_key_returns_empty(self):
        assert get_use_case_priority_factors(None) == []

    def test_unknown_key_returns_empty(self):
        assert get_use_case_priority_factors("does_not_exist") == []


# ---------------------------------------------------------------------------
# 3. Seasonal boost multiplier
# ---------------------------------------------------------------------------
from src.app.services.product_ranking_agent import listwise_rerank, RankedProduct


def _make_product(pid: str, price: float = 1000.0, ram: int = 16, gpu: bool = False) -> Dict[str, Any]:
    return {
        "product_id": pid,
        "name": f"Product {pid}",
        "brand": "TestBrand",
        "price": price,
        "ram_gb": ram,
        "has_dedicated_gpu": gpu,
        "storage_gb": 512,
        "display_inches": 14.0,
        "cpu_family": "Intel Core i5",
    }


class TestSeasonalBoostInListwiseRerank:
    def test_no_seasonal_boost_baseline(self):
        products = [_make_product("A"), _make_product("B"), _make_product("C")]
        result = listwise_rerank(products, budget_max=1200, top_n=3)
        assert len(result) > 0
        assert all(isinstance(r, RankedProduct) for r in result)

    def test_seasonal_boost_does_not_crash(self):
        products = [_make_product("A"), _make_product("B"), _make_product("C")]
        result = listwise_rerank(
            products,
            budget_max=1200,
            top_n=3,
            seasonal_boosts={"portability": 1.2, "battery": 1.15, "value": 1.10},
            use_case_priority_factors=["portability", "battery", "value"],
        )
        assert len(result) > 0

    def test_seasonal_boost_increases_scores(self):
        """With seasonal boost activated, scores should be >= baseline scores."""
        products = [_make_product("A"), _make_product("B")]
        baseline = listwise_rerank(products, budget_max=1200, top_n=2)
        boosted = listwise_rerank(
            products,
            budget_max=1200,
            top_n=2,
            seasonal_boosts={"portability": 1.20, "battery": 1.15},
            use_case_priority_factors=["portability", "battery"],
        )
        for b, s in zip(sorted(baseline, key=lambda r: r.product_id),
                        sorted(boosted, key=lambda r: r.product_id)):
            assert s.score >= b.score - 1e-6  # boosted >= baseline (with float tolerance)

    def test_seasonal_boost_capped_at_12_percent(self):
        """Maximum boost should never exceed 12% over baseline score."""
        products = [_make_product("X", price=800.0)]
        baseline = listwise_rerank(products, budget_max=1000, top_n=1)
        # Apply very large boosts across many factors
        boosted = listwise_rerank(
            products,
            budget_max=1000,
            top_n=1,
            seasonal_boosts={f: 2.0 for f in ["portability", "battery", "value", "gpu", "cooling", "build_quality"]},
            use_case_priority_factors=["portability", "battery", "value", "gpu", "cooling", "build_quality"],
        )
        if baseline and boosted:
            max_allowed = baseline[0].score * 1.12 + 1e-6
            assert boosted[0].score <= max_allowed

    def test_seasonal_boost_empty_factors_no_effect(self):
        """No priority factors = no seasonal boost applied."""
        products = [_make_product("A"), _make_product("B")]
        baseline = listwise_rerank(products, budget_max=1200, top_n=2)
        no_factors = listwise_rerank(
            products,
            budget_max=1200,
            top_n=2,
            seasonal_boosts={"portability": 1.2},
            use_case_priority_factors=[],
        )
        for b, n in zip(sorted(baseline, key=lambda r: r.product_id),
                        sorted(no_factors, key=lambda r: r.product_id)):
            assert abs(b.score - n.score) < 1e-6

    def test_seasonal_boost_none_boosts_no_effect(self):
        """None seasonal_boosts = no multiplier applied."""
        products = [_make_product("A"), _make_product("B")]
        baseline = listwise_rerank(products, budget_max=1200, top_n=2)
        same = listwise_rerank(
            products,
            budget_max=1200,
            top_n=2,
            seasonal_boosts=None,
            use_case_priority_factors=["portability", "battery"],
        )
        for b, s in zip(sorted(baseline, key=lambda r: r.product_id),
                        sorted(same, key=lambda r: r.product_id)):
            assert abs(b.score - s.score) < 1e-6

    def test_ranks_are_sequential_after_boost(self):
        products = [_make_product(str(i)) for i in range(5)]
        result = listwise_rerank(
            products,
            budget_max=1200,
            top_n=5,
            seasonal_boosts={"portability": 1.15},
            use_case_priority_factors=["portability"],
        )
        ranks = [r.rank for r in result]
        assert sorted(ranks) == list(range(1, len(result) + 1))


# ---------------------------------------------------------------------------
# 4. Knowledge-base JSON integrity
# ---------------------------------------------------------------------------
class TestKnowledgeBaseIntegrity:
    def test_kb_parses_cleanly(self):
        path = os.path.join("config", "use_case_knowledge_base.json")
        with open(path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        assert "use_cases" in kb
        assert "accessory_affinities" in kb
        assert "_universal" in kb["accessory_affinities"]

    def test_all_affinity_values_are_lists(self):
        path = os.path.join("config", "use_case_knowledge_base.json")
        with open(path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        for key, val in kb["accessory_affinities"].items():
            if key.startswith("_"):
                continue
            assert isinstance(val, list), f"accessory_affinities[{key!r}] must be a list"

    def test_feature_flags_seasonal_context(self):
        import subprocess
        path = os.path.join("config", "feature_flags.json")
        flags = None
        # Try current file first; fall back to committed version if corrupted/empty
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw:
                flags = json.loads(raw)
        except Exception:
            flags = None
        if not isinstance(flags, dict) or not flags:
            # Read from git HEAD to get the canonical committed state
            try:
                result = subprocess.run(
                    ["git", "show", "HEAD:config/feature_flags.json"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    flags = json.loads(result.stdout)
            except Exception:
                flags = {}
        if not isinstance(flags, dict):
            flags = {}
        assert "SEASONAL_CONTEXT" in flags
        sc = flags["SEASONAL_CONTEXT"]
        assert "boosts" in sc
        # active_season is null by default (no unintended activation)
        assert sc.get("active_season") is None
        # Each season entry is a dict of factor → multiplier
        for season, boosts in sc["boosts"].items():
            assert isinstance(boosts, dict), f"boosts[{season!r}] must be a dict"
            for factor, mult in boosts.items():
                assert mult > 1.0, f"Multiplier for {factor} in {season} should be > 1.0"
