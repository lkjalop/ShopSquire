from src.app.services.recommendation_core.research_routing import (
    assess_research_trigger_shadow,
)


def test_ordinary_high_confidence_catalog_search_stays_catalog_first():
    result = assess_research_trigger_shadow(
        {}, catalog_coverage=0.98, retrieval_confidence=0.95,
    )

    assert result.state == "catalog_sufficient"
    assert result.recommendation == "catalog_first"
    assert result.authoritative is False


def test_unfamiliar_material_workload_is_a_research_candidate():
    result = assess_research_trigger_shadow({
        "concepts": [{"query_span": "maintenance simulation", "material": True}],
        "material_unknowns": [
            {"unknown_id": "execution", "resolution_source": "buyer"},
            {"unknown_id": "requirements", "resolution_source": "research"},
        ],
    })

    assert result.state == "unresolved_workload"
    assert result.recommendation == "research_candidate"
    assert result.calibration_status == "uncalibrated_shadow"


def test_competing_hypotheses_are_distinct_from_missing_requirements():
    result = assess_research_trigger_shadow({
        "concepts": [{"query_span": "digital model", "material": True}],
        "material_unknowns": [{"unknown_id": "deployment", "resolution_source": "buyer"}],
        "workload_hypotheses": [
            {"hypothesis_id": "local", "evidence_coverage": "partial"},
            {"hypothesis_id": "remote", "evidence_coverage": "unresolved"},
        ],
    })

    assert result.state == "ambiguous_intent"
    assert "competing_hypotheses" in result.reasons


def test_commercial_materiality_can_raise_observation_but_not_authority():
    low = assess_research_trigger_shadow({}, commercial_materiality=0.0)
    high = assess_research_trigger_shadow({}, commercial_materiality=1.0)

    assert high.score > low.score
    assert high.authoritative is False
    assert high.recommendation == "catalog_first"
