"""Censor-aware projection of buyer behaviour for advisory analytics.

It never guesses intent from absence.  A session can be right-censored while
the buyer is still considering a purchase; only explicit abandonment or an
elapsed observation window contributes to an abandonment rate.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict

from src.app.services.evidence_measurements import EvidenceMeasurement, MeasurementState


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


class BehavioralSignalProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "behavioral-signal-projection-v1"
    measurements: list[EvidenceMeasurement]
    right_censored_sessions: int
    withheld_sessions: int
    guardrails: list[str]
    ranking_authority: str = "none"
    commerce_authority: str = "none"


def project_behavioral_signals(
    events: Iterable[dict[str, Any]], *, now: datetime | None = None,
    abandonment_window: timedelta = timedelta(hours=24),
) -> BehavioralSignalProjection:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    withheld: set[str] = set()
    for event in events:
        session_id = str(event.get("session_id") or "").strip()
        if not session_id:
            continue
        if str(event.get("consent_state") or "").lower() == "denied":
            withheld.add(session_id)
            continue
        sessions[session_id].append(dict(event))

    hover_sessions: set[str] = set()
    clicked_sessions: set[str] = set()
    carted_sessions: set[str] = set()
    purchased_sessions: set[str] = set()
    mature_cart_sessions: set[str] = set()
    abandoned_sessions: set[str] = set()
    censored: set[str] = set()
    for session_id, rows in sessions.items():
        types = {str(row.get("event_type") or "").lower() for row in rows}
        if "hover" in types:
            hover_sessions.add(session_id)
        if types & {"click", "select_item"}:
            clicked_sessions.add(session_id)
        if "add_to_cart" not in types:
            continue
        carted_sessions.add(session_id)
        if "purchase" in types:
            purchased_sessions.add(session_id)
            mature_cart_sessions.add(session_id)
            continue
        if types & {"cart_abandoned", "checkout_abandoned", "session_closed"}:
            abandoned_sessions.add(session_id)
            mature_cart_sessions.add(session_id)
            continue
        last_time = max((_time(row.get("occurred_at")) for row in rows), default=None)
        if last_time is not None and current - last_time >= abandonment_window:
            abandoned_sessions.add(session_id)
            mature_cart_sessions.add(session_id)
        else:
            censored.add(session_id)

    measurements: list[EvidenceMeasurement] = []
    if hover_sessions:
        numerator = len(hover_sessions & clicked_sessions)
        denominator = len(hover_sessions)
        measurements.append(EvidenceMeasurement(
            metric="hover_to_click_rate", state=MeasurementState.DERIVED,
            value=round(numerator / denominator, 4), unit="ratio",
            numerator=numerator, denominator=denominator,
            source_authority="consented_behavioral_events",
            reason="A hover is attention evidence only; it is not purchase intent.",
        ))
    else:
        measurements.append(EvidenceMeasurement(
            metric="hover_to_click_rate", state=MeasurementState.NOT_COLLECTED,
            reason="No consented hover observations were available.",
        ))
    if mature_cart_sessions:
        numerator = len(abandoned_sessions)
        denominator = len(mature_cart_sessions)
        measurements.append(EvidenceMeasurement(
            metric="cart_abandonment_rate", state=MeasurementState.DERIVED,
            value=round(numerator / denominator, 4), unit="ratio",
            numerator=numerator, denominator=denominator,
            source_authority="closed_or_mature_cart_sessions",
            reason="Open sessions are excluded until the observation window closes.",
        ))
    else:
        measurements.append(EvidenceMeasurement(
            metric="cart_abandonment_rate",
            state=(MeasurementState.RIGHT_CENSORED if censored else MeasurementState.NOT_COLLECTED),
            reason=("Cart sessions remain inside the observation window."
                    if censored else "No eligible cart sessions were observed."),
        ))
    return BehavioralSignalProjection(
        measurements=measurements,
        right_censored_sessions=len(censored), withheld_sessions=len(withheld),
        guardrails=[
            "Absence of a click is not a negative preference.",
            "Hover, click and cart signals are advisory and consent scoped.",
            "Open sessions do not count as abandonment.",
            "Behavior cannot override verified fit, policy, availability or buyer confirmation.",
        ],
    )


__all__ = ["BehavioralSignalProjection", "project_behavioral_signals"]
