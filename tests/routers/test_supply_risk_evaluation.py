from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.app.routers.supply_risk import (
    CausalEvaluationRequest,
    DisruptionObservationRequest,
    DisruptionProjectionRequest,
    create_disruption_observation,
    create_disruption_projection,
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


class _Db:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_disruption_endpoint_binds_tenant_and_commits_advisory_observation(monkeypatch):
    import src.app.routers.supply_risk as module

    captured = {}
    monkeypatch.setattr(module, "current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(
        module, "record_disruption_observation",
        lambda _db, **kwargs: captured.update(kwargs) or {
            "id": "obs-1", "authority": "advisory_only", "execution_allowed": False,
        },
    )
    db = _Db()
    result = create_disruption_observation(
        DisruptionObservationRequest(
            disruption_type="lane_weather_risk", affected_node_ids=["node-1"],
            geography="AU-SYD", effective_from="2026-08-03T00:00:00Z",
            observed_at="2026-08-03T00:01:00Z", retrieved_at="2026-08-03T00:02:00Z",
            fresh_until="2026-08-03T04:00:00Z", source_id="official-weather",
            source_record_id="alert-1", source_revision="r1", source_licence="public-domain",
            evidence_ref="sha256:evidence", severity="high", probability_range=(0.7, 0.9),
            delay_range_days=(1, 3), cost_impact_range_minor=(100, 500), currency="AUD",
            claim_status="supported",
        ),
        role="owner", db=db,
    )
    assert captured["tenant_id"] == "tenant-a"
    assert result["execution_allowed"] is False
    assert db.commits == 1


def test_disruption_projection_endpoint_remains_proposal_only(monkeypatch):
    import src.app.routers.supply_risk as module

    captured = {}
    monkeypatch.setattr(module, "current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(
        module, "project_disruption_impact",
        lambda _db, **kwargs: captured.update(kwargs) or {
            "status": "bounded_recalculation_proposed", "authority": "proposal_only",
            "execution_allowed": False, "external_action": "none",
        },
    )
    db = _Db()
    result = create_disruption_projection(
        "obs-1",
        DisruptionProjectionRequest(
            target_node_id="variant-1", baseline_version="allocation-v1",
            baseline={"currency": "AUD"}, decision_time="2026-08-03T00:30:00Z",
        ),
        role="owner", db=db,
    )
    assert captured["tenant_id"] == "tenant-a"
    assert captured["observation_id"] == "obs-1"
    assert result["external_action"] == "none"
    assert db.commits == 1
