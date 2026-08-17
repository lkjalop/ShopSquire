from src.app.services.shopping_case_allocation_projection import project_case_allocation


def _fact(observation_id, facility, quantity, *, kind, lead, cost=0, protected=0):
    return {
        "observation_id": observation_id,
        "kind": "inventory_quantity",
        "subject_ref": "configuration:CFG-1",
        "location_ref": facility,
        "known_at": "2026-08-17T00:00:00+00:00",
        "value": {
            "quantity": quantity,
            "sku": "CFG-1",
            "facility_kind": kind,
            "destination_id": "buyer-region-token",
            "destination_kind": "region",
            "deadline_days": 3,
            "lead_time_days": lead,
            "lane_capacity_units": quantity,
            "transfer_cost_minor_per_unit": cost,
            "protected_demand_units": protected,
        },
    }


def test_topology_neutral_projection_uses_eligible_locations_and_protected_cover():
    result = project_case_allocation(
        state_data={"requested_quantity": 25, "selected_sku": "CFG-1"},
        observations=[
            _fact("obs-local", "facility-near", 12, kind="store", lead=0, protected=5),
            _fact("obs-region", "facility-region", 30, kind="warehouse", lead=1, cost=100),
            _fact("obs-late", "facility-supplier", 50, kind="supplier", lead=8, cost=10),
        ],
    )
    assert result["status"] == "complete"
    assert result["allocated_units"] == 25
    assert [(row["facility_id"], row["quantity"]) for row in result["lines"]] == [
        ("facility-near", 7), ("facility-region", 18),
    ]
    assert all(row["facility_id"] != "facility-supplier" for row in result["lines"])
    assert result["execution_allowed"] is False


def test_projection_abstains_when_destination_or_deadline_is_undisclosed():
    result = project_case_allocation(
        state_data={"requested_quantity": 30, "selected_sku": "CFG-1"},
        observations=[{
            "kind": "inventory_quantity", "subject_ref": "configuration:CFG-1",
            "location_ref": "facility-a", "known_at": "2026-08-17T00:00:00Z",
            "value": {"quantity": 10, "facility_kind": "warehouse"},
        }],
    )
    assert result["status"] == "not_evaluated"
    assert set(result["missing_inputs"]) == {
        "destination_id", "destination_kind", "deadline_days",
    }
