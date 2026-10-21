from src.app.services.terminal_research_narration import terminal_research_narration
import pytest


@pytest.mark.parametrize('state', [
    {'requirement_completeness': 'partial'},
    {'catalog_authority': 'blocked'},
    {'requirement_completeness': 'complete', 'catalog_authority': 'permitted'},
])
def test_other_case_research_cannot_rewrite_current_product_answer(state):
    original = 'We do not stock the requested enclosure.'
    assert terminal_research_narration(
        research_outcome={'case_id': 'old', 'identity': {'title': 'Old workload'}, **state},
        current_exploration={'case_id': 'current'}, subject_role='ADJACENT_PRODUCT',
        execution_evidence={}, existing_message=original, product_shelves={'shelves': []},
    ) == original


def test_current_partial_host_obligation_still_prevents_purchase_fit_claim():
    message = terminal_research_narration(
        research_outcome={'case_id': 'current', 'identity': {'title': 'Current workload'},
                          'requirement_completeness': 'partial'},
        current_exploration={'case_id': 'current'}, subject_role='PROCURE_SUBJECT',
        execution_evidence={}, existing_message='This fully qualifies.',
    )
    assert 'coverage remains partial' in message
    assert 'fully qualifies' not in message


def test_current_context_only_workload_blocks_generic_purchase_fit():
    message = terminal_research_narration(
        research_outcome={"case_id": "current", "accepted_claim_count": 0},
        current_exploration={"case_id": "current", "status": "context_only",
                             "evidence": "authoritative_context_only"},
        subject_role="PROCURE_SUBJECT", execution_evidence={},
        existing_message="Yes - $2,000 is ample for general. Strong fits start at $629.",
    )
    assert "cannot confirm" in message
    assert "context" in message
    assert "ample" not in message
    assert "Strong fits" not in message


def test_historical_context_cannot_replace_unrelated_purchase_answer():
    original = "We do not stock the requested storage enclosure."
    message = terminal_research_narration(
        research_outcome={"case_id": "current"},
        current_exploration={"case_id": "old", "status": "context_only"},
        subject_role="PROCURE_SUBJECT", execution_evidence={}, existing_message=original,
    )
    assert message == original


def test_resolved_research_preserves_qualified_purchase_answer():
    original = "One configuration meets the accepted requirements."
    assert terminal_research_narration(
        research_outcome={"case_id": "current", "accepted_claim_count": 6},
        current_exploration={"case_id": "current", "status": "requirements_resolved"},
        subject_role="PROCURE_SUBJECT", execution_evidence={}, existing_message=original,
    ) == original


def test_partial_evidence_keeps_the_canonical_subject():
    message = terminal_research_narration(
        research_outcome={
            "failure_code": "requirements_incomplete", "accepted_claim_count": 2,
            "identity": {"title": "PRAGMATA"},
        },
        execution_evidence={}, existing_message="Fully qualified",
    )
    assert "PRAGMATA" in message
    assert "partial" in message
    assert "Fully qualified" not in message


def test_missing_research_plan_cannot_leave_a_budget_success_sentence():
    message = terminal_research_narration(
        research_outcome={"catalog_authority": "blocked", "failure_code": "case_research_plan_not_found"},
        execution_evidence={}, existing_message="Yes, the best fit starts at $1,919.",
    )
    assert "$1,919" not in message
    assert "could not complete" in message


def test_partial_evidence_replaces_an_earlier_budget_fit_claim():
    message = terminal_research_narration(
        research_outcome={"failure_code": "requirements_incomplete", "accepted_claim_count": 2},
        execution_evidence={}, existing_message="Yes, this laptop fully qualifies.",
    )
    assert "2 requirement claims" in message
    assert "partial" in message
    assert "fully qualifies" not in message


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
    assert "Research has not established authority" in message


def test_unresearched_provisional_turn_cannot_claim_fit():
    result = terminal_research_narration(
        research_outcome={"catalog_authority":"unknown", "discovery_status":"not_attempted"},
        current_exploration={"status":"provisional"}, execution_evidence={},
        existing_message="These all handle creative workloads.")
    assert "remain unresolved" in result
    assert "These all handle" not in result


def test_compiled_selected_scope_outranks_model_outage_without_inventing_a_discovered_identity():
    message = terminal_research_narration(
        research_outcome={'accepted_claim_count':1, 'requirement_completeness':'complete',
            'catalog_authority':'permitted', 'simulation_only':True, 'identity':None},
        execution_evidence={'failure_code':'model_execution_unavailable'},
        existing_message='No product fit was concluded.',
        product_shelves={'shelves':[{'initial':[{'identity_key':'fixture-config','fit_status':'qualified'}]}]})
    assert 'fictional scope' in message
    assert '1 exact catalog configuration' in message
    assert 'No product fit was concluded' not in message
