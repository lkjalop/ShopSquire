import pytest
from pydantic import ValidationError

from src.app.services.recommendation_core.research_trigger_decision import (
    ResearchTriggerDecision,
    decide_research_trigger,
)


def _decide(**overrides):
    values = {
        "interpretation_confidence": 0.9,
        "workload_profile_coverage": "covered",
        "corpus_coverage": "sufficient",
        "cache_coverage": "miss",
        "material_unknowns": [],
        "expected_decision_impact": 0.8,
    }
    values.update(overrides)
    return decide_research_trigger(**values)


@pytest.mark.parametrize("workload", ["office", "base_game"])
def test_known_profile_with_fresh_corpus_uses_no_external_research(workload):
    result = _decide()

    assert workload  # documents two vertical-independent examples
    assert result.route == "local_evidence"
    assert result.external_research_eligible is False
    assert result.authorization_required is False
    assert result.should_execute_external_research is False
    assert result.authoritative is False


@pytest.mark.parametrize("profile", ["partial", "miss", "unknown"])
def test_material_out_of_profile_gap_is_eligible_but_cannot_run_without_consent(profile):
    result = _decide(
        interpretation_confidence=0.45,
        workload_profile_coverage=profile,
        corpus_coverage="miss",
        cache_coverage="miss",
        material_unknowns=["named workload requirements"],
        authorization_state="not_requested",
    )

    assert result.external_research_eligible is True
    assert result.authorization_required is True
    assert result.route == "request_authorization"
    assert result.should_execute_external_research is False


def test_corpus_miss_without_material_decision_impact_does_not_trigger_search():
    result = _decide(
        workload_profile_coverage="partial",
        corpus_coverage="miss",
        cache_coverage="miss",
        material_unknowns=["cosmetic preference"],
        expected_decision_impact=0.1,
    )

    assert result.external_research_eligible is False
    assert result.route == "provisional_catalog"
    assert "low_decision_impact" in result.reason_codes


def test_fresh_cache_prevents_external_search_despite_profile_and_corpus_misses():
    result = _decide(
        interpretation_confidence=0.3,
        workload_profile_coverage="miss",
        corpus_coverage="miss",
        cache_coverage="sufficient",
        material_unknowns=["scientific application requirements"],
    )

    assert result.route == "local_evidence"
    assert result.external_research_eligible is False
    assert result.should_execute_external_research is False
    assert "fresh_cache_sufficient" in result.reason_codes


def test_buyer_denial_routes_to_upload_or_manual_evidence_with_zero_execution():
    result = _decide(
        interpretation_confidence=0.4,
        workload_profile_coverage="miss",
        corpus_coverage="miss",
        cache_coverage="miss",
        material_unknowns=["named modlist requirements"],
        authorization_state="denied",
    )

    assert result.external_research_eligible is True
    assert result.route == "request_buyer_evidence"
    assert result.should_execute_external_research is False
    assert "buyer_declined_external_research" in result.reason_codes


def test_only_explicit_authorization_makes_an_eligible_external_route_executable():
    result = _decide(
        interpretation_confidence=0.4,
        workload_profile_coverage="miss",
        corpus_coverage="stale",
        cache_coverage="miss",
        material_unknowns=["workload minimum requirements"],
        authorization_state="granted",
    )

    assert result.external_research_eligible is True
    assert result.route == "external_research"
    assert result.should_execute_external_research is True
    assert "external_research_authorized" in result.reason_codes


def test_tenant_policy_can_prevent_execution_even_when_buyer_granted_consent():
    result = _decide(
        workload_profile_coverage="miss",
        corpus_coverage="miss",
        cache_coverage="miss",
        material_unknowns=["unknown scientific application"],
        authorization_state="granted",
        external_research_allowed=False,
    )

    assert result.external_research_eligible is True
    assert result.should_execute_external_research is False
    assert result.route == "request_buyer_evidence"
    assert "external_research_not_allowed" in result.reason_codes


def test_decision_contract_rejects_untyped_extension_fields():
    payload = _decide().model_dump()
    payload["provider_name"] = "must-not-be-selected-here"

    with pytest.raises(ValidationError):
        ResearchTriggerDecision.model_validate(payload)
