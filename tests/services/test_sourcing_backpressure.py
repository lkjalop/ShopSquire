from datetime import datetime, timedelta, timezone

import pytest

from src.app.services.sourcing_backpressure import (
    SourcingBackpressurePolicy,
    SourcingQueueState,
    evaluate_sourcing_admission,
)


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _policy() -> SourcingBackpressurePolicy:
    return SourcingBackpressurePolicy(
        max_open_requests=4,
        max_open_units=100,
        max_request_units=50,
        max_dispatches_per_hour=3,
        acknowledgement_sla=timedelta(hours=2),
    )


def test_compatible_demand_consolidates_without_new_supplier_contact():
    decision = evaluate_sourcing_admission(
        policy=_policy(),
        state=SourcingQueueState(
            open_requests=4, open_units=70, dispatches_last_hour=3,
            oldest_unacknowledged_at=NOW - timedelta(minutes=30),
        ),
        requested_units=20,
        compatible_open_request=True,
        urgent=False,
        now=NOW,
    )
    assert decision.action == "consolidate"
    assert decision.external_contact_permitted is False
    assert decision.projected_open_units == 90


def test_normal_demand_is_deferred_when_supplier_or_rate_capacity_is_exhausted():
    decision = evaluate_sourcing_admission(
        policy=_policy(),
        state=SourcingQueueState(
            open_requests=4, open_units=95, dispatches_last_hour=3,
            oldest_unacknowledged_at=NOW - timedelta(minutes=20),
        ),
        requested_units=10,
        compatible_open_request=False,
        urgent=False,
        now=NOW,
    )
    assert decision.action == "defer"
    assert decision.external_contact_permitted is False
    assert set(decision.reason_codes) == {
        "supplier_open_request_limit",
        "supplier_open_unit_limit",
        "supplier_dispatch_rate_limit",
    }


def test_urgent_demand_seeks_alternative_instead_of_overwhelming_supplier():
    decision = evaluate_sourcing_admission(
        policy=_policy(),
        state=SourcingQueueState(
            open_requests=4, open_units=100, dispatches_last_hour=3,
            oldest_unacknowledged_at=NOW - timedelta(hours=3),
        ),
        requested_units=10,
        compatible_open_request=False,
        urgent=True,
        now=NOW,
    )
    assert decision.action == "seek_alternative"
    assert decision.external_contact_permitted is False
    assert "supplier_acknowledgement_sla_breached" in decision.reason_codes
    assert decision.next_permitted_actions == (
        "query_approved_alternative_supplier",
        "evaluate_qualified_substitute",
        "request_operator_override",
    )


def test_policy_is_dimension_driven_and_rejects_invalid_limits():
    with pytest.raises(ValueError, match="max_open_requests"):
        SourcingBackpressurePolicy(
            max_open_requests=0,
            max_open_units=100,
            max_request_units=50,
            max_dispatches_per_hour=3,
            acknowledgement_sla=timedelta(hours=2),
        )
