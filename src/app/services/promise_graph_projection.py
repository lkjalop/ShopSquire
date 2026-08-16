"""Deterministic delivery-promise projection over governed supply paths."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.evidence_measurements import EvidenceMeasurement, MeasurementState


class PromisePathVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_index: int = Field(ge=0)
    status: Literal["meets", "fails", "conditional"]
    lead_time: EvidenceMeasurement
    capacity: EvidenceMeasurement
    reasons: list[str]


class PromiseGraphProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["promise-graph-v1"] = "promise-graph-v1"
    status: Literal["feasible", "failed", "conditional", "empty", "unavailable"]
    requested_quantity: int = Field(ge=1)
    deadline_days: int = Field(ge=0)
    paths: list[PromisePathVerdict]
    selected_path_index: int | None = None
    authority: Literal["advisory_only"] = "advisory_only"
    execution_allowed: Literal[False] = False


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def project_delivery_promise(
    path_result: dict[str, Any], *, requested_quantity: int, deadline_days: int,
    source_status: str = "healthy",
) -> PromiseGraphProjection:
    """Evaluate paths without converting missing capacity or lead time to zero."""

    quantity = max(1, int(requested_quantity))
    deadline = max(0, int(deadline_days))
    raw_paths = list(path_result.get("paths") or [])
    if not raw_paths:
        unavailable = source_status in {"unavailable", "failed", "not_configured"}
        return PromiseGraphProjection(
            status="unavailable" if unavailable else "empty",
            requested_quantity=quantity, deadline_days=deadline, paths=[],
        )

    verdicts: list[PromisePathVerdict] = []
    for index, edges in enumerate(raw_paths):
        lead_values: list[float] = []
        capacities: list[float] = []
        lead_unknown = capacity_unknown = False
        for edge in edges:
            props = dict(edge.get("properties") or {})
            lead = _number(props.get("lead_time_days_p50"))
            capacity = _number(props.get("capacity_units"))
            lead_unknown = lead_unknown or lead is None
            capacity_unknown = capacity_unknown or capacity is None
            if lead is not None:
                lead_values.append(max(0.0, lead))
            if capacity is not None:
                capacities.append(max(0.0, capacity))
        total_lead = sum(lead_values) if not lead_unknown else None
        path_capacity = min(capacities) if capacities and not capacity_unknown else None
        reasons: list[str] = []
        if total_lead is None:
            reasons.append("lead_time_not_disclosed")
        elif total_lead > deadline:
            reasons.append("deadline_failed")
        if path_capacity is None:
            reasons.append("capacity_not_disclosed")
        elif path_capacity < quantity:
            reasons.append("quantity_failed")
        if not reasons:
            status = "meets"
        elif any(reason.endswith("_failed") for reason in reasons):
            status = "fails"
        else:
            status = "conditional"
        verdicts.append(PromisePathVerdict(
            path_index=index, status=status, reasons=reasons,
            lead_time=EvidenceMeasurement(
                metric="path_lead_time_days",
                state=(MeasurementState.DERIVED if total_lead is not None
                       else MeasurementState.NOT_DISCLOSED),
                value=total_lead, unit="days" if total_lead is not None else None,
                source_authority="governed_supply_path",
                reason=(None if total_lead is not None else "One or more lanes did not disclose lead time."),
            ),
            capacity=EvidenceMeasurement(
                metric="path_capacity_units",
                state=(MeasurementState.DERIVED if path_capacity is not None
                       else MeasurementState.NOT_DISCLOSED),
                value=path_capacity, unit="units" if path_capacity is not None else None,
                source_authority="governed_supply_path",
                reason=(None if path_capacity is not None else "One or more lanes did not disclose capacity."),
            ),
        ))
    meets = [row for row in verdicts if row.status == "meets"]
    conditional = [row for row in verdicts if row.status == "conditional"]
    selected = min(
        meets or conditional,
        key=lambda row: (
            float(row.lead_time.value) if row.lead_time.value is not None else float("inf"),
            row.path_index,
        ),
        default=None,
    )
    status = "feasible" if meets else "conditional" if conditional else "failed"
    return PromiseGraphProjection(
        status=status, requested_quantity=quantity, deadline_days=deadline,
        paths=verdicts, selected_path_index=selected.path_index if selected else None,
    )


__all__ = ["PromiseGraphProjection", "PromisePathVerdict", "project_delivery_promise"]
