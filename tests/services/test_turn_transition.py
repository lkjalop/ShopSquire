from src.app.services.turn_transition import (
    TurnCommit,
    TurnTransition,
    build_turn_read_model,
    derive_turn_transition,
)


def test_transition_priority_is_explicit_and_bounded():
    assert derive_turn_transition(active_case=True, new_category=True) == TurnTransition.NEW_CATEGORY
    assert derive_turn_transition(
        active_case=True, additive_workload=True, subject_action="continue",
    ) == TurnTransition.ADD_WORKLOAD
    assert derive_turn_transition(
        active_case=True, pending_clarification={"question_id": "locality"},
        clarification_relation="answer",
    ) == TurnTransition.ANSWER_PENDING
    assert derive_turn_transition(
        active_case=True, commercial_amendment=True,
    ) == TurnTransition.COMMERCIAL_AMENDMENT
    assert derive_turn_transition(
        active_case=True, workload_refinement=True,
    ) == TurnTransition.REFINE_WORKLOAD
    assert derive_turn_transition(active_case=False) == TurnTransition.UNRESOLVED


def test_revision_bound_read_model_is_a_projection_of_one_commit():
    commit = TurnCommit(
        case_id="sc-demo",
        expected_revision=4,
        source_message_id="msg-1",
        idempotency_key="idem-1",
        transition=TurnTransition.ADD_WORKLOAD,
        objective="Gaming plus Emulate3D",
        workloads=["Baldur's Gate 3", "Rockwell Emulate3D"],
        preserved_fields=["budget"],
        pending_clarification={"action": "consume", "prior_question_id": "locality"},
        external_research_authorized=True,
        catalog_authority="blocked",
        assistant_message="I retained the budget and added Emulate3D.",
    )
    projection = build_turn_read_model(commit, revision=5)
    assert projection.case_revision == 5
    assert projection.transition == TurnTransition.ADD_WORKLOAD
    assert projection.pending_clarification.action == "consume"
    assert projection.catalog_authority == "blocked"
    assert projection.commerce_authority == "none"
