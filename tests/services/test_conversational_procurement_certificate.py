from datetime import datetime, timezone

from src.app.services.conversational_procurement_certificate import (
    TURN_ONE,
    TURN_TWO,
    build_conversational_procurement_certificate,
)


def test_exact_two_turn_spatiotemporal_certificate_passes_every_invariant() -> None:
    artifact = build_conversational_procurement_certificate(
        turn_one=TURN_ONE,
        turn_two=TURN_TWO,
        interpretation_instant=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )

    assert artifact["passed"] is True
    assert all(artifact["invariants"].values())
    state = artifact["amended_state"]
    assert state["revision"] == 2
    assert state["requested_quantity"] == 60
    assert [(row["location_ref"], row["quantity"]) for row in state["destinations"]] == [
        ("Sydney", 45), ("Perth", 15),
    ]
    assert state["workloads"] == ["Unreal Engine", "large CAD models", "simulation"]
    assert state["budget"]["amount_minor"] == 22_000_000
    assert state["temporal"]["resolution_status"] == "resolved"
    assert artifact["allocation"]["allocated_units"] >= 30
    assert artifact["allocation"]["shortfall_units"] == 19
    assert artifact["supplier_shortfall"]["status"] == "proposal_only"
    assert artifact["canonical_truth"]["commerce_authority"] == "NONE"
    assert len(artifact["artifact_sha256"]) == 64


def test_certificate_does_not_mislabel_fixture_as_live_network() -> None:
    artifact = build_conversational_procurement_certificate()

    assert artifact["fixture"] is True
    assert artifact["live_network_certified"] is False
    assert artifact["provider_accounting"] == {
        "external_calls_before_authorization": 0,
        "external_calls_after_authorization": 0,
        "paid_calls": 0,
        "reason": "enrolled_evidence_fixture_no_network_dispatch",
    }
