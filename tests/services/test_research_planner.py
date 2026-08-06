from src.app.services.recommendation_core.research_planner import build_research_plan


def test_plan_is_vertical_neutral_and_does_not_choose_provider_ids():
    plan = build_research_plan(
        {
            "concepts": [{
                "text": "predictive maintenance simulation",
                "status": "unresolved",
                "material": True,
            }],
            "evidence_questions": [{
                "question_id": "performance_target",
                "question": "What model scale and time-to-result target is required?",
                "purpose": "resolve_performance_target",
                "material": True,
            }],
        },
        external_research_authorized=True,
    )

    payload = plan.model_dump()
    assert payload["subject_spans"] == ["predictive maintenance simulation"]
    assert {item["claim_type"] for item in payload["evidence_needs"]} == {
        "concept_identity", "recommended_requirements",
    }
    assert all(item["provider_capability"] == "official_requirements"
               for item in payload["evidence_needs"])
    assert "provider_id" not in str(payload)
    assert payload["external_research_authorized"] is True
    assert payload["interpretation_origin"] == "model"


def test_plan_bounds_questions_fanout_and_deadlines(monkeypatch):
    monkeypatch.setenv("RESEARCH_LANE_TIMEOUT_MS", "999999")
    monkeypatch.setenv("RESEARCH_TOTAL_TIMEOUT_MS", "1")
    plan = build_research_plan(
        {
            "concepts": [
                {"text": f"concept {index}", "material": True}
                for index in range(10)
            ],
            "evidence_questions": [
                {
                    "question_id": f"question {index}",
                    "question": f"Question number {index}?",
                    "purpose": "resolve_concept",
                    "material": True,
                }
                for index in range(10)
            ],
        },
        external_research_authorized=False,
    )

    assert len(plan.subject_spans) == 4
    assert len(plan.evidence_needs) == 8
    assert len(plan.material_slots) == 5
    assert plan.max_provider_fanout == 3
    assert plan.per_provider_timeout_ms == 30_000
    assert plan.total_timeout_ms == 100


def test_plan_uses_buyer_span_not_advisory_model_normalization():
    plan = build_research_plan(
        {
            "concepts": [{
                "text": "maintenance digital twin",
                "query_span": "maintenance digital twin",
                "normalized_label": "predictive maintenance simulation",
                "material": True,
            }],
        },
        external_research_authorized=True,
    )

    assert plan.subject_spans == ["maintenance digital twin"]
    assert all(item.subject_span == "maintenance digital twin" for item in plan.evidence_needs)


def test_plan_preserves_degraded_interpretation_origin():
    plan = build_research_plan(
        {
            "proposal_origin": "deterministic_fallback",
            "concepts": [{"text": "unfamiliar simulation", "material": True}],
        },
        external_research_authorized=False,
    )

    assert plan.interpretation_origin == "deterministic_fallback"


def test_buyer_free_text_is_a_research_candidate_not_an_authorized_requirement():
    plan = build_research_plan(
        {
            "concepts": [{"text": "maintenance digital twin", "material": True}],
            "evidence_questions": [{
                "question_id": "software_or_standard",
                "question": "Which workflow and execution target must be supported?",
                "purpose": "resolve_compatibility",
                "material": True,
            }],
        },
        external_research_authorized=True,
        clarification_answer={
            "question_id": "software_or_standard",
            "value": "Local engineering simulation with 3D visualisation.",
            "authority": "buyer_authored_candidate",
        },
    )

    slot = plan.material_slots[0]
    assert slot.answer_status == "candidate"
    assert slot.answer_candidate == "Local engineering simulation with 3D visualisation."
    assert "requirement" not in slot.model_dump()
