"""Project one case's recorded supply facts through the bounded allocator.

Locations and lanes are data.  This module contains no city, warehouse, or
supplier names and has advisory authority only.
"""
from __future__ import annotations

from typing import Any

from src.app.services.bounded_allocation_solver import (
    DestinationDemand,
    FacilitySupply,
    TransferLane,
    solve_bounded_allocation,
)


_FACILITY_KINDS = {"store", "warehouse", "distribution_centre", "port", "supplier"}
_LOCATION_KINDS = {"address_token", "suburb", "town", "city", "region", "store"}


def project_case_allocation(
    *, state_data: dict[str, Any], observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return an honest allocation projection or explicit missing inputs."""

    requested = state_data.get("requested_quantity")
    inventory = [row for row in observations if row.get("kind") == "inventory_quantity"]
    latest = inventory[-1] if inventory else {}
    latest_value = dict(latest.get("value") or {})
    fulfilment = dict(state_data.get("fulfilment") or {})
    destination_id = str(
        latest_value.get("destination_id") or fulfilment.get("destination_id") or ""
    ).strip()
    deadline = latest_value.get("deadline_days", fulfilment.get("deadline_days"))
    location_kind = str(
        latest_value.get("destination_kind") or fulfilment.get("destination_kind") or ""
    ).strip()
    missing: list[str] = []
    if not isinstance(requested, int) or requested <= 0:
        missing.append("requested_quantity")
    if not destination_id:
        missing.append("destination_id")
    if location_kind not in _LOCATION_KINDS:
        missing.append("destination_kind")
    if not isinstance(deadline, int) or isinstance(deadline, bool) or deadline < 0:
        missing.append("deadline_days")
    if not inventory:
        missing.append("inventory_observations")
    if missing:
        return {
            "status": "not_evaluated",
            "missing_inputs": list(dict.fromkeys(missing)),
            "authority": "advisory_only",
            "execution_allowed": False,
        }

    selected_sku = str(state_data.get("selected_sku") or "").strip()
    supplies: list[FacilitySupply] = []
    lanes: list[TransferLane] = []
    for index, row in enumerate(inventory):
        value = dict(row.get("value") or {})
        subject = str(row.get("subject_ref") or "")
        sku = str(value.get("sku") or subject.rsplit(":", 1)[-1]).strip()
        if selected_sku and sku != selected_sku:
            continue
        facility_id = str(row.get("location_ref") or value.get("facility_id") or "").strip()
        facility_kind = str(value.get("facility_kind") or "").strip()
        if not facility_id or facility_kind not in _FACILITY_KINDS:
            continue
        observed_at = str(row.get("known_at") or "")
        supplies.append(FacilitySupply(
            facility_id=facility_id, facility_kind=facility_kind, sku=sku,
            on_hand_units=int(value["quantity"]),
            reserved_units=int(value.get("reserved_units") or 0),
            protected_demand_units=int(value.get("protected_demand_units") or 0),
            observed_at=observed_at,
        ))
        lanes.append(TransferLane(
            lane_id=str(value.get("lane_id") or f"recorded-lane-{index}"),
            origin_facility_id=facility_id, destination_id=destination_id,
            capacity_units=int(value.get("lane_capacity_units", value["quantity"])),
            lead_time_days=int(value.get("lead_time_days") or 0),
            cost_minor_per_unit=int(value.get("transfer_cost_minor_per_unit") or 0),
            available=bool(value.get("lane_available", True)),
        ))
    if not supplies:
        return {
            "status": "not_evaluated",
            "missing_inputs": ["eligible_exact_configuration_supply"],
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    plan = solve_bounded_allocation(
        supplies=supplies,
        demands=[DestinationDemand(
            destination_id=destination_id, location_kind=location_kind,
            requested_units=requested, deadline_days=deadline,
        )],
        lanes=lanes,
    )
    return plan.model_dump(mode="json")


__all__ = ["project_case_allocation"]
