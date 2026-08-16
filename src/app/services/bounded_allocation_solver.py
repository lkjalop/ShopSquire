"""Topology-agnostic, bounded min-cost allocation for advisory procurement plans.

The solver consumes typed supply nodes and transfer lanes. Place names are data;
no city, store, warehouse, port, or supplier is privileged in code. It never
reserves stock or sends a supplier request.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FacilityKind = Literal["store", "warehouse", "distribution_centre", "port", "supplier"]


class FacilitySupply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    facility_id: str = Field(min_length=1, max_length=200)
    facility_kind: FacilityKind
    sku: str = Field(min_length=1, max_length=200)
    on_hand_units: int = Field(ge=0, le=1_000_000)
    reserved_units: int = Field(default=0, ge=0, le=1_000_000)
    protected_demand_units: int = Field(default=0, ge=0, le=1_000_000)
    observed_at: str

    @property
    def allocatable_units(self) -> int:
        return max(0, self.on_hand_units - self.reserved_units - self.protected_demand_units)


class DestinationDemand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    destination_id: str = Field(min_length=1, max_length=200)
    location_kind: Literal["address_token", "suburb", "town", "city", "region", "store"]
    requested_units: int = Field(ge=1, le=1_000_000)
    deadline_days: int = Field(ge=0, le=3650)


class TransferLane(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str = Field(min_length=1, max_length=200)
    origin_facility_id: str = Field(min_length=1, max_length=200)
    destination_id: str = Field(min_length=1, max_length=200)
    capacity_units: int = Field(ge=0, le=1_000_000)
    lead_time_days: int = Field(ge=0, le=3650)
    cost_minor_per_unit: int = Field(default=0, ge=0, le=1_000_000_000)
    available: bool = True


class AllocationLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    facility_id: str
    facility_kind: FacilityKind
    destination_id: str
    lane_id: str
    sku: str
    quantity: int = Field(ge=1)
    lead_time_days: int = Field(ge=0)
    cost_minor: int = Field(ge=0)


class AllocationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["bounded-allocation-v1"] = "bounded-allocation-v1"
    status: Literal["complete", "partial", "infeasible"]
    requested_units: int
    allocated_units: int
    shortfall_units: int
    total_transfer_cost_minor: int
    lines: tuple[AllocationLine, ...]
    protected_units_by_facility: dict[str, int]
    reasons: tuple[str, ...]
    authority: Literal["advisory_only"] = "advisory_only"
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def conserve_quantity(self) -> "AllocationPlan":
        if sum(line.quantity for line in self.lines) != self.allocated_units:
            raise ValueError("allocation_quantity_not_conserved")
        if self.allocated_units + self.shortfall_units != self.requested_units:
            raise ValueError("allocation_shortfall_not_conserved")
        return self


def solve_bounded_allocation(
    *, supplies: list[FacilitySupply], demands: list[DestinationDemand],
    lanes: list[TransferLane], max_nodes: int = 128,
) -> AllocationPlan:
    """Solve a bounded transportation problem using successive shortest paths."""
    if len(supplies) + len(demands) + len(lanes) > max_nodes:
        raise ValueError("allocation_problem_too_large")
    requested = sum(row.requested_units for row in demands)
    if requested <= 0:
        raise ValueError("allocation_demand_required")
    supply_by_id = {row.facility_id: row for row in supplies}
    demand_by_id = {row.destination_id: row for row in demands}
    if len(supply_by_id) != len(supplies) or len(demand_by_id) != len(demands):
        raise ValueError("duplicate_allocation_node")

    # Residual graph edge: [to, reverse_index, remaining_capacity, unit_cost, metadata].
    graph: list[list[list]] = []
    node_index: dict[str, int] = {}

    def node(name: str) -> int:
        if name not in node_index:
            node_index[name] = len(graph)
            graph.append([])
        return node_index[name]

    def edge(source: int, target: int, capacity: int, cost: int, metadata=None) -> None:
        forward = [target, len(graph[target]), capacity, cost, metadata, capacity]
        reverse = [source, len(graph[source]), 0, -cost, None, 0]
        graph[source].append(forward)
        graph[target].append(reverse)

    source = node("source")
    sink = node("sink")
    for supply in supplies:
        edge(source, node(f"facility:{supply.facility_id}"), supply.allocatable_units, 0)
    for demand in demands:
        edge(node(f"destination:{demand.destination_id}"), sink, demand.requested_units, 0)
    eligible_lanes: list[TransferLane] = []
    for lane in lanes:
        supply = supply_by_id.get(lane.origin_facility_id)
        demand = demand_by_id.get(lane.destination_id)
        if not supply or not demand or not lane.available:
            continue
        if lane.lead_time_days > demand.deadline_days:
            continue
        eligible_lanes.append(lane)
        edge(
            node(f"facility:{supply.facility_id}"),
            node(f"destination:{demand.destination_id}"),
            min(lane.capacity_units, supply.allocatable_units),
            lane.cost_minor_per_unit,
            lane,
        )

    flow = cost = 0
    while flow < requested:
        distance = [10**30] * len(graph)
        parent: list[tuple[int, int] | None] = [None] * len(graph)
        distance[source] = 0
        # Residual reverse edges carry negative cost, so use a bounded
        # Bellman-Ford relaxation rather than an invalid plain Dijkstra pass.
        for _ in range(max(0, len(graph) - 1)):
            changed = False
            for current, outgoing in enumerate(graph):
                if distance[current] == 10**30:
                    continue
                for index, item in enumerate(outgoing):
                    target, _, capacity, unit_cost, _, _ = item
                    candidate = distance[current] + unit_cost
                    if capacity > 0 and candidate < distance[target]:
                        distance[target] = candidate
                        parent[target] = (current, index)
                        changed = True
            if not changed:
                break
        if parent[sink] is None:
            break
        amount = requested - flow
        cursor = sink
        while cursor != source:
            previous, index = parent[cursor]
            amount = min(amount, graph[previous][index][2])
            cursor = previous
        cursor = sink
        while cursor != source:
            previous, index = parent[cursor]
            item = graph[previous][index]
            item[2] -= amount
            graph[cursor][item[1]][2] += amount
            cursor = previous
        flow += amount
        cost += amount * distance[sink]

    lines: list[AllocationLine] = []
    for supply in supplies:
        origin = node_index[f"facility:{supply.facility_id}"]
        for item in graph[origin]:
            lane = item[4]
            if not isinstance(lane, TransferLane):
                continue
            used = item[5] - item[2]
            if used <= 0:
                continue
            lines.append(AllocationLine(
                facility_id=supply.facility_id, facility_kind=supply.facility_kind,
                destination_id=lane.destination_id, lane_id=lane.lane_id,
                sku=supply.sku, quantity=used, lead_time_days=lane.lead_time_days,
                cost_minor=used * lane.cost_minor_per_unit,
            ))
    lines.sort(key=lambda row: (row.destination_id, row.cost_minor, row.facility_id, row.lane_id))
    shortfall = requested - flow
    reasons: list[str] = []
    if not eligible_lanes:
        reasons.append("no_eligible_lane_by_deadline")
    if sum(row.allocatable_units for row in supplies) < requested:
        reasons.append("protected_or_available_supply_insufficient")
    if shortfall and eligible_lanes:
        reasons.append("lane_or_destination_capacity_insufficient")
    return AllocationPlan(
        status="complete" if shortfall == 0 else "partial" if flow else "infeasible",
        requested_units=requested, allocated_units=flow, shortfall_units=shortfall,
        total_transfer_cost_minor=cost, lines=tuple(lines),
        protected_units_by_facility={
            row.facility_id: row.reserved_units + row.protected_demand_units for row in supplies
        },
        reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "AllocationLine", "AllocationPlan", "DestinationDemand", "FacilitySupply",
    "TransferLane", "solve_bounded_allocation",
]
