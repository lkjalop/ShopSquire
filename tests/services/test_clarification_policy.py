from src.app.services.recommendation_core.clarification_policy import (
    select_semantic_clarification,
)


def test_consent_precedes_model_proposed_domain_question():
    question = select_semantic_clarification(
        research_status="consent_required",
        proposed_questions=[{
            "question_id": "software",
            "question": "Which software and version?",
            "purpose": "resolve_compatibility",
        }],
    )

    assert question["id"] == "external_research_consent"
    assert question["missing_slots"] == ["external_research_consent"]
    assert "software" not in question["text"].lower()


def test_insufficient_research_asks_one_model_proposed_material_question():
    question = select_semantic_clarification(
        research_status="insufficient",
        proposed_questions=[
            {
                "question_id": "performance_target",
                "question": "What scale and time-to-result target is required?",
                "purpose": "resolve_performance_target",
            },
            {
                "question_id": "deployment",
                "question": "Must it run locally?",
                "purpose": "resolve_deployment",
            },
        ],
    )

    assert question["id"] == "performance_target"
    assert question["text"] == "What scale and time-to-result target is required?"
    assert question["options"] == []


def test_missing_model_question_uses_vertical_neutral_fallback():
    question = select_semantic_clarification(
        research_status="unavailable",
        proposed_questions=[],
    )

    assert question["id"] == "concept_resolution"
    assert "standard" in question["text"].lower()
    assert "software" not in question["text"].lower()
