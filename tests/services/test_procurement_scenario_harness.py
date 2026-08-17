from datetime import datetime, timezone

from src.app.services.bounded_allocation_solver import (
    DestinationDemand,
    FacilitySupply,
    TransferLane,
)
from src.app.services.procurement_case_state import DestinationAllocation, ProcurementCaseState
from src.app.services.procurement_disturbance import ProcurementDisturbance
from src.app.services.procurement_scenario_harness import (
    ProcurementScenario,
    ScenarioInvariant,
    run_procurement_scenario,
)


NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)


def test_topology_neutral_eight_disturbance_scenario_has_no_duplicate_effects():
    state = ProcurementCaseState(
        case_id="case-simulator", revision=4, objective="fleet", requested_quantity=60,
        destinations=[DestinationAllocation(
            location_ref="destination-token", location_kind="address_token", quantity=60,
        )],
    )
    kinds = (
        "supplier_delay", "stock_correction", "price_change", "forecast_revision",
        "buyer_quantity_change", "quote_expiry", "supplier_rejection", "supplier_substitute",
    )
    scenario = ProcurementScenario(
        scenario_id="topology-neutral-60", state=state,
        supplies=(
            FacilitySupply(facility_id="local-node", facility_kind="store", sku="SKU-A", on_hand_units=15, reserved_units=2, protected_demand_units=3, observed_at=NOW.isoformat()),
            FacilitySupply(facility_id="network-node", facility_kind="distribution_centre", sku="SKU-A", on_hand_units=35, protected_demand_units=5, observed_at=NOW.isoformat()),
            FacilitySupply(facility_id="supplier-node", facility_kind="supplier", sku="SKU-A", on_hand_units=40, observed_at=NOW.isoformat()),
        ),
        demands=(DestinationDemand(destination_id="destination-token", location_kind="address_token", requested_units=60, deadline_days=10),),
        lanes=(
            TransferLane(lane_id="near", origin_facility_id="local-node", destination_id="destination-token", capacity_units=10, lead_time_days=1, cost_minor_per_unit=100),
            TransferLane(lane_id="network", origin_facility_id="network-node", destination_id="destination-token", capacity_units=30, lead_time_days=3, cost_minor_per_unit=300),
            TransferLane(lane_id="supplier", origin_facility_id="supplier-node", destination_id="destination-token", capacity_units=20, lead_time_days=8, cost_minor_per_unit=500),
        ),
        disturbances=tuple(ProcurementDisturbance(
            disturbance_id=f"d-{kind}", kind=kind, case_id=state.case_id,
            expected_case_revision=state.revision, known_at=NOW.isoformat(),
            effective_at=NOW.isoformat(), evidence_ref=f"fixture:{kind}",
        ) for kind in kinds),
        expected=ScenarioInvariant(require_complete_allocation=True),
    )
    result = run_procurement_scenario(
        scenario, knowledge_cutoff=NOW, evaluation_time=NOW,
    )
    assert result.passed is True
    assert result.score == 100
    assert result.duplicate_side_effects == 0
    assert len(result.projections) == 8
    assert all(row.external_calls == row.rfq_calls == row.cart_mutations == 0 for row in result.projections)
