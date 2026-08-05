from src.app.services.semantic_research_fixture import resolve_fixture
from types import SimpleNamespace

from src.app.services.evidence_orchestrator import gather_evidence


def test_deterministic_fixture_is_explicitly_simulated_and_not_source_approved(monkeypatch) -> None:
    monkeypatch.setenv("SEMANTIC_RESEARCH_FIXTURES_ENABLED", "1")
    monkeypatch.setenv("SEMANTIC_RESEARCH_FIXTURE_ID", "siemens_digital_twin_demo")

    result = resolve_fixture("digital twin")

    assert result is not None
    assert result["provider_id"] == "deterministic_fixture:siemens_digital_twin_demo"
    assert result["simulation_only"] is True
    assert result["authority"] == "simulation_candidate_only"
    assert result["normalized_evidence"][0]["source_policy"]["review_status"] == "pending_independent_review"


def test_fixture_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SEMANTIC_RESEARCH_FIXTURES_ENABLED", raising=False)
    monkeypatch.setenv("SEMANTIC_RESEARCH_FIXTURE_ID", "siemens_digital_twin_demo")

    assert resolve_fixture("digital twin") is None


def test_local_fixture_exercises_provenance_without_external_egress_consent(monkeypatch) -> None:
    monkeypatch.setenv("SEMANTIC_RESEARCH_FIXTURES_ENABLED", "1")
    monkeypatch.setenv("SEMANTIC_RESEARCH_FIXTURE_ID", "siemens_digital_twin_demo")
    plan = SimpleNamespace(
        intent="product_search",
        needs_market_evidence=False,
        quantity=30,
        availability_horizon_days=None,
        needs_concept_resolution=True,
        external_research_authorized=False,
        semantic_proposal={
            "concepts": [{"text": "digital twin", "material": True}],
        },
    )

    bundle = gather_evidence(plan, query="laptops for a digital twin", web_consent=False)
    data = bundle["legs"]["concept_resolution"]["data"]

    assert data["status"] == "simulation_fixture"
    assert data["provider_id"].startswith("deterministic_fixture:")
    assert data["authority"] == "simulation_candidate_only"


def test_qualified_fixture_requires_explicit_research_consent(monkeypatch) -> None:
    monkeypatch.setenv("SEMANTIC_RESEARCH_FIXTURES_ENABLED", "1")
    monkeypatch.setenv(
        "SEMANTIC_RESEARCH_FIXTURE_ID",
        "siemens_digital_twin_qualified_contract",
    )

    assert resolve_fixture("digital twin simulation", authorized=False) is None
    result = resolve_fixture("digital twin simulation", authorized=True)

    assert result is not None
    assert result["simulation_only"] is True
    assert result["authority"] == "simulation_contract_only"
    assert result["catalog_qualifications"] == [
        {
            "sku": "RGAM-0007",
            "alignment_status": "qualified",
            "evidence_refs": ["fixture:digital-twin-profile-1:2026-08-05"],
        }
    ]
