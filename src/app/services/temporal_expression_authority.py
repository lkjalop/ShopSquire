"""Deterministic authority for buyer deadline expressions.

Language models may identify the expression and timezone, but only this module
may turn them into an executable instant. Ambiguous language stays unresolved.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


ResolutionStatus = Literal["not_attempted", "resolved", "ambiguous", "unresolved"]

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
}
_RELATIVE_DURATION = re.compile(
    r"^(?:within|in)\s+(?P<count>\d+|[a-z-]+)\s+"
    r"(?P<unit>hours?|days?|weeks?)$",
    re.IGNORECASE,
)
_RELATIVE_WEEKDAY = re.compile(
    r"^(?:this|next|coming)\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)$",
    re.IGNORECASE,
)


class TemporalResolutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_expression: str = Field(min_length=1, max_length=200)
    timezone: str
    interpretation_instant: str
    resolved_utc_instant: str | None = None
    calendar_source: str
    calendar_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: ResolutionStatus
    unresolved_reason: str | None = None
    clarification_question: str | None = None


def _aware(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ValueError("interpretation_instant_requires_timezone")
    return parsed


def _calendar_version(zone_name: str) -> str:
    try:
        return f"tzdata:{version('tzdata')}:{zone_name}"
    except PackageNotFoundError:
        return f"system-zoneinfo:{zone_name}"


def _count(token: str) -> int | None:
    if token.isdigit():
        value = int(token)
        return value if 0 < value <= 365 else None
    return _NUMBER_WORDS.get(token.casefold())


def _record(
    *, expression: str, zone_name: str, interpreted_at: datetime,
    status: ResolutionStatus, resolved: datetime | None = None,
    confidence: float, reason: str | None = None,
    clarification: str | None = None, source: str = "iana_tzdb",
) -> TemporalResolutionRecord:
    return TemporalResolutionRecord(
        original_expression=expression,
        timezone=zone_name,
        interpretation_instant=interpreted_at.astimezone(timezone.utc).isoformat(),
        resolved_utc_instant=(
            resolved.astimezone(timezone.utc).isoformat() if resolved is not None else None
        ),
        calendar_source=source,
        calendar_version=_calendar_version(zone_name),
        confidence=confidence,
        status=status,
        unresolved_reason=reason,
        clarification_question=clarification,
    )


def resolve_temporal_expression(
    expression: str,
    *,
    timezone_name: str,
    interpretation_instant: datetime | str,
) -> TemporalResolutionRecord:
    """Resolve only expressions with one deterministic temporal meaning."""

    normalized = " ".join(str(expression or "").strip().split())
    if not normalized:
        raise ValueError("temporal_expression_required")
    zone = ZoneInfo(timezone_name)
    interpreted = _aware(interpretation_instant)

    try:
        explicit = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        explicit = None
    if explicit is not None:
        if explicit.tzinfo is None:
            return _record(
                expression=normalized, zone_name=timezone_name,
                interpreted_at=interpreted, status="ambiguous", confidence=0.0,
                reason="explicit_instant_missing_timezone",
                clarification="Which timezone applies to that deadline?",
                source="buyer_explicit_instant",
            )
        return _record(
            expression=normalized, zone_name=timezone_name,
            interpreted_at=interpreted, status="resolved", resolved=explicit,
            confidence=1.0, source="buyer_explicit_instant",
        )

    relative = _RELATIVE_DURATION.fullmatch(normalized)
    if relative:
        amount = _count(relative.group("count"))
        if amount is None:
            return _record(
                expression=normalized, zone_name=timezone_name,
                interpreted_at=interpreted, status="unresolved", confidence=0.0,
                reason="relative_duration_out_of_range",
                clarification="What exact deadline should I use?",
            )
        unit = relative.group("unit").casefold()
        delta = (
            timedelta(hours=amount) if unit.startswith("hour")
            else timedelta(days=amount * (7 if unit.startswith("week") else 1))
        )
        # Duration is applied on the buyer's local wall-clock timeline. ZoneInfo
        # then computes the correct UTC offset across daylight-saving changes.
        resolved = interpreted.astimezone(zone) + delta
        return _record(
            expression=normalized, zone_name=timezone_name,
            interpreted_at=interpreted, status="resolved", resolved=resolved,
            confidence=1.0,
        )

    if _RELATIVE_WEEKDAY.fullmatch(normalized):
        return _record(
            expression=normalized, zone_name=timezone_name,
            interpreted_at=interpreted, status="ambiguous", confidence=0.0,
            reason="relative_weekday_requires_date_and_time_confirmation",
            clarification=(
                f"What exact date and local time in {timezone_name} should I use for "
                f"'{normalized}'?"
            ),
        )

    return _record(
        expression=normalized, zone_name=timezone_name,
        interpreted_at=interpreted, status="unresolved", confidence=0.0,
        reason="unsupported_temporal_expression",
        clarification="What exact date, local time, and timezone should I use?",
    )


__all__ = ["TemporalResolutionRecord", "resolve_temporal_expression"]
