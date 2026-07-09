"""E1 response-shape stage — tier split parity with the former inline block."""
from __future__ import annotations

from src.app.services.recommend_response_shape import apply_recommendation_tiers


def _tiers_stub(results, **kw):
    return {"minimum": results[:1], "recommended": results[1:2], "show_split": False}


def test_tiers_stamped_from_results():
    payload = {}
    apply_recommendation_tiers(
        payload, results=[{"sku": "A"}, {"sku": "B"}], constraints={"budget_max": 2000},
        query="gaming laptop",
        parse_explicit_spec_blocks=lambda q: {"has_explicit_blocks": False},
        build_minimum_recommended_tiers=_tiers_stub,
    )
    assert payload["recommendation_tiers"]["minimum"] == [{"sku": "A"}]
    assert payload["recommendation_tiers"]["show_split"] is False
    assert payload["explicit_spec_blocks"] == {"has_explicit_blocks": False}


def test_explicit_blocks_force_split_and_explanations():
    payload = {}
    apply_recommendation_tiers(
        payload, results=[{"sku": "A"}, {"sku": "B"}], constraints={},
        query="min: 16gb ram, rec: 32gb ram",
        parse_explicit_spec_blocks=lambda q: {"has_explicit_blocks": True, "minimum": {"ram": 16}, "recommended": {"ram": 32}},
        build_minimum_recommended_tiers=_tiers_stub,
    )
    t = payload["recommendation_tiers"]
    assert t["show_split"] is True
    assert "minimum spec block" in t["minimum_explanation"]
    assert "recommended spec block" in t["recommended_explanation"]


def test_helper_raise_falls_back_to_empty_tiers():
    payload = {}
    def _boom(*a, **k):
        raise RuntimeError("tier build failed")
    apply_recommendation_tiers(
        payload, results=[{"sku": "A"}], constraints={}, query="x",
        parse_explicit_spec_blocks=lambda q: {"has_explicit_blocks": False},
        build_minimum_recommended_tiers=_boom,
    )
    assert payload["recommendation_tiers"] == {"minimum": [], "recommended": [], "show_split": False}
