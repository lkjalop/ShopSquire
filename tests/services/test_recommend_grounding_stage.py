"""Grounding-ladder stage (extracted from suggest()). Verifies the no-op guards (no image / disabled /
absent id_result), the brand-drop gate, the grounded annotations, and never-raises — with the
grounding_ladder service injected via monkeypatch."""
from __future__ import annotations

from types import SimpleNamespace

import src.app.services.grounding_ladder as gl
from src.app.services.recommend_grounding_stage import run_grounding_ladder


def _grounded(brand=None, confidence=0.9, tier="catalog", label="high", residual=None):
    return SimpleNamespace(brand=brand, confidence=confidence, tier_name=tier, confidence_label=label,
                           residual_question=residual,
                           to_dict=lambda: {"brand": brand, "tier": tier, "confidence": confidence})


def _patch(monkeypatch, grounded):
    monkeypatch.setattr(gl, "resolve_grounded_identity", lambda **kw: grounded)
    monkeypatch.setattr(gl, "get_catalog_brands", lambda db: ["dell", "hp"])


def _call(**over):
    base = dict(query="laptop", constraints={}, incoming_image_payload=True, id_source="vision_image",
                id_result={"brand": "asus"}, image_blob=None, image_identity_confidence=0.5,
                strict_image_brand_hint="asus", db=None, trace_id="T", trace_fn=lambda *a, **k: None,
                enabled=True)
    base.update(over)
    return run_grounding_ladder(**base)


def test_no_image_payload_is_noop():
    conf, hint = _call(incoming_image_payload=False)
    assert conf == 0.5 and hint == "asus"


def test_disabled_is_noop():
    conf, hint = _call(enabled=False)
    assert conf == 0.5 and hint == "asus"


def test_absent_id_result_skips_like_inline_nameerror():
    conf, hint = _call(id_result=None)
    assert conf == 0.5 and hint == "asus"  # reproduces the inline NameError→skip exactly


def test_ungrounded_brand_is_dropped(monkeypatch):
    _patch(monkeypatch, _grounded(brand=None, confidence=0.4, tier="generic", label="low"))
    calls = []
    constraints = {"brand": "asus", "brands": ["asus"], "_request_brand_hint": "asus"}
    conf, hint = _call(constraints=constraints, trace_fn=lambda *a, **k: calls.append(a))
    assert "brand" not in constraints and "brands" not in constraints  # ungrounded brand dropped
    assert hint is None and conf == 0.4
    assert any("grounding_ladder_brand_dropped" in a for a in calls)


def test_grounded_brand_annotates_without_drop(monkeypatch):
    _patch(monkeypatch, _grounded(brand="dell", confidence=0.95, tier="catalog", label="high",
                                  residual="which model?"))
    constraints = {"brand": "dell"}
    conf, hint = _call(constraints=constraints, id_result={"brand": "dell"})
    assert constraints["brand"] == "dell"  # grounded → kept
    assert conf == 0.95 and constraints["_grounded_tier"] == "catalog"
    assert constraints["_identity_residual_question"] == "which model?"


def test_resolver_failure_is_recorded_and_continues(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("vlm down")
    monkeypatch.setattr(gl, "resolve_grounded_identity", _boom)
    monkeypatch.setattr(gl, "get_catalog_brands", lambda db: [])
    calls = []
    conf, hint = _call(trace_fn=lambda *a, **k: calls.append(a))
    assert conf == 0.5 and hint == "asus"  # unchanged inputs returned
    assert any("stage_partial_failure" in a for a in calls)
