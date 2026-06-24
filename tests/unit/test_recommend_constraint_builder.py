"""Tests for recommend_constraint_builder — the extracted constraint assembly logic."""
import pytest
from src.app.services.recommend_constraint_builder import (
    build_initial_constraints,
    enrich_constraints_with_persona,
    merge_accumulated_slots,
    merge_confirmed_slots,
)


def _noop_pref(*args, **kwargs):
    """Simulates an empty decayed preference lookup."""
    if len(args) > 1:
        return args[1]  # default
    return None


class TestBuildInitialConstraints:
    def test_basic_assembly(self):
        c = build_initial_constraints(
            uid_hash="abc123",
            query="gaming laptop under 1500",
            budget_min=None,
            budget_max=1500,
            nlp={"intent": "product_search", "preferences": {"use_case": "gaming"}, "slots": {}},
            parsed={"brands": ["ASUS"]},
            confirmed_slots={},
            decayed_pref_fn=_noop_pref,
            shortlist_lock_active=False,
            turn_intent="SEARCH",
            locale="en",
        )
        assert c["budget_max"] == 1500
        assert c["brands"] == ["ASUS"]
        assert c["intent"] == "product_search"
        assert c["use_case"] == "gaming"
        assert c["turn_intent"] == "SEARCH"
        assert c["locale"] == "en"
        assert c["_request_budget_max"] == 1500

    def test_priority_request_over_nlp(self):
        """Request param budget_max wins over NLP parsed budget."""
        c = build_initial_constraints(
            uid_hash="x",
            query="laptop",
            budget_min=None,
            budget_max=2000,
            nlp={"preferences": {"budget_max": 1500}, "slots": {}},
            parsed={},
            confirmed_slots={},
            decayed_pref_fn=_noop_pref,
            shortlist_lock_active=False,
            turn_intent="SEARCH",
            locale=None,
        )
        assert c["budget_max"] == 2000

    def test_fallback_to_decayed_pref(self):
        """When nothing else provides a value, decayed pref is used."""
        def pref_fn(key, default=None):
            if key == "use_case":
                return "office"
            return default

        c = build_initial_constraints(
            uid_hash="x",
            query="laptop",
            budget_min=None,
            budget_max=None,
            nlp={"preferences": {}, "slots": {}},
            parsed={},
            confirmed_slots={},
            decayed_pref_fn=pref_fn,
            shortlist_lock_active=False,
            turn_intent="SEARCH",
            locale=None,
        )
        assert c["use_case"] == "office"

    def test_no_budget_returns_none(self):
        c = build_initial_constraints(
            uid_hash="x",
            query="something portable",
            budget_min=None,
            budget_max=None,
            nlp={"preferences": {}, "slots": {}},
            parsed={},
            confirmed_slots={},
            decayed_pref_fn=_noop_pref,
            shortlist_lock_active=False,
            turn_intent="SEARCH",
            locale=None,
        )
        assert c["budget_max"] is None
        assert c["budget_min"] is None

    def test_pii_scrubbed_from_query(self):
        c = build_initial_constraints(
            uid_hash="x",
            query="my email is test@example.com and I want a laptop",
            budget_min=None,
            budget_max=None,
            nlp={"preferences": {}, "slots": {}},
            parsed={},
            confirmed_slots={},
            decayed_pref_fn=_noop_pref,
            shortlist_lock_active=False,
            turn_intent="SEARCH",
            locale=None,
        )
        # scrub_pii should redact the email
        assert "test@example.com" not in c["query"]


class TestEnrichConstraintsWithPersona:
    def test_high_confidence_persona(self):
        c = {}
        enrich_constraints_with_persona(
            c, buyer_persona="gamer", buyer_persona_confidence=0.8,
            persona_scores={"gamer": 3, "student": 1}, persona_min_confidence=0.34,
        )
        assert c["buyer_persona"] == "gamer"
        assert c["buyer_persona_confidence"] == 0.8
        assert "buyer_persona_low_confidence" not in c

    def test_low_confidence_persona(self):
        c = {}
        enrich_constraints_with_persona(
            c, buyer_persona="traveler", buyer_persona_confidence=0.2,
            persona_scores=None, persona_min_confidence=0.34,
        )
        assert c.get("buyer_persona_candidate") == "traveler"
        assert c.get("buyer_persona_low_confidence") is True

    def test_no_persona(self):
        c = {}
        enrich_constraints_with_persona(
            c, buyer_persona=None, buyer_persona_confidence=0.0,
            persona_scores=None,
        )
        assert "buyer_persona" not in c


class TestMergeAccumulatedSlots:
    def test_fills_empty_slots(self):
        c = {"budget_min": None, "budget_max": None, "use_case": None, "use_case_tags": None}
        merge_accumulated_slots(c, {"budget_max": 2000, "use_case": "gaming", "gpu_preference": "discrete"})
        assert c["budget_max"] == 2000
        assert c["use_case"] == "gaming"
        assert c["gpu_preference"] == "discrete"

    def test_does_not_overwrite_existing(self):
        c = {"budget_max": 1500, "use_case": "office"}
        merge_accumulated_slots(c, {"budget_max": 2000, "use_case": "gaming"})
        assert c["budget_max"] == 1500
        assert c["use_case"] == "office"

    def test_handles_empty_accumulated(self):
        c = {"budget_max": None}
        merge_accumulated_slots(c, {})
        assert c["budget_max"] is None


class TestMergeConfirmedSlots:
    def test_fills_none_budget(self):
        c = {"budget_min": None, "budget_max": None, "use_case": None, "brands": [], "specs": [],
             "availability": None, "condition": None}
        merge_confirmed_slots(c, {"budget_max": 1800, "brands": ["Dell", "HP"]})
        assert c["budget_max"] == 1800
        assert c["brands"] == ["Dell", "HP"]

    def test_does_not_overwrite_existing_budget(self):
        c = {"budget_min": None, "budget_max": 1200, "use_case": "office", "brands": ["Lenovo"],
             "specs": [], "availability": None, "condition": None}
        merge_confirmed_slots(c, {"budget_max": 2000, "brands": ["HP"]})
        assert c["budget_max"] == 1200
        assert c["brands"] == ["Lenovo"]

    def test_brand_list_capped_at_8(self):
        c = {"brands": [], "specs": [], "budget_min": None, "budget_max": None,
             "use_case": None, "availability": None, "condition": None}
        merge_confirmed_slots(c, {"brands": list(range(20))})
        assert len(c["brands"]) == 8
