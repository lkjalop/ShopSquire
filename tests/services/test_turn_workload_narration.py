"""Narration preserves buyer context without qualifying an unresolved product."""
import pytest

from src.app.services.turn_transition import TurnCommit, TurnTransition, build_turn_read_model


@pytest.mark.parametrize("workloads", [
    ["Baldur's Gate 3", "Rockwell Emulate3D"],
    ["Fictional CAD A", "Fictional PLC B"],
])
def test_added_workloads_survive_generic_unresolved_narration(workloads):
    commit = TurnCommit(
        case_id="case", expected_revision=1, source_message_id="message",
        idempotency_key="operation", transition=TurnTransition.ADD_WORKLOAD,
        workloads=workloads, catalog_authority="blocked",
        research={"ambiguity_exploration": {"status": "provisional"}},
        requirements={"unresolved": [{"reason": "requirements_unresolved"}]},
        products=[{"sku": "PRIOR-UNQUALIFIED"}],
        assistant_message="The buyer added a workload.",
    )
    view = build_turn_read_model(commit, revision=2)
    assert all(label in view.assistant_message for label in workloads)
    assert "Requested workloads:" in view.assistant_message
    assert view.catalog_authority == "blocked"
    assert view.commerce_authority == "none"
    assert view.products == []
    assert view.research_outcome.accepted_claim_count == 0


def test_replaced_workload_does_not_echo_prior_buyer_query():
    commit = TurnCommit(
        case_id="case", expected_revision=1, source_message_id="message",
        idempotency_key="operation", transition=TurnTransition.REPLACE_WORKLOAD,
        workloads=["New workload"], objective="Replace PRIOR-REMOVED-WORKLOAD",
        catalog_authority="blocked", assistant_message="Requirements remain unresolved.",
    )
    view = build_turn_read_model(commit, revision=2)
    assert "PRIOR-REMOVED-WORKLOAD" not in view.assistant_message
    assert view.commerce_authority == "none"
