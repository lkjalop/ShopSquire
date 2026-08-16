from datetime import datetime, timezone

import pytest

from src.app.services.bounded_allocation_solver import (
    DestinationDemand,
    FacilitySupply,
    TransferLane,
)
from src.app.services.procurement_case_state import (
    DestinationAllocation,
    ProcurementCaseState,
)
from src.app.services.procurement_disturbance import (
    ProcurementDisturbance,
    project_procurement_disturbance,
)


NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)


def _case() -> ProcurementCaseState:
    return ProcurementCaseState(
        case_id="case-60", revision=8, objective="managed engineering fleet",
        workloads=["engineering"], requested_quantity=60,
        destinations=[DestinationAllocation(
            location_ref="buyer-destination-token", location_kind="address_token", quantity=60,
        )],
    )


def _disturbance(kind, *, known="2026-08-17T00:00:00+00:00", effective=None, revision=8):
    return ProcurementDisturbance(
        disturbance_id=f"event-{kind}", kind=kind, case_id="case-60",
        expected_case_revision=revision, known_at=known,
        effective_at=effective or known, evidence_ref=f"receipt:{kind}",
    )


@pytest.mark.parametrize("kind", [
    "supplier_delay", "stock_correction", "price_change", "forecast_revision",
    "buyer_quantity_change", "quote_expiry", "supplier_rejection", "supplier_substitute",
])
def test_disturbances_recompute_only_declared_dependencies_without_side_effects(kind):
    state = _case()
    result = project_procurement_disturbance(
        state=state, disturbance=_disturbance(kind),
        knowledge_cutoff=NOW, evaluation_time=NOW,
    )
    assert result.disposition == "applied"
    assert result.external_calls == result.rfq_calls == result.cart_mutations == 0
    assert "response" in result.recomputed_stages
    if kind in {"supplier_delay", "stock_correction", "forecast_revision", "quote_expiry", "supplier_rejection", "supplier_substitute"}:
        assert "fit" not in result.recomputed_stages
    assert state == _case()  # immutable buyer constraints


def test_known_future_and_historical_replay_do_not_leak_evidence():
    event = _disturbance(
        "supplier_delay", known="2026-08-16T00:00:00+00:00",
        effective="2026-08-20T00:00:00+00:00",
    )
    known_future = project_procurement_disturbance(
        state=_case(), disturbance=event, knowledge_cutoff=NOW, evaluation_time=NOW,
    )
    historical = project_procurement_disturbance(
        state=_case(), disturbance=event,
        knowledge_cutoff=datetime(2026, 8, 15, tzinfo=timezone.utc), evaluation_time=NOW,
    )
    assert known_future.disposition == "known_future"
    assert historical.disposition == "not_yet_known"
    assert known_future.allocation is None
    assert historical.allocation is None


def test_stale_case_revision_cannot_be_projected():
    with pytest.raises(ValueError, match="disturbance_case_revision_conflict"):
        project_procurement_disturbance(
            state=_case(), disturbance=_disturbance("price_change", revision=7),
            knowledge_cutoff=NOW, evaluation_time=NOW,
        )


def test_stock_correction_replans_across_generic_topology_and_protects_local_cover():
    result = project_procurement_disturbance(
        state=_case(), disturbance=_disturbance("stock_correction"),
        knowledge_cutoff=NOW, evaluation_time=NOW,
        supplies=[
            FacilitySupply(
                facility_id="nearest-store", facility_kind="store", sku="LAP-A",
                on_hand_units=15, reserved_units=2, protected_demand_units=3,
                observed_at=NOW.isoformat(),
            ),
            FacilitySupply(
                facility_id="regional-dc", facility_kind="distribution_centre", sku="LAP-A",
                on_hand_units=35, protected_demand_units=5, observed_at=NOW.isoformat(),
            ),
            FacilitySupply(
                facility_id="approved-supplier", facility_kind="supplier", sku="LAP-A",
                on_hand_units=40, observed_at=NOW.isoformat(),
            ),
        ],
        demands=[DestinationDemand(
            destination_id="buyer-destination-token", location_kind="address_token",
            requested_units=60, deadline_days=10,
        )],
        lanes=[
            TransferLane(lane_id="local", origin_facility_id="nearest-store", destination_id="buyer-destination-token", capacity_units=10, lead_time_days=1, cost_minor_per_unit=100),
            TransferLane(lane_id="network", origin_facility_id="regional-dc", destination_id="buyer-destination-token", capacity_units=30, lead_time_days=3, cost_minor_per_unit=300),
            TransferLane(lane_id="supplier", origin_facility_id="approved-supplier", destination_id="buyer-destination-token", capacity_units=20, lead_time_days=8, cost_minor_per_unit=500),
        ],
    )
    assert result.allocation is not None
    assert result.allocation.status == "complete"
    assert [(line.facility_id, line.quantity) for line in result.allocation.lines] == [
        ("nearest-store", 10), ("regional-dc", 30), ("approved-supplier", 20),
    ]
    assert result.allocation.protected_units_by_facility == {
        "nearest-store": 5, "regional-dc": 5, "approved-supplier": 0,
    }
