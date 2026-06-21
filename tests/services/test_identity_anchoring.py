"""Multimodal anchoring (C3) — an image-identified model must steer the results.

Two pieces:
  * specs_to_constraints now emits identity_model (the most specific anchor, previously dropped);
  * identity_anchor_boost floats candidates matching that model line to the top of the scored list.
Together: upload a photo of a specific model -> that product line is anchored, not generic matches.
"""
from __future__ import annotations

from src.app.services.product_identity_agent import specs_to_constraints
from src.app.services.product_ranking_agent import identity_anchor_boost


# ── specs_to_constraints emits identity_model ──
def test_specs_to_constraints_emits_model():
    out = specs_to_constraints({
        "identified": True, "confidence": 0.9, "brand": "Lenovo", "model": "ThinkPad X1 Carbon",
    })
    assert out["identity_brand"] == "Lenovo"
    assert out["identity_model"] == "ThinkPad X1 Carbon"


def test_specs_to_constraints_drops_unknown_model():
    out = specs_to_constraints({"identified": True, "confidence": 0.9, "brand": "Lenovo", "model": "unknown"})
    assert "identity_model" not in out


def test_specs_to_constraints_low_confidence_is_empty():
    assert specs_to_constraints({"identified": True, "confidence": 0.1, "model": "X1"}) == {}


# ── identity_anchor_boost ──
def _scored():
    return [
        {"score": 1.0, "candidate": {"sku": "A", "name": "Generic Notebook 15"}},
        {"score": 0.9, "candidate": {"sku": "B", "name": "Lenovo ThinkPad X1 Carbon Gen 11"}},
        {"score": 0.95, "candidate": {"sku": "C", "name": "Dell XPS 13"}},
    ]


def test_boost_floats_matching_model_to_top():
    out = identity_anchor_boost(_scored(), identity_model="ThinkPad X1")
    assert out[0]["candidate"]["sku"] == "B"  # matched item now ranks first
    assert out[0]["candidate"]["_identity_anchor"] == 1.0  # both tokens matched


def test_partial_token_match_gets_partial_boost():
    scored = [
        {"score": 1.0, "candidate": {"sku": "A", "name": "Acme Carbon Ultra"}},  # 1 of 2 tokens
        {"score": 0.99, "candidate": {"sku": "B", "name": "Plain Laptop"}},
    ]
    out = identity_anchor_boost(scored, identity_model="ThinkPad Carbon", boost=0.6)
    # A matched 1/2 tokens -> +0.3 -> 1.3 > 0.99
    assert out[0]["candidate"]["sku"] == "A"
    assert out[0]["candidate"]["_identity_anchor"] == 0.5


def test_no_model_is_noop_preserving_order():
    original = _scored()
    out = identity_anchor_boost(original, identity_model=None)
    assert [i["candidate"]["sku"] for i in out] == ["A", "B", "C"]


def test_no_match_leaves_scores_untouched():
    out = identity_anchor_boost(_scored(), identity_model="Macbook Air")
    assert all("_identity_anchor" not in i["candidate"] for i in out)
    assert out[0]["candidate"]["sku"] == "A"  # unchanged order (no re-sort triggered)
