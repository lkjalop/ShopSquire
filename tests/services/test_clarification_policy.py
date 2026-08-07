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
                "resolves_unknown_ids": ["performance"],
                "decision_impacts": ["capability", "affordable_quantity"],
            },
            {
                "question_id": "deployment",
                "question": "Must it run locally?",
                "purpose": "resolve_deployment",
                "resolves_unknown_ids": ["deployment"],
                "decision_impacts": ["architecture", "product_set"],
            },
        ],
        material_unknowns=[
            {"unknown_id": "performance", "resolution_source": "buyer"},
            {"unknown_id": "deployment", "resolution_source": "buyer"},
        ],
    )

    assert question["id"] == "deployment"
    assert question["text"] == "Must it run locally?"
    assert question["options"] == []
    assert question["selection_policy"] == "expected_decision_impact"
    assert question["decision_impacts"] == ["architecture", "product_set"]


def test_research_owned_question_is_not_asked_of_buyer():
    question = select_semantic_clarification(
        research_status="not_configured",
        proposed_questions=[{
            "question_id": "hardware_floor",
            "question": "What CPU, RAM, and GPU does this workload need?",
            "purpose": "resolve_compatibility",
            "resolves_unknown_ids": ["official-requirements"],
            "decision_impacts": ["capability", "product_set"],
        }],
        material_unknowns=[{
            "unknown_id": "official-requirements",
            "resolution_source": "research",
        }],
    )

    assert question["id"] == "authoritative_evidence_required"
    assert "cpu" not in question["text"].lower()
    assert question["selection_policy"] == "authority_before_catalog"


def test_buyer_owned_question_wins_over_research_owned_question():
    question = select_semantic_clarification(
        research_status="insufficient",
        proposed_questions=[
            {
                "question_id": "hardware_floor",
                "question": "What hardware does it need?",
                "purpose": "resolve_compatibility",
                "resolves_unknown_ids": ["official-requirements"],
                "decision_impacts": ["capability"],
            },
            {
                "question_id": "execution_location",
                "question": "Will it run locally, remotely, or in a hybrid setup?",
                "purpose": "resolve_compatibility",
                "resolves_unknown_ids": ["execution-location"],
                "decision_impacts": ["architecture", "product_set"],
            },
        ],
        material_unknowns=[
            {"unknown_id": "official-requirements", "resolution_source": "research"},
            {"unknown_id": "execution-location", "resolution_source": "buyer"},
        ],
    )

    assert question["id"] == "execution_location"
    assert question["missing_slots"] == ["execution-location"]


def test_missing_model_question_uses_vertical_neutral_fallback():
    question = select_semantic_clarification(
        research_status="unavailable",
        proposed_questions=[],
    )

    assert question["id"] == "concept_resolution"
    assert "standard" in question["text"].lower()
    assert "software" not in question["text"].lower()


def test_question_that_distinguishes_more_open_hypotheses_wins():
    question = select_semantic_clarification(
        research_status="insufficient",
        proposed_questions=[
            {
                "question_id": "performance_target",
                "question": "What result time is acceptable?",
                "purpose": "resolve_performance_target",
                "resolves_unknown_ids": ["performance"],
                "decision_impacts": ["capability", "affordable_quantity"],
            },
            {
                "question_id": "execution_location",
                "question": "Will it run locally, remotely, or in a hybrid setup?",
                "purpose": "resolve_compatibility",
                "resolves_unknown_ids": ["deployment"],
                "decision_impacts": ["product_set"],
            },
        ],
        material_unknowns=[
            {"unknown_id": "performance", "resolution_source": "buyer"},
            {"unknown_id": "deployment", "resolution_source": "buyer"},
        ],
        workload_hypotheses=[
            {
                "hypothesis_id": "local",
                "evidence_coverage": "partial",
                "discriminating_unknown_ids": ["deployment"],
            },
            {
                "hypothesis_id": "remote",
                "evidence_coverage": "unresolved",
                "discriminating_unknown_ids": ["deployment"],
            },
        ],
    )

    assert question["id"] == "execution_location"
    assert question["selection_policy"] == "bounded_information_gain"
    assert question["hypotheses_discriminated"] == 2
