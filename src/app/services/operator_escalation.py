"""Pure projection for internal operator escalation.

Business-calendar evidence controls notification timing only. It never changes
inventory, delivery feasibility, supplier-send authority, or payment state.
"""
from __future__ import annotations

from typing import Any, Mapping


def build_operator_escalation(
    *,
    reason: str,
    calendar_expectation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expectation = dict(calendar_expectation or {})
    calendar_state = str(expectation.get("calendar_state") or "unknown").lower()
    response_due_at = str(expectation.get("response_due_at") or "").strip() or None
    if calendar_state == "open" and response_due_at:
        notification_status = "notify_now"
    elif calendar_state in {"closed", "holiday"} and response_due_at:
        notification_status = "scheduled"
    else:
        notification_status = "proposed"
        response_due_at = None
    return {
        "status": "recommended",
        "reason": str(reason),
        "action": "fulfillment_operator_review",
        "notification": {
            "status": notification_status,
            "audience": "authorized_fulfillment_operator",
            "channel": "internal_queue",
        },
        "sla": {
            "calendar_state": calendar_state,
            "response_due_at": response_due_at,
            "calendar_version": expectation.get("calendar_version"),
            "authority": "operational_calendar" if calendar_state != "unknown" else "unavailable",
        },
        "delivery_authority_granted": False,
        "supplier_send_authority_granted": False,
        "external_action": "none",
    }
