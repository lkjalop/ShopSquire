import pytest

from src.app.services.bounded_allocation_solver import (
    DestinationDemand, FacilitySupply, TransferLane, solve_bounded_allocation,
)


def _supply(facility_id, kind, on_hand, *, reserved=0, protected=0):
    return FacilitySupply(
        facility_id=facility_id, facility_kind=kind, sku="CFG-1",
        on_hand_units=on_hand, reserved_units=reserved,
        protected_demand_units=protected, observed_at="2026-08-16T00:00:00Z",
    )


def test_allocates_from_topology_not_hard_coded_places_and_protects_local_cover():
    supplies = [
        _supply("nearest-store", "store", 12, reserved=2, protected=5),
        _supply("regional-dc", "distribution_centre", 30, protected=10),
        _supply("supplier-node", "supplier", 50),
    ]
    demands = [DestinationDemand(
        destination_id="buyer-suburb-token", location_kind="suburb",
        requested_units=25, deadline_days=3,
    )]
    lanes = [
        TransferLane(lane_id="local", origin_facility_id="nearest-store",
                     destination_id="buyer-suburb-token", capacity_units=10,
                     lead_time_days=0, cost_minor_per_unit=0),
        TransferLane(lane_id="dc", origin_facility_id="regional-dc",
                     destination_id="buyer-suburb-token", capacity_units=20,
                     lead_time_days=1, cost_minor_per_unit=100),
        TransferLane(lane_id="supplier", origin_facility_id="supplier-node",
                     destination_id="buyer-suburb-token", capacity_units=50,
                     lead_time_days=8, cost_minor_per_unit=50),
    ]

    result = solve_bounded_allocation(supplies=supplies, demands=demands, lanes=lanes)

    assert result.status == "complete"
    assert result.allocated_units == 25
    assert [(line.facility_id, line.quantity) for line in result.lines] == [
        ("nearest-store", 5), ("regional-dc", 20),
    ]
    assert result.protected_units_by_facility["nearest-store"] == 7
    assert all(line.facility_id != "supplier-node" for line in result.lines)


def test_reports_partial_and_does_not_consume_reserved_or_protected_units():
    result = solve_bounded_allocation(
        supplies=[_supply("warehouse-a", "warehouse", 15, reserved=3, protected=7)],
        demands=[DestinationDemand(destination_id="destination-x", location_kind="town",
                                   requested_units=12, deadline_days=2)],
        lanes=[TransferLane(lane_id="lane-a", origin_facility_id="warehouse-a",
                            destination_id="destination-x", capacity_units=12,
                            lead_time_days=1, cost_minor_per_unit=20)],
    )

    assert result.status == "partial"
    assert result.allocated_units == 5
    assert result.shortfall_units == 7
    assert "protected_or_available_supply_insufficient" in result.reasons


def test_deadline_failure_is_infeasible_even_when_supplier_has_stock():
    result = solve_bounded_allocation(
        supplies=[_supply("supplier-a", "supplier", 100)],
        demands=[DestinationDemand(destination_id="destination-x", location_kind="region",
                                   requested_units=30, deadline_days=1)],
        lanes=[TransferLane(lane_id="late", origin_facility_id="supplier-a",
                            destination_id="destination-x", capacity_units=100,
                            lead_time_days=8, cost_minor_per_unit=1)],
    )
    assert result.status == "infeasible"
    assert result.reasons == ("no_eligible_lane_by_deadline",)


def test_problem_size_is_bounded():
    with pytest.raises(ValueError, match="allocation_problem_too_large"):
        solve_bounded_allocation(
            supplies=[_supply("a", "store", 1)],
            demands=[DestinationDemand(destination_id="x", location_kind="city",
                                       requested_units=1, deadline_days=1)],
            lanes=[], max_nodes=1,
        )
