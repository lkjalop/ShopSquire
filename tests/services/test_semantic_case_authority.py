from src.app.services.recommendation_core.turn_router import (
    persisted_semantic_blocker_decision,
)


BLOCKED = {
    "outcome": "clarify",
    "catalog_authority": "blocked",
    "desired_outcome": (
        "recommend a laptop for simulating a digital twin for maintenance of mechanical machines"
    ),
    "concepts": [
        {
            "text": "simulating a digital twin for maintenance of mechanical machines",
            "status": "unresolved",
            "material": True,
            "interpretations": [],
        }
    ],
    "questions": [
        {
            "question_id": "software_or_standard",
            "question": "Which exact software and version must be supported?",
            "purpose": "resolve_compatibility",
            "material": True,
        }
    ],
    "state_prevented": ["catalog_recommendation", "commerce_execution"],
}


def test_choose_cannot_bypass_a_persisted_material_blocker() -> None:
    decision = persisted_semantic_blocker_decision(
        "Choose a laptop.",
        {"semantic_resolution": BLOCKED},
    )

    assert decision is not None
    assert decision.source == "deterministic_persisted_semantic_blocker"
    assert decision.semantic_proposal["validation"] == "valid"
    assert decision.semantic_proposal["evidence_questions"][0]["question_id"] == "software_or_standard"
    assert decision.node_handle is None
    assert decision.exact_product_sku is None


def test_confirm_cannot_create_commerce_state_while_evidence_is_blocked() -> None:
    decision = persisted_semantic_blocker_decision(
        "Choose the first one and confirm the purchase order.",
        {"semantic_resolution": BLOCKED},
    )

    assert decision is not None
    assert decision.lane == "SEARCH"
    assert "commerce_execution" in decision.semantic_proposal["state_prevented"]


def test_substantive_answer_is_allowed_to_reenter_semantic_resolution() -> None:
    decision = persisted_semantic_blocker_decision(
        "Siemens NX 2412, running locally, medium assemblies under five minutes.",
        {"semantic_resolution": BLOCKED},
    )

    assert decision is None
