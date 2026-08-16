"""Typed, durable buyer intent and spatiotemporal query compilation.

The model may *propose* patches to this contract.  Deterministic validation owns
revision checks, invariants and the effective case state.  Commerce execution is
deliberately outside this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MoneyConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    scope: Literal["per_unit", "total", "unknown"] = "unknown"

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class DestinationAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    location_ref: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=0, le=1_000_000)
    location_kind: Literal["region", "city", "store", "warehouse", "address_token", "unknown"] = "unknown"


class TemporalConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_expression: str | None = Field(default=None, max_length=200)
    required_by: str | None = None
    timezone: str = "Australia/Sydney"
    as_of: str | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("required_by", "as_of")
    @classmethod
    def aware_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("temporal_timestamp_requires_timezone")
        return value


class ProcurementCaseState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "procurement_case_state.v1"
    case_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(default=1, ge=1)
    objective: str | None = Field(default=None, max_length=2_000)
    workloads: list[str] = Field(default_factory=list, max_length=20)
    selected_sku: str | None = Field(default=None, max_length=200)
    candidate_skus: list[str] = Field(default_factory=list, max_length=100)
    requested_quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    budget: MoneyConstraint | None = None
    destinations: list[DestinationAllocation] = Field(default_factory=list, max_length=100)
    temporal: TemporalConstraint | None = None
    policies: dict[str, Any] = Field(default_factory=dict)
    research: dict[str, Any] = Field(default_factory=dict)
    requirements: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    fulfilment: dict[str, Any] = Field(default_factory=dict)
    authority: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def allocation_matches_total(self) -> "ProcurementCaseState":
        refs = [row.location_ref.casefold() for row in self.destinations]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_destination")
        if self.destinations and self.requested_quantity is not None:
            if sum(row.quantity for row in self.destinations) != self.requested_quantity:
                raise ValueError("destination_quantity_total_mismatch")
        return self


class CasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["set", "add", "remove", "move_quantity"]
    path: str = Field(min_length=1, max_length=120)
    value: Any = None
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    from_ref: str | None = Field(default=None, max_length=200)
    to_ref: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=200)


class CasePatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: ProcurementCaseState
    changed_paths: tuple[str, ...]
    preserved_paths: tuple[str, ...]


class SpatioTemporalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "spatiotemporal_query.v1"
    query_type: str
    query_purpose: str
    case_id: str
    case_revision: int
    objective: str | None
    workloads: list[str]
    product_scope: list[str]
    requested_quantity: int | None
    destinations: list[DestinationAllocation]
    required_by: datetime | None
    as_of: datetime
    timezone: str
    metrics: list[str]
    constraints: dict[str, Any]
    search_dimensions: dict[str, list[str]]
    allowed_dimensions: list[str]
    prohibited_dimensions: list[str]
    unresolved_fields: list[str]
    external_research_authorized: bool
    promise_authority: Literal["none", "calculation_only"] = "none"


_SET_PATHS = {
    "objective", "selected_sku", "requested_quantity", "budget.amount_minor",
    "budget.currency", "budget.scope", "temporal.required_by", "temporal.as_of",
    "temporal.original_expression", "temporal.timezone", "destinations",
}


def _copy_state(state: ProcurementCaseState) -> dict[str, Any]:
    return state.model_dump(mode="python")


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    if path not in _SET_PATHS:
        raise ValueError(f"unsupported_case_patch_path:{path}")
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        if not isinstance(cursor.get(part), dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def _move_quantity(data: dict[str, Any], patch: CasePatch) -> None:
    if patch.path != "destinations" or not patch.from_ref or not patch.to_ref or not patch.quantity:
        raise ValueError("destination_move_contract_incomplete")
    rows = [dict(row) for row in data.get("destinations") or []]
    by_ref = {str(row.get("location_ref") or "").casefold(): row for row in rows}
    source = by_ref.get(patch.from_ref.casefold())
    if source is None:
        raise ValueError("source_destination_not_found")
    if int(source.get("quantity") or 0) < patch.quantity:
        raise ValueError("destination_quantity_insufficient")
    target = by_ref.get(patch.to_ref.casefold())
    if target is None:
        target = {"location_ref": patch.to_ref, "quantity": 0, "location_kind": "unknown"}
        rows.append(target)
    source["quantity"] = int(source["quantity"]) - patch.quantity
    target["quantity"] = int(target.get("quantity") or 0) + patch.quantity
    data["destinations"] = [row for row in rows if int(row.get("quantity") or 0) > 0]


def apply_case_patch_set(
    state: ProcurementCaseState,
    *,
    expected_revision: int,
    patches: list[CasePatch],
) -> CasePatchResult:
    """Apply a model/human-proposed patch set atomically after deterministic validation."""
    if state.revision != expected_revision:
        raise ValueError("case_revision_conflict")
    if not patches:
        raise ValueError("case_patch_set_empty")
    data = _copy_state(state)
    changed: list[str] = []
    for patch in patches:
        if patch.operation == "set":
            _set_path(data, patch.path, patch.value)
        elif patch.operation == "move_quantity":
            _move_quantity(data, patch)
        elif patch.operation in {"add", "remove"} and patch.path in {"workloads", "candidate_skus"}:
            values = list(data.get(patch.path) or [])
            candidate = str(patch.value or "").strip()
            if not candidate:
                raise ValueError("case_patch_value_required")
            if patch.operation == "add" and candidate not in values:
                values.append(candidate)
            elif patch.operation == "remove":
                values = [item for item in values if item != candidate]
            data[patch.path] = values
        else:
            raise ValueError(f"unsupported_case_patch:{patch.operation}:{patch.path}")
        if patch.path not in changed:
            changed.append(patch.path)
    data["revision"] = state.revision + 1
    updated = ProcurementCaseState.model_validate(data)
    all_paths = {
        "objective", "workloads", "selected_sku", "candidate_skus", "requested_quantity",
        "budget", "destinations", "temporal", "policies", "research", "requirements",
        "fulfilment", "authority",
    }
    changed_roots = {path.split(".", 1)[0] for path in changed}
    return CasePatchResult(
        state=updated,
        changed_paths=tuple(changed),
        preserved_paths=tuple(sorted(all_paths - changed_roots)),
    )


def _utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def compile_spatiotemporal_query(
    state: ProcurementCaseState,
    *,
    query_type: str,
    query_purpose: str,
    metrics: list[str],
    now: datetime | None = None,
) -> SpatioTemporalQuery:
    """Compile an executable read query from the retained case, never the last utterance alone."""
    temporal = state.temporal
    as_of = _utc(temporal.as_of if temporal else None) or (now or datetime.now(timezone.utc))
    required_by = _utc(temporal.required_by if temporal else None)
    timezone_name = temporal.timezone if temporal else "Australia/Sydney"
    unresolved: list[str] = []
    if temporal and temporal.original_expression and required_by is None:
        unresolved.append("required_by")
    if not state.workloads:
        unresolved.append("workloads")

    semantic = list(state.workloads)
    spatial = [row.location_ref for row in state.destinations]
    if query_purpose == "workload_discovery":
        allowed = ["semantic"]
        prohibited = ["spatial", "commercial", "inventory"]
        search_dimensions = {"semantic": semantic}
    elif query_purpose in {"logistics_discovery", "fulfilment_computation"}:
        allowed = ["spatial", "temporal", "commercial", "inventory"]
        prohibited = ["buyer_identity"]
        search_dimensions = {"semantic": semantic, "spatial": spatial}
    else:
        allowed = ["semantic", "spatial", "temporal", "commercial"]
        prohibited = ["buyer_identity"]
        search_dimensions = {"semantic": semantic, "spatial": spatial}

    return SpatioTemporalQuery(
        query_type=query_type,
        query_purpose=query_purpose,
        case_id=state.case_id,
        case_revision=state.revision,
        objective=state.objective,
        workloads=list(state.workloads),
        product_scope=[state.selected_sku] if state.selected_sku else list(state.candidate_skus),
        requested_quantity=state.requested_quantity,
        destinations=list(state.destinations),
        required_by=required_by,
        as_of=as_of,
        timezone=timezone_name,
        metrics=list(dict.fromkeys(metrics)),
        constraints=dict(state.policies),
        search_dimensions=search_dimensions,
        allowed_dimensions=allowed,
        prohibited_dimensions=prohibited,
        unresolved_fields=unresolved,
        external_research_authorized=bool(state.research.get("consent") is True),
        promise_authority="calculation_only" if required_by and state.destinations else "none",
    )


def project_legacy_case_anchor(anchor: dict[str, Any]) -> ProcurementCaseState:
    """Loss-minimizing adapter while existing chat/core consumers use the flat case anchor."""
    semantic = anchor.get("semantic_resolution") if isinstance(anchor.get("semantic_resolution"), dict) else {}
    workloads: list[str] = []
    for row in semantic.get("hypotheses") or []:
        if isinstance(row, dict):
            label = str(row.get("label") or row.get("name") or "").strip()
            if label and label not in workloads:
                workloads.append(label)
    quantity = anchor.get("requested_quantity") or anchor.get("quantity")
    destination = anchor.get("destination") or anchor.get("destination_token")
    allocation_rows = anchor.get("destination_allocations")
    if isinstance(allocation_rows, list):
        destinations = [
            DestinationAllocation.model_validate(row)
            for row in allocation_rows if isinstance(row, dict)
        ]
    else:
        destinations = (
            [DestinationAllocation(location_ref=str(destination), quantity=int(quantity))]
            if destination and quantity else []
        )
    budget_raw = anchor.get("budget") if isinstance(anchor.get("budget"), dict) else {}
    amount = budget_raw.get("amount_minor") or budget_raw.get("total_cents")
    budget = MoneyConstraint(
        amount_minor=int(amount), currency=str(budget_raw.get("currency") or "AUD"),
        scope=str(budget_raw.get("scope") or "unknown"),
    ) if amount is not None else None
    deadline = anchor.get("deadline") or anchor.get("required_by")
    resolved_deadline = None
    if deadline:
        try:
            datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            resolved_deadline = str(deadline)
        except ValueError:
            # Preserve the buyer's expression without pretending it has been
            # resolved to a timezone-aware instant.
            resolved_deadline = None
    temporal = TemporalConstraint(
        original_expression=str(deadline) if deadline else None,
        required_by=resolved_deadline,
        timezone=str(anchor.get("timezone") or "Australia/Sydney"),
        as_of=anchor.get("as_of"),
    ) if deadline or anchor.get("as_of") else None
    return ProcurementCaseState(
        case_id=str(anchor.get("case_id") or "legacy-unbound"),
        revision=int(anchor.get("revision") or 1),
        objective=anchor.get("objective") or anchor.get("retained_purpose"),
        workloads=workloads,
        selected_sku=anchor.get("selected_sku") or anchor.get("sku"),
        requested_quantity=int(quantity) if quantity is not None else None,
        budget=budget,
        destinations=destinations,
        temporal=temporal,
        policies=dict(anchor.get("policies") or {}),
        research=dict(anchor.get("research") or {}),
        requirements=dict(anchor.get("requirements") or {}),
        fulfilment=dict(anchor.get("fulfilment") or {}),
        authority=dict(anchor.get("authority") or {}),
    )
