import pytest
from pydantic import ValidationError

from src.app.services.case_research_plan import build_case_research_plan
from src.app.services.shopping_case_truth_projection import ShoppingCaseTruthProjection


def _projection(**updates):
    plan = build_case_research_plan(
        "I need to simulate a PLC-controlled factory and cyberattacks against the OT network."
    )
    assert plan is not None
    payload = {
        "case_id": "sc-case-truth-1",
        "trace_id": "case-truth-1",
        "retained_purpose": plan.retained_purpose,
        "status": "provisional",
        "interpretations": plan.hypotheses,
        "next_question": {"id": "research_scope", "text": plan.next_question},
        "research_choices": ["research_approved_sources"],
        "execution": "local_exploration_completed",
        "evidence": "material_gaps",
        "decision": "exploration_allowed",
        "provider_accounting": {"external_calls": 0, "paid_calls": 0},
        "research_plan_id": plan.plan_id,
        "ambiguity_objects": plan.ambiguities,
        "research_obligations": plan.obligations,
        "source_candidate_ids": plan.source_candidate_ids,
        "timing_envelope": {
            "catalog_candidate_ms": 2.1,
            "research_plan_ms": 1.2,
            "case_persistence_ms": 3.0,
            "shelf_projection_ms": 4.0,
            "response_projection_ms": 0.2,
            "total_ms": 10.5,
            "deadline_status": "within_deadline",
            "external_calls": 0,
        },
    }
    payload.update(updates)
    return payload


def test_projection_preserves_one_identity_and_hypothesis_set_for_panel_and_trace():
    projection = ShoppingCaseTruthProjection.model_validate(_projection())
    rendered = projection.model_dump(mode="json")

    assert rendered["case_id"] == "sc-case-truth-1"
    assert rendered["trace_id"] == "case-truth-1"
    assert rendered["retained_purpose"].startswith("I need to simulate")
    assert 1 <= len(rendered["interpretations"]) <= 3
    assert rendered["timing_envelope"]["total_ms"] == 10.5


def test_projection_rejects_panel_trace_identity_drift():
    with pytest.raises(ValidationError, match="case_trace_identity_mismatch"):
        ShoppingCaseTruthProjection.model_validate(_projection(trace_id="some-other-trace"))


def test_projection_rejects_hypothesis_drift():
    payload = _projection()
    payload["ambiguity_objects"][0].hypothesis_ids = ["not-in-panel"]
    with pytest.raises(ValidationError, match="ambiguity_hypothesis_mismatch"):
        ShoppingCaseTruthProjection.model_validate(payload)
