import pytest

from src.app.services.supplier_intelligence import supplier_metrics


def test_supplier_metrics_are_tenant_scoped_and_typed():
    events = [
        {"tenant_id": "a", "supplier_id": "s1", "event_type": "quote",
         "outcome": "accepted", "source_record_id": "q1"},
        {"tenant_id": "a", "supplier_id": "s1", "event_type": "delivery",
         "requested_qty": 10, "filled_qty": 9, "on_time": True,
         "lead_time_days": 6, "source_record_id": "d1"},
        {"tenant_id": "a", "supplier_id": "s1", "event_type": "delivery",
         "requested_qty": 10, "filled_qty": 10, "on_time": True,
         "lead_time_days": 8, "source_record_id": "d2"},
        {"tenant_id": "a", "supplier_id": "s1", "event_type": "substitution",
         "source_record_id": "s1"},
        {"tenant_id": "b", "supplier_id": "s1", "event_type": "quote",
         "outcome": "rejected", "source_record_id": "other-tenant"},
    ]

    result = supplier_metrics(tenant_id="a", supplier_id="s1", events=events)

    assert result["quote_acceptance_rate"] == 1.0
    assert result["quote_rejection_rate"] == 0.0
    assert result["fill_rate"] == pytest.approx(0.95)
    assert result["otif_rate"] == 0.5
    assert result["lead_time_mean_days"] == 7.0
    assert result["lead_time_stddev_days"] == 1.0
    assert result["source_count"] == 4
    assert result["authority"] == "advisory_metrics_only"
