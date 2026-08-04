"""Tests for the Round 2 digital-marketing enhancements:

  1. update_profile_from_intent — persona/brands/use-case propagation
  2. refine_profile_from_outcome — accessory acceptance/rejection tracking
  3. ShopperIntent → constraints injection (via recommend.py wiring)
  4. Event-driven orchestrator budget adaptation
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. update_profile_from_intent
# ---------------------------------------------------------------------------
from src.app.services.episodic_memory import EpisodicMemory
from src.app.services.memory import Memory
from src.app.services.use_case_advisor import extract_shopper_intent


def _make_mem() -> Memory:
    """Return the real scoped-memory contract over a mocked Redis transport."""
    redis = MagicMock()
    redis.get.return_value = None
    Memory._LOCAL_STORE.clear()
    Memory._LOCAL_INDEX.clear()
    mem = Memory(redis)
    return mem


def _make_intent(**overrides) -> SimpleNamespace:
    """Build a lightweight ShopperIntentResult-like object."""
    defaults = dict(
        persona="gamer",
        budget_tier="mid",
        price_sensitivity="medium",
        brands_positive=["asus"],
        brands_negative=["hp"],
        use_case_key="gaming_competitive",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestUpdateProfileFromIntent:
    def test_persona_propagated(self):
        em = EpisodicMemory(_make_mem())
        intent = _make_intent(persona="creator")
        profile = em.update_profile_from_intent("u1", intent)
        assert profile.inferred_persona == "creator"

    def test_budget_tier_propagated(self):
        em = EpisodicMemory(_make_mem())
        intent = _make_intent(budget_tier="premium")
        profile = em.update_profile_from_intent("u1", intent)
        assert profile.budget_tier == "premium"

    def test_price_sensitivity_propagated(self):
        em = EpisodicMemory(_make_mem())
        intent = _make_intent(price_sensitivity="high")
        profile = em.update_profile_from_intent("u1", intent)
        assert profile.price_sensitivity == "high"

    def test_brands_accumulated(self):
        em = EpisodicMemory(_make_mem())
        intent = _make_intent(brands_positive=["lenovo", "dell"], brands_negative=["acer"])
        profile = em.update_profile_from_intent("u1", intent)
        assert "lenovo" in profile.preferred_brands
        assert "dell" in profile.preferred_brands
        assert "acer" in profile.avoided_brands

    def test_use_case_accumulated(self):
        em = EpisodicMemory(_make_mem())
        intent = _make_intent(use_case_key="ai_ml_workstation")
        profile = em.update_profile_from_intent("u1", intent)
        assert "ai_ml_workstation" in profile.typical_use_cases

    def test_session_count_incremented(self):
        em = EpisodicMemory(_make_mem())
        p1 = em.update_profile_from_intent("u1", _make_intent())
        assert p1.session_count == 1
        # Subsequent call should read back the profile and increment again
        # (need to mock redis to return the saved profile)
        mem = _make_mem()
        mem.redis.get.return_value = json.dumps({
            "user_id": "u1",
            "preferred_brands": ["asus"],
            "avoided_brands": ["hp"],
            "budget_tier": "mid",
            "typical_use_cases": ["gaming_competitive"],
            "purchase_history_summary": [],
            "last_session_summary": None,
            "inferred_persona": "gamer",
            "accessory_acceptances": {},
            "accessory_rejections": {},
            "upsell_acceptance_rate": None,
            "price_sensitivity": "medium",
            "session_count": 1,
            "updated_at": time.time(),
        })
        em2 = EpisodicMemory(mem)
        p2 = em2.update_profile_from_intent("u1", _make_intent())
        assert p2.session_count == 2

    def test_unknown_persona_ignored(self):
        em = EpisodicMemory(_make_mem())
        intent = _make_intent(persona="unknown")
        profile = em.update_profile_from_intent("u1", intent)
        assert profile.inferred_persona is None  # not overwritten

    def test_session_summary_stored(self):
        em = EpisodicMemory(_make_mem())
        profile = em.update_profile_from_intent("u1", _make_intent(), session_summary="user wants a gaming laptop")
        assert profile.last_session_summary == "user wants a gaming laptop"


# ---------------------------------------------------------------------------
# 2. refine_profile_from_outcome
# ---------------------------------------------------------------------------
class TestRefineProfileFromOutcome:
    def test_accessory_acceptance(self):
        em = EpisodicMemory(_make_mem())
        profile = em.refine_profile_from_outcome("u1", {
            "accessory_slug": "gaming-mouse",
            "upsell_clicked": True,
        })
        assert profile.accessory_acceptances.get("gaming-mouse") == 1

    def test_accessory_rejection(self):
        em = EpisodicMemory(_make_mem())
        profile = em.refine_profile_from_outcome("u1", {
            "accessory_slug": "extended-warranty",
            "upsell_clicked": False,
        })
        assert profile.accessory_rejections.get("extended-warranty") == 1

    def test_upsell_acceptance_rate_calculation(self):
        mem = _make_mem()
        em = EpisodicMemory(mem)
        # Simulate existing profile with 2 acceptances, 1 rejection
        mem.redis.get.return_value = json.dumps({
            "user_id": "u1",
            "preferred_brands": [],
            "avoided_brands": [],
            "budget_tier": None,
            "typical_use_cases": [],
            "purchase_history_summary": [],
            "last_session_summary": None,
            "inferred_persona": None,
            "accessory_acceptances": {"mouse": 2},
            "accessory_rejections": {"warranty": 1},
            "upsell_acceptance_rate": None,
            "price_sensitivity": None,
            "session_count": 0,
            "updated_at": time.time(),
        })
        profile = em.refine_profile_from_outcome("u1", {
            "accessory_slug": "charger",
            "bundle_purchased": True,
        })
        # 2 (mouse) + 1 (charger) = 3 accepts, 1 reject → 3/4 = 0.75
        assert profile.upsell_acceptance_rate == 0.75

    def test_purchased_sku_tracked(self):
        em = EpisodicMemory(_make_mem())
        profile = em.refine_profile_from_outcome("u1", {
            "purchased_sku": "SKU-1234",
        })
        assert "SKU-1234" in profile.purchase_history_summary

    def test_empty_slug_ignored(self):
        em = EpisodicMemory(_make_mem())
        profile = em.refine_profile_from_outcome("u1", {
            "accessory_slug": "",
            "upsell_clicked": True,
        })
        assert len(profile.accessory_acceptances) == 0

    def test_no_accessory_slug_keeps_empty(self):
        em = EpisodicMemory(_make_mem())
        profile = em.refine_profile_from_outcome("u1", {
            "upsell_clicked": True,
        })
        assert len(profile.accessory_acceptances) == 0


# ---------------------------------------------------------------------------
# 3. ShopperIntent → constraints injection (unit-level)
# ---------------------------------------------------------------------------
class TestShopperIntentConstraintsInjection:
    """Verify that extract_shopper_intent produces correct output from a
    constraints-like SimpleNamespace, mirroring how recommend.py calls it."""

    def _build_pq(self, **kwargs) -> SimpleNamespace:
        defaults = dict(
            intent="recommend",
            intent_confidence=0.85,
            budget_min=500,
            budget_max=1200,
            brands_positive=["dell"],
            brands_negative=["hp"],
            use_case_hints=["gaming_competitive"],
            raw_query="I need a gaming laptop under $1200",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_persona_from_use_case(self):
        pq = self._build_pq(use_case_hints=["content_creation"])
        result = extract_shopper_intent(pq)
        assert result.persona == "creator"

    def test_priority_factors_populated(self):
        pq = self._build_pq(use_case_hints=["gaming_competitive"])
        result = extract_shopper_intent(pq)
        assert isinstance(result.priority_factors, list)

    def test_accessory_affinities_populated(self):
        pq = self._build_pq(use_case_hints=["gaming_competitive"])
        result = extract_shopper_intent(pq)
        assert isinstance(result.accessory_affinities, list)

    def test_urgency_from_raw_query(self):
        pq = self._build_pq(raw_query="I need a laptop urgently")
        result = extract_shopper_intent(pq)
        assert result.urgency == "high"

    def test_bundle_receptivity_for_recommend(self):
        pq = self._build_pq(intent="recommend")
        result = extract_shopper_intent(pq)
        assert result.bundle_receptivity == "high"

    def test_session_slots_override(self):
        pq = self._build_pq(budget_max=None)
        result = extract_shopper_intent(pq, session_slots={"budget_max": 800})
        assert result.budget_max == 800
        assert result.price_sensitivity == "medium"

    def test_profile_fallback_persona(self):
        pq = self._build_pq(use_case_hints=[])
        profile = SimpleNamespace(typical_use_cases=["office_general"])
        result = extract_shopper_intent(pq, user_profile=profile)
        assert result.persona == "office"

    def test_to_dict_has_all_keys(self):
        pq = self._build_pq()
        result = extract_shopper_intent(pq)
        d = result.to_dict()
        expected_keys = {
            "persona", "primary_intent", "secondary_needs", "budget_min",
            "budget_max", "budget_tier", "price_sensitivity", "urgency",
            "bundle_receptivity", "brands_positive", "brands_negative",
            "use_case_key", "accessory_affinities", "priority_factors",
            "confidence", "warranty_tag",
        }
        assert expected_keys.issubset(set(d.keys()))


# ---------------------------------------------------------------------------
# 4. Event-driven orchestrator budget adaptation
# ---------------------------------------------------------------------------
class TestEventDrivenBudget:
    """Test _compute_adaptive_agent_budgets with event_signals."""

    def _make_orchestrator(self) -> Any:
        from src.app.services.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        orch.flags = {"AGENT_TOKEN_BUDGET_DEFAULT": 2200}
        return orch

    def _base_kwargs(self) -> Dict[str, Any]:
        return dict(
            query="compare gaming laptops",
            tier=1,
            base_tool_budget=4,
            risk_adj=0.0,
            intent_confidence=1.0,
            multi_turn=False,
        )

    @patch("src.app.routers.admin_grc.get_latest_risk_bands", side_effect=Exception("no GRC"))
    def test_no_events_baseline(self, _mock):
        orch = self._make_orchestrator()
        result = orch._compute_adaptive_agent_budgets(**self._base_kwargs(), event_signals=None)
        assert "global_tool_budget" in result
        baseline_factor = result["factor"]
        # Verify factor doesn't include event boosts
        assert baseline_factor < 2.0

    @patch("src.app.routers.admin_grc.get_latest_risk_bands", side_effect=Exception("no GRC"))
    def test_cart_abandonment_boosts_ranking(self, _mock):
        orch = self._make_orchestrator()
        baseline = orch._compute_adaptive_agent_budgets(**self._base_kwargs(), event_signals=None)
        boosted = orch._compute_adaptive_agent_budgets(
            **self._base_kwargs(),
            event_signals={"cart_abandonment_detected": True},
        )
        # Factor should be higher
        assert boosted["factor"] > baseline["factor"]

    @patch("src.app.routers.admin_grc.get_latest_risk_bands", side_effect=Exception("no GRC"))
    def test_coupon_abuse_boosts_security(self, _mock):
        orch = self._make_orchestrator()
        baseline = orch._compute_adaptive_agent_budgets(**self._base_kwargs(), event_signals=None)
        boosted = orch._compute_adaptive_agent_budgets(
            **self._base_kwargs(),
            event_signals={"coupon_abuse_signals": True},
        )
        assert boosted["factor"] > baseline["factor"]
        # Security agent should get more tokens
        sec_tokens_base = baseline["agent_token_budgets"].get("Security_Observer_Agent", 0)
        sec_tokens_boost = boosted["agent_token_budgets"].get("Security_Observer_Agent", 0)
        assert sec_tokens_boost >= sec_tokens_base

    @patch("src.app.routers.admin_grc.get_latest_risk_bands", side_effect=Exception("no GRC"))
    def test_high_value_session_boosts_factor(self, _mock):
        orch = self._make_orchestrator()
        baseline = orch._compute_adaptive_agent_budgets(**self._base_kwargs(), event_signals=None)
        boosted = orch._compute_adaptive_agent_budgets(
            **self._base_kwargs(),
            event_signals={"high_value_session": True},
        )
        assert boosted["factor"] > baseline["factor"]

    @patch("src.app.routers.admin_grc.get_latest_risk_bands", side_effect=Exception("no GRC"))
    def test_combined_events_stack(self, _mock):
        orch = self._make_orchestrator()
        single = orch._compute_adaptive_agent_budgets(
            **self._base_kwargs(),
            event_signals={"cart_abandonment_detected": True},
        )
        combined = orch._compute_adaptive_agent_budgets(
            **self._base_kwargs(),
            event_signals={
                "cart_abandonment_detected": True,
                "coupon_abuse_signals": True,
                "high_value_session": True,
            },
        )
        assert combined["factor"] > single["factor"]

    @patch("src.app.routers.admin_grc.get_latest_risk_bands", side_effect=Exception("no GRC"))
    def test_empty_event_signals_same_as_none(self, _mock):
        orch = self._make_orchestrator()
        none_result = orch._compute_adaptive_agent_budgets(**self._base_kwargs(), event_signals=None)
        empty_result = orch._compute_adaptive_agent_budgets(**self._base_kwargs(), event_signals={})
        assert none_result["factor"] == empty_result["factor"]
