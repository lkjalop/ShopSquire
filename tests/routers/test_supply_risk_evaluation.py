from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.app.routers.supply_risk import (
    CausalEvaluationRequest,
    evaluate_causal_cohorts,
)


def test_causal_cohort_endpoint_is_bounded_and_simulation_only():
    result = evaluate_causal_cohorts(
        CausalEvaluationRequest(
            scenario_ids=["electronics_memory_allocation"],
            seeds=[7, 13],
            days=120,
            cohort_dimensions={
                "electronics_memory_allocation": {
                    "archetype": "launch_electronics",
                    "lifecycle_stage": "launch",
                },
            },
        ),
        role="merchant",
    )

    assert result["manifest"]["run_count"] == 2
    assert result["authority"] == "simulation_only"
    assert result["execution_allowed"] is False
    assert result["causal_claim_allowed"] is False
    assert result["can_increase_autonomy"] is False


def test_causal_cohort_endpoint_reports_unknown_scenario():
    with pytest.raises(HTTPException) as exc:
        evaluate_causal_cohorts(
            CausalEvaluationRequest(
                scenario_ids=["unknown-scenario"],
                seeds=[7],
                days=120,
            ),
            role="merchant",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "synthetic_supply_scenario_not_found"
