"""Deterministic scheduling for governed supplier contact channels.

Operational calendars determine *when a response SLA runs*.  They do not imply
that every channel can be executed by the same transport.  Email may be sent
while a supplier is closed when policy permits it; phone contact is always a
durable human task and is never handed to the email worker.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping


@dataclass(frozen=True)
class ContactSchedule:
    channel: str
    queue_state: str
    transport_eligible: bool
    not_before: str | None
    sla_clock: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_contact_schedule(
    *, channel: str, expectation: Mapping[str, Any] | None, submitted_at: str,
) -> ContactSchedule:
    normalized = str(channel or "email").strip().lower()
    temporal = dict(expectation or {})
    transmission = str(temporal.get("transmission_state") or "").strip().lower()
    sla_clock = str(temporal.get("sla_clock") or "unknown").strip().lower()
    next_open = str(temporal.get("next_open_at") or "").strip() or None

    if normalized == "email":
        if transmission in {"queue_until_open", "blocked_unknown"}:
            return ContactSchedule(
                channel=normalized, queue_state="scheduled", transport_eligible=True,
                not_before=next_open, sla_clock=sla_clock,
                reason="email_waits_for_authorized_window",
            )
        return ContactSchedule(
            channel=normalized, queue_state="pending", transport_eligible=True,
            not_before=submitted_at, sla_clock=sla_clock,
            reason=("email_transmits_sla_paused" if sla_clock == "paused" else "email_due_now"),
        )

    if normalized == "phone":
        return ContactSchedule(
            channel=normalized, queue_state="queued_contact", transport_eligible=False,
            not_before=next_open or submitted_at, sla_clock=sla_clock,
            reason="human_phone_contact_required",
        )

    if normalized in {"edi", "cxml", "api", "portal"}:
        return ContactSchedule(
            channel=normalized, queue_state="connector_queued", transport_eligible=False,
            not_before=next_open or submitted_at, sla_clock=sla_clock,
            reason=f"{normalized}_connector_required",
        )

    return ContactSchedule(
        channel=normalized or "unknown", queue_state="blocked", transport_eligible=False,
        not_before=None, sla_clock=sla_clock, reason="unsupported_supplier_channel",
    )
