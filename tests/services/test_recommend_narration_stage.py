"""recommend_narration_stage - QueryUnderstanding-backed narration inputs."""
from __future__ import annotations

from src.app.services.query_understanding import SAFE_IMAGE_LABEL, USER_TEXT, build_query_understanding
from src.app.services.recommend_narration_stage import (
    apply_narration_inputs_to_constraints,
    build_narration_evidence_block,
    build_narration_inputs,
)


def test_narration_inputs_prefer_query_understanding():
    qu = build_query_understanding(
        "show me something like this under 1800",
        {"budget_max": 1800, "_inferred_image_brand": "asus", "use_case": "gaming"},
    )
    ni = build_narration_inputs("ignored", {"budget_max": 999}, query_understanding=qu)
    assert ni.budget_max == 1800.0
    assert ni.brands == ["asus"]
    assert ni.use_case == "gaming"
    assert ni.provenance["budget_max"] == USER_TEXT
    assert ni.provenance["brands"] == SAFE_IMAGE_LABEL


def test_apply_narration_inputs_to_constraints_fills_missing_only():
    ni = build_narration_inputs("q", {"budget_max": 1200, "use_case": "student"})
    out = apply_narration_inputs_to_constraints({"budget_max": 900}, ni)
    assert out["budget_max"] == 900
    assert out["use_case"] == "student"
    assert "_query_understanding" in out


def test_evidence_block_is_compact_and_traceable():
    ni = build_narration_inputs(
        "q",
        {"budget_min": 1300, "budget_max": 1800, "brands": ["lenovo"], "use_case": "office_general"},
    )
    block = build_narration_evidence_block(ni)
    assert "Structured interpretation evidence" in block
    assert "$1,300-$1,800" in block
    assert "office general" in block
    assert "lenovo" in block
