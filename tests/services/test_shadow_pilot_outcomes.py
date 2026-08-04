from datetime import datetime, timezone

from src.app.schemas.metric_evidence import MetricEvidence
from src.app.services.shadow_pilot_outcomes import measure_shadow_pilot_outcomes


def _gmroi() -> MetricEvidence:
    return MetricEvidence(
        metric="gmroi",
        tenant_id="tenant-a",
        subject_type="variant",
        subject_id="variant-1",
        value=2.4,
        unit="annualised_ratio",
        currency="AUD",
        window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        as_of=datetime(2026, 2, 2, tzinfo=timezone.utc),
        status="observed",
        confidence=1.0,
        coverage=1.0,
        source_count=2,
        source_records=["valuation-1", "margin-1"],
        provenance_chain=["valuation/1", "margin/1"],
        definition_version="gmroi_authoritative_v2",
        visibility="operator",
    )


def test_scorecard_measures_comparable_outcomes_and_operator_workload() -> None:
    result = measure_shadow_pilot_outcomes(
        tenant_id="tenant-a",
        window_start="2026-01-01T00:00:00Z",
        window_end="2026-02-01T00:00:00Z",
        forecast_pairs=[
            {
                "tenant_id": "tenant-a",
                "baseline_error": 20,
                "candidate_error": 15,
                "metric": "WAPE",
                "source_record_id": "forecast-1",
            },
        ],
        demand_rows=[
            {
                "tenant_id": "tenant-a",
                "latent_demand_units": 8,
                "fulfilled_units": 5,
                "stockout": True,
                "source_record_id": "demand-1",
            },
            {
                "tenant_id": "tenant-a",
                "latent_demand_units": 4,
                "fulfilled_units": 4,
                "stockout": False,
                "source_record_id": "demand-2",
            },
        ],
        gross_margin_evidence={
            "tenant_id": "tenant-a",
            "value_minor": 30_000,
            "currency": "AUD",
            "source_records": ["margin-1"],
        },
        gmroi_evidence=_gmroi(),
        attribution_events=[
            {"tenant_id": "tenant-a", "eligible": True, "attributed": True},
            {"tenant_id": "tenant-a", "eligible": True, "attributed": False},
            {
                "tenant_id": "tenant-a",
                "eligible": True,
                "attributed": True,
                "late": True,
            },
            {"tenant_id": "tenant-b", "eligible": True, "attributed": True},
        ],
        operator_events=[
            {
                "tenant_id": "tenant-a",
                "event_type": "proposal_reviewed",
                "duration_seconds": 120,
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "proposal_approved",
                "duration_seconds": 60,
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "proposal_overridden",
                "duration_seconds": 30,
            },
            {"tenant_id": "tenant-b", "event_type": "proposal_approved"},
        ],
        simulation_only=False,
    )

    assert result["forecast_value_added"]["value"] == 0.25
    assert result["stockouts"]["lost_units"] == 3
    assert result["stockouts"]["stockout_days"] == 1
    assert result["gross_margin"]["value_minor"] == 30_000
    assert result["gmroi"]["value"] == 2.4
    assert result["attribution"] == {
        "status": "observed",
        "eligible_outcomes": 3,
        "credited_outcomes": 1,
        "late_outcomes_excluded": 1,
        "coverage": 0.333333,
    }
    assert result["operator_workload"]["human_minutes"] == 3.5
    assert result["operator_workload"]["approval_rate"] == 0.5
    assert result["operator_workload"]["override_rate"] == 0.5
    assert result["autonomy_increase_allowed"] is False


def test_scorecard_keeps_missing_evidence_undefined_instead_of_zero() -> None:
    result = measure_shadow_pilot_outcomes(
        tenant_id="tenant-a",
        window_start="2026-01-01T00:00:00Z",
        window_end="2026-02-01T00:00:00Z",
        forecast_pairs=[],
        demand_rows=[],
        gross_margin_evidence=None,
        gmroi_evidence=None,
        attribution_events=[],
        operator_events=[],
        simulation_only=True,
    )

    assert result["forecast_value_added"]["value"] is None
    assert result["stockouts"]["lost_units"] is None
    assert result["gross_margin"]["value_minor"] is None
    assert result["gmroi"]["value"] is None
    assert result["attribution"]["coverage"] is None
    assert result["operator_workload"]["human_minutes"] is None
    assert result["authority"] == "simulation_only"
    assert result["autonomy_increase_allowed"] is False
