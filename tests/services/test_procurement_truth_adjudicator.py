from datetime import datetime, timezone

from src.app.services.procurement_truth_adjudicator import (
    adjudicate_exploration_truth,
    adjudicate_procurement_truth,
)


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def test_unresearched_case_is_provisional_and_has_no_commerce_authority() -> None:
    truth = adjudicate_procurement_truth(
        state_data={"case_id": "case-1", "revision": 2}, evaluated_at=NOW,
    )

    assert truth.research_execution == "NOT_ATTEMPTED"
    assert truth.evidence_status == "NONE"
    assert truth.freshness == "UNKNOWN"
    assert truth.decision_status == "PROVISIONAL"
    assert truth.commerce_authority == "NONE"


def test_qualified_case_requires_current_evidence_before_action_authority() -> None:
    state = {
        "case_id": "case-2",
        "revision": 5,
        "research": {
            "complete": True,
            "claims": [{"status": "accepted"}],
            "provider_accounting": {"external_calls": 2, "paid_calls": 0},
        },
        "fulfilment": {"commercial_decision": {"status": "QUALIFIED_NOW"}},
        "authority": {"action_allowed": True},
    }
    stale = adjudicate_procurement_truth(
        state_data=state,
        evidence_watermarks=[{"state": "stale"}],
        evaluated_at=NOW,
    )
    current = adjudicate_procurement_truth(
        state_data=state,
        evidence_watermarks=[{"state": "current"}],
        evaluated_at=NOW,
    )

    assert stale.decision_status == "QUALIFIED"
    assert stale.commerce_authority == "NONE"
    assert current.commerce_authority == "ACTION_ALLOWED"
    assert current.external_calls == 2


def test_side_effect_without_authority_fails_the_visible_decision() -> None:
    truth = adjudicate_procurement_truth(
        state_data={"case_id": "case-3", "revision": 1},
        evaluated_at=NOW,
        cart_mutations=1,
    )

    assert truth.decision_status == "FAILED"
    assert any("Invariant violation" in reason for reason in truth.reasons)


def test_exploration_projection_uses_same_vocabulary() -> None:
    truth = adjudicate_exploration_truth({
        "case_id": "sc-case-4",
        "execution": "live_discovery_completed",
        "evidence": "publisher_candidates_only",
        "decision": "provisional_exploration_only",
        "provider_accounting": {"external_calls": 1, "paid_calls": 0},
        "evaluated_at": NOW.isoformat(),
    })

    assert truth.research_execution == "DISCOVERY_ONLY"
    assert truth.evidence_status == "CANDIDATE_ONLY"
    assert truth.decision_status == "PROVISIONAL"
    assert truth.commerce_authority == "NONE"
