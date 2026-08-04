"""Product-agnostic supplier contact and sourcing queue policy.

The core evaluates quantities, queue state, dispatch rate and acknowledgement age. It knows
nothing about laptops, groceries, ERP vendors, email, portals or telephony. Deployments obtain
policy and live queue state through adapters, then execute only the returned permitted action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal


SourcingAdmissionAction = Literal[
    "open_request", "consolidate", "defer", "seek_alternative"
]


@dataclass(frozen=True)
class SourcingBackpressurePolicy:
    max_open_requests: int
    max_open_units: int
    max_request_units: int
    max_dispatches_per_hour: int
    acknowledgement_sla: timedelta

    def __post_init__(self) -> None:
        for field_name in (
            "max_open_requests",
            "max_open_units",
            "max_request_units",
            "max_dispatches_per_hour",
        ):
            if int(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name}_must_be_positive")
        if self.acknowledgement_sla <= timedelta(0):
            raise ValueError("acknowledgement_sla_must_be_positive")


@dataclass(frozen=True)
class SourcingQueueState:
    open_requests: int
    open_units: int
    dispatches_last_hour: int
    oldest_unacknowledged_at: datetime | None = None

    def __post_init__(self) -> None:
        if min(self.open_requests, self.open_units, self.dispatches_last_hour) < 0:
            raise ValueError("sourcing_queue_state_cannot_be_negative")


@dataclass(frozen=True)
class SourcingAdmission:
    action: SourcingAdmissionAction
    external_contact_permitted: bool
    reason_codes: tuple[str, ...]
    projected_open_requests: int
    projected_open_units: int
    queue_age_seconds: int | None
    next_permitted_actions: tuple[str, ...]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_sourcing_admission(
    *,
    policy: SourcingBackpressurePolicy,
    state: SourcingQueueState,
    requested_units: int,
    compatible_open_request: bool,
    urgent: bool,
    now: datetime | None = None,
) -> SourcingAdmission:
    """Return a deterministic admission decision without contacting a supplier."""
    quantity = int(requested_units)
    if quantity <= 0:
        raise ValueError("requested_units_must_be_positive")
    stamp = _utc(now or datetime.now(timezone.utc))
    queue_age_seconds = None
    if state.oldest_unacknowledged_at is not None:
        queue_age_seconds = max(
            0, int((stamp - _utc(state.oldest_unacknowledged_at)).total_seconds())
        )

    projected_requests = state.open_requests + (0 if compatible_open_request else 1)
    projected_units = state.open_units + quantity
    reasons: list[str] = []
    if quantity > policy.max_request_units:
        reasons.append("supplier_request_unit_limit")
    if projected_units > policy.max_open_units:
        reasons.append("supplier_open_unit_limit")
    if not compatible_open_request and projected_requests > policy.max_open_requests:
        reasons.append("supplier_open_request_limit")
    if (
        not compatible_open_request
        and state.dispatches_last_hour >= policy.max_dispatches_per_hour
    ):
        reasons.append("supplier_dispatch_rate_limit")
    if (
        queue_age_seconds is not None
        and queue_age_seconds > int(policy.acknowledgement_sla.total_seconds())
    ):
        reasons.append("supplier_acknowledgement_sla_breached")

    # Consolidation updates an existing draft and deliberately creates no new
    # external contact. It remains allowed only while the unit envelope holds.
    if compatible_open_request and not {
        "supplier_request_unit_limit", "supplier_open_unit_limit"
    }.intersection(reasons):
        return SourcingAdmission(
            action="consolidate",
            external_contact_permitted=False,
            reason_codes=tuple(reasons),
            projected_open_requests=projected_requests,
            projected_open_units=projected_units,
            queue_age_seconds=queue_age_seconds,
            next_permitted_actions=("append_child_demand_to_open_request",),
        )

    if reasons:
        alternative_actions = (
            "query_approved_alternative_supplier",
            "evaluate_qualified_substitute",
            "request_operator_override",
        )
        return SourcingAdmission(
            action="seek_alternative" if urgent else "defer",
            external_contact_permitted=False,
            reason_codes=tuple(sorted(reasons)),
            projected_open_requests=projected_requests,
            projected_open_units=projected_units,
            queue_age_seconds=queue_age_seconds,
            next_permitted_actions=(
                alternative_actions if urgent else
                ("wait_for_supplier_acknowledgement", "query_approved_alternative_supplier")
            ),
        )

    return SourcingAdmission(
        action="open_request",
        external_contact_permitted=True,
        reason_codes=(),
        projected_open_requests=projected_requests,
        projected_open_units=projected_units,
        queue_age_seconds=queue_age_seconds,
        next_permitted_actions=("create_governed_supplier_request",),
    )
