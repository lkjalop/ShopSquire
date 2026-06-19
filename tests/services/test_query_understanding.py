"""QueryUnderstanding contract (the unified interpretation; #4 phase 1).

Locks: field assembly from parsed constraints, per-field provenance, missing-field detection, and
the cold-start assumption ledger (proceed with an OVERRIDABLE default, not a silent guess).
Vertical-agnostic: no brand/spec flavour in the object.
"""
from __future__ import annotations

from src.app.services.query_understanding import (
    DEFAULT,
    LLM_INFERRED,
    OFF_TOPIC,
    ON_TOPIC,
    SAFE_IMAGE_LABEL,
    USER_TEXT,
    build_query_understanding,
)


def test_assembles_typed_fields_from_constraints():
    qu = build_query_understanding(
        "gaming laptop under 1800",
        {"budget_max": 1800, "brands": ["asus"], "use_case": "gaming"},
    )
    assert qu.budget_max == 1800.0
    assert qu.brands == ["asus"]
    assert qu.use_case == "gaming"
    assert qu.provenance["budget_max"] == USER_TEXT
    assert qu.provenance["use_case"] == USER_TEXT


def test_provenance_marks_image_derived_and_inferred():
    qu = build_query_understanding(
        "show me something like this",
        {"_inferred_image_brand": "msi", "budget_max": 1500},
    )
    assert qu.brands == ["msi"]
    assert qu.provenance["brands"] == SAFE_IMAGE_LABEL  # came from an image, not typed


def test_use_case_from_query_plan_is_inferred():
    class _Plan:
        intent = "content_creation"
    qu = build_query_understanding("editing videos", {}, query_plan=_Plan())
    assert qu.use_case == "content_creation"
    assert qu.provenance["use_case"] == LLM_INFERRED  # inferred, not typed


def test_missing_fields_detected_for_vague_query():
    qu = build_query_understanding("show me laptops", {})
    # no budget, no use_case, no brands → all flagged missing (NQE should ask / assume)
    assert "budget_max" in qu.missing
    assert "use_case" in qu.missing
    assert "brands" in qu.missing


def test_assumption_ledger_is_overridable_and_clears_missing():
    qu = build_query_understanding("show me laptops", {})
    assert "budget_max" in qu.missing
    qu2 = qu.with_assumption("budget_max", 1500, basis="median catalog price")
    assert qu2.assumptions[0] == {"field": "budget_max", "value": 1500, "basis": "median catalog price", "overridable": True}
    assert qu2.provenance["budget_max"] == DEFAULT
    assert "budget_max" not in qu2.missing  # an explicit assumption resolves the gap (visibly)
    # frozen: original unchanged
    assert "budget_max" in qu.missing


def test_image_relation_normalised():
    assert build_query_understanding("q", {}).image_relation == "none"
    assert build_query_understanding("q", {"_image_relation": "on_topic"}).image_relation == ON_TOPIC
    assert build_query_understanding("q", {"_image_relation": "garbage"}).image_relation == "none"
    assert build_query_understanding("q", {}, image_relation=OFF_TOPIC).image_relation == OFF_TOPIC


def test_to_dict_is_trace_friendly():
    qu = build_query_understanding("gaming laptop under 1800", {"budget_max": 1800, "use_case": "gaming"})
    d = qu.to_dict()
    assert d["budget_max"] == 1800.0 and d["use_case"] == "gaming"
    assert "provenance" in d and "missing" in d and "assumptions" in d
