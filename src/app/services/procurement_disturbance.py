"""Typed disturbance projection for revision-bound procurement decisions.

This module does not execute research, RFQs, cart changes, or stock reservations.
It identifies the smallest dependent stage set and produces a new advisory
allocation from facts known at the requested replay cutoff.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.services.bounded_allocation_solver import (
    AllocationPlan,
    DestinationDemand,
    FacilitySupply,
    TransferLane,
    solve_bounded_allocation,
)
from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_coordinator import (
    invalidations_for_changed_paths,
)


DisturbanceKind = Literal[
    "supplier_delay",
    "stock_correction",
    "price_change",
    "forecast_revision",
    "buyer_quantity_change",
    "quote_expiry",
    "supplier_rejection",
    "supplier_substitute",
]


_CHANGED_PATH = {
    "supplier_delay": "fulfilment.supplier_lead_time",
    "stock_correction": "fulfilment.inventory",
    "price_change": "fulfilment.price",
    "forecast_revision": "fulfilment.protected_demand",
    "buyer_quantity_change": "requested_quantity",
    "quote_expiry": "fulfilment.quote_validity",
    "supplier_rejection": "fulfilment.supplier_offer",
    "supplier_substitute": "fulfilment.substitution",
}


class ProcurementDisturbance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disturbance_id: str = Field(min_length=1, max_length=160)
    kind: DisturbanceKind
    case_id: str = Field(min_length=1, max_length=200)
    expected_case_revision: int = Field(ge=1)
    known_at: str
    effective_at: str
    evidence_ref: str = Field(min_length=1, max_length=240)

    @field_validator("known_at", "effective_at")
    @classmethod
    def require_aware_time(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("disturbance_time_requires_timezone")
        return value


class DisturbanceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disturbance_id: str
    case_id: str
    case_revision: int
    knowledge_cutoff: str
    evaluation_time: str
    disposition: Literal["applied", "known_future", "not_yet_known"]
    changed_path: str
    recomputed_stages: tuple[str, ...]
    preserved_constraint_hash: str
    allocation: AllocationPlan | None = None
    external_calls: Literal[0] = 0
    rfq_calls: Literal[0] = 0
    cart_mutations: Literal[0] = 0


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ValueError("decision_time_requires_timezone")
    return parsed.astimezone(timezone.utc)


def _constraint_hash(state: ProcurementCaseState) -> str:
    import hashlib
    import json

    retained = {
        "objective": state.objective,
        "workloads": state.workloads,
        "budget": state.budget.model_dump(mode="json") if state.budget else None,
        "destinations": [row.model_dump(mode="json") for row in state.destinations],
        "temporal": state.temporal.model_dump(mode="json") if state.temporal else None,
    }
    return hashlib.sha256(json.dumps(retained, sort_keys=True).encode()).hexdigest()


def project_procurement_disturbance(
    *,
    state: ProcurementCaseState,
    disturbance: ProcurementDisturbance,
    knowledge_cutoff: datetime,
    evaluation_time: datetime,
    supplies: list[FacilitySupply] | None = None,
    demands: list[DestinationDemand] | None = None,
    lanes: list[TransferLane] | None = None,
) -> DisturbanceProjection:
    """Project one fact without changing buyer constraints or causing effects."""
    if disturbance.case_id != state.case_id:
        raise ValueError("disturbance_case_mismatch")
    if disturbance.expected_case_revision != state.revision:
        raise ValueError("disturbance_case_revision_conflict")

    known = _utc(knowledge_cutoff)
    evaluated = _utc(evaluation_time)
    observed = _utc(disturbance.known_at)
    effective = _utc(disturbance.effective_at)
    if observed > known:
        disposition = "not_yet_known"
    elif effective > evaluated:
        disposition = "known_future"
    else:
        disposition = "applied"

    changed_path = _CHANGED_PATH[disturbance.kind]
    invalidation = invalidations_for_changed_paths([changed_path])[0]
    allocation = None
    if disposition == "applied" and supplies is not None and demands is not None and lanes is not None:
        allocation = solve_bounded_allocation(
            supplies=supplies, demands=demands, lanes=lanes,
        )
    return DisturbanceProjection(
        disturbance_id=disturbance.disturbance_id,
        case_id=state.case_id,
        case_revision=state.revision,
        knowledge_cutoff=known.isoformat(),
        evaluation_time=evaluated.isoformat(),
        disposition=disposition,
        changed_path=changed_path,
        recomputed_stages=invalidation.invalidated_stages,
        preserved_constraint_hash=_constraint_hash(state),
        allocation=allocation,
    )


__all__ = [
    "DisturbanceProjection",
    "ProcurementDisturbance",
    "project_procurement_disturbance",
]
