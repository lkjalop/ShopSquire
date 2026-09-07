from src.app.services.terminal_research_narration import terminal_research_narration


def test_held_claims_replace_false_no_evidence_narration() -> None:
    message = terminal_research_narration(
        research_outcome={
            "identity": {"title": "Agisoft Metashape"},
            "parsed_claim_count": 9,
            "held_claim_count": 9,
            "failure_code": "independent_policy_human_signoff_pending",
        },
        execution_evidence={},
        existing_message="No authoritative provider returned requirements.",
    )

    assert "parsed 9 cited requirement claims" in message
    assert "9 claims remain held" in message
    assert "no product is verified" in message
    assert "No authoritative provider" not in message


def test_router_truncation_is_narrated_before_catalog_fit() -> None:
    message = terminal_research_narration(
        research_outcome=None,
        execution_evidence={"failure_code": "router_output_truncated"},
        existing_message="No qualified in-catalog match under $6,000.",
    )

    assert "model response was truncated" in message
    assert "product fit were not concluded" in message
    assert "$6,000" not in message


def test_success_without_held_claims_preserves_existing_answer() -> None:
    assert terminal_research_narration(
        research_outcome={"held_claim_count": 0},
        execution_evidence={},
        existing_message="Four qualified products fit the accepted requirements.",
    ) == "Four qualified products fit the accepted requirements."


def test_accepted_and_held_claims_keep_success_and_append_review_boundary() -> None:
    message = terminal_research_narration(
        research_outcome={
            "identity": {"title": "Rockwell Emulate3D"},
            "parsed_claim_count": 5,
            "accepted_claim_count": 2,
            "held_claim_count": 3,
            "catalog_authority": "permitted",
        },
        execution_evidence={},
        existing_message="Two current catalog products satisfy the accepted requirements.",
    )

    assert message.startswith("Two current catalog products satisfy")
    assert "3 additional claims remain held" in message
    assert "accepted claims are not downgraded" in message


def test_successful_research_outcome_outranks_an_earlier_router_timeout() -> None:
    message = terminal_research_narration(
        research_outcome={
            "identity": {"title": "PRAGMATA"},
            "discovery_status": "completed",
            "accepted_claim_count": 2,
            "requirement_completeness": "complete",
            "catalog_authority": "permitted",
        },
        execution_evidence={"failure_code": "model_execution_timeout"},
        existing_message=(
            "Official research resolved PRAGMATA and qualified four products."
        ),
    )

    assert "Official research resolved PRAGMATA" in message
    assert "Research and product fit were not concluded" not in message


def test_router_failure_remains_visible_as_degraded_when_research_succeeds() -> None:
    message = terminal_research_narration(
        research_outcome={
            "identity": {"title": "PRAGMATA"},
            "discovery_status": "completed",
            "accepted_claim_count": 2,
            "requirement_completeness": "complete",
            "catalog_authority": "blocked",
        },
        execution_evidence={"failure_code": "router_output_truncated"},
        existing_message="Official requirements were established, but no SKU qualified.",
    )

    assert "interpretation was degraded" in message.lower()
    assert "Official requirements were established" in message
