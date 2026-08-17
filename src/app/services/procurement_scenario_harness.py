"""Deterministic procurement scenario evaluation; no training or side effects."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.bounded_allocation_solver import (
    DestinationDemand,
    FacilitySupply,
    TransferLane,
)
from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_disturbance import (
    DisturbanceProjection,
    ProcurementDisturbance,
    project_procurement_disturbance,
)


class ScenarioInvariant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    no_external_calls: bool = True
    no_rfq_calls: bool = True
    no_cart_mutations: bool = True
    preserve_constraints: bool = True
    require_complete_allocation: bool = False


class ProcurementScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1, max_length=160)
    state: ProcurementCaseState
    hidden_constraints: dict[str, str | int | bool] = Field(default_factory=dict)
    supplies: tuple[FacilitySupply, ...] = ()
    demands: tuple[DestinationDemand, ...] = ()
    lanes: tuple[TransferLane, ...] = ()
    disturbances: tuple[ProcurementDisturbance, ...]
    permitted_actions: tuple[Literal["project", "allocate"], ...] = ("project", "allocate")
    expected: ScenarioInvariant = ScenarioInvariant()


class ScenarioScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    passed: bool
    score: int = Field(ge=0, le=100)
    failures: tuple[str, ...]
    projections: tuple[DisturbanceProjection, ...]
    duplicate_side_effects: Literal[0] = 0
    training_authority: Literal[False] = False


def run_procurement_scenario(
    scenario: ProcurementScenario, *, knowledge_cutoff: datetime,
    evaluation_time: datetime,
) -> ScenarioScore:
    baseline_state = scenario.state.model_dump(mode="json")
    projections: list[DisturbanceProjection] = []
    failures: list[str] = []
    for disturbance in scenario.disturbances:
        projection = project_procurement_disturbance(
            state=scenario.state, disturbance=disturbance,
            knowledge_cutoff=knowledge_cutoff, evaluation_time=evaluation_time,
            supplies=list(scenario.supplies) if scenario.supplies else None,
            demands=list(scenario.demands) if scenario.demands else None,
            lanes=list(scenario.lanes) if scenario.lanes else None,
        )
        projections.append(projection)
        if scenario.expected.no_external_calls and projection.external_calls:
            failures.append(f"{disturbance.disturbance_id}:external_call")
        if scenario.expected.no_rfq_calls and projection.rfq_calls:
            failures.append(f"{disturbance.disturbance_id}:rfq_call")
        if scenario.expected.no_cart_mutations and projection.cart_mutations:
            failures.append(f"{disturbance.disturbance_id}:cart_mutation")
        if (
            scenario.expected.require_complete_allocation
            and projection.disposition == "applied"
            and projection.allocation is not None
            and projection.allocation.status != "complete"
        ):
            failures.append(f"{disturbance.disturbance_id}:allocation_incomplete")
    if scenario.expected.preserve_constraints and scenario.state.model_dump(mode="json") != baseline_state:
        failures.append("buyer_constraints_mutated")
    score = max(0, 100 - 20 * len(set(failures)))
    return ScenarioScore(
        scenario_id=scenario.scenario_id, passed=not failures, score=score,
        failures=tuple(dict.fromkeys(failures)), projections=tuple(projections),
    )


__all__ = [
    "ProcurementScenario", "ScenarioInvariant", "ScenarioScore",
    "run_procurement_scenario",
]
