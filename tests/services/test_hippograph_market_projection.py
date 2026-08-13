import pytest

from src.app.services.hippograph_market_projection import project_cohort_market_signals


def _row(**overrides):
    row = {
        "tenant_id": "t1", "cohort_key": "portable-workstations-sydney",
        "metric": "search_demand", "cohort_size": 12, "observation_count": 20,
        "value": 0.7, "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-08T00:00:00Z", "product_ref": "LAP-1",
    }
    row.update(overrides)
    return row


def test_projection_hashes_cohort_and_suppresses_small_groups():
    projection = project_cohort_market_signals([
        _row(), _row(cohort_key="tiny", cohort_size=3, product_ref="LAP-2"),
        _row(tenant_id="other", cohort_key="other"),
    ], tenant_id="t1")
    assert len(projection.signals) == 1
    assert projection.signals[0].cohort_ref.startswith("cohort:")
    assert "portable" not in projection.signals[0].cohort_ref
    assert projection.signals[0].cohort_size_band == "10-24"
    assert projection.suppressed_small_cohorts == 1
    assert projection.contains_individual_identifiers is False
    assert projection.ranking_authority == projection.commerce_authority == "none"


def test_individual_scope_and_extra_pii_fields_fail_closed():
    with pytest.raises(ValueError, match="individual_scope_forbidden"):
        project_cohort_market_signals([_row(cohort_key="user:alice")], tenant_id="t1")
    with pytest.raises(ValueError):
        project_cohort_market_signals([_row(email="buyer@example.com")], tenant_id="t1")
