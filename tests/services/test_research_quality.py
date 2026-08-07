import pytest
from pydantic import ValidationError

from src.app.services.recommendation_core.research_quality import (
    SealedResearchReportReview,
    binary_trigger_metrics,
    clarification_metrics,
    grounding_metrics,
    hypothesis_metrics,
    relation_relevance,
)


def test_hypothesis_metrics_separate_recall_from_calibration():
    result = hypothesis_metrics(["local", "hybrid"], {"local": 0.8, "remote": 0.7})
    assert result["recall"] == 0.5
    assert result["brier"] > 0


def test_trigger_and_clarification_metrics_do_not_share_an_aggregate_pass_rate():
    trigger = binary_trigger_metrics([
        {"expected_research": True, "observed_research": True},
        {"expected_research": False, "observed_research": True},
    ])
    clarification = clarification_metrics([
        {
            "asked": True,
            "reduced_material_uncertainty": False,
            "best_available_utility": 0.8,
            "selected_utility": 0.5,
        },
    ])
    assert trigger == {"precision": 0.5, "recall": 1.0}
    assert clarification == {"ineffective_question_rate": 1.0, "mean_regret": 0.3}


def test_grounding_requires_complete_provenance_for_presented_claims():
    result = grounding_metrics([
        {
            "presented": True, "status": "accepted", "source_id": "vendor",
            "source_record_id": "doc:1", "observed_at": "2026-08-07T00:00:00Z",
        },
        {"presented": True, "status": "accepted", "source_id": "vendor"},
    ])
    assert result == {"unsupported_claim_rate": 0.5, "provenance_coverage": 0.5}


def test_relation_metrics_distinguish_substitutes_and_complements():
    result = relation_relevance([
        {"relation": "exact"}, {"relation": "substitute"},
        {"relation": "complement"}, {"relation": "irrelevant"},
    ])
    assert result["useful_precision"] == 0.75
    assert result["exact_precision"] == 0.25


def test_report_quality_requires_an_independent_human_seal():
    with pytest.raises(ValidationError):
        SealedResearchReportReview(
            case_id="case-1", reviewer_id="model", reviewer_type="model",
            accuracy=5, coverage=5, informativeness=5, clarity=5,
            consistency=5, novelty=5, sealed_at="2026-08-07T00:00:00Z",
        )
