"""Provider-neutral operational calendars and business-time response expectations.

The core deliberately knows nothing about Gmail, Graph, SAP, carrier brands, countries, or
product categories.  Adapters provide versioned calendars and response policies; this module
performs deterministic timezone-aware arithmetic over those normalized facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_CURRENT = {"current", "fresh"}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone_aware_datetime_required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class OperationalInterval:
    weekday: int
    start_local: time
    end_local: time

    def __post_init__(self) -> None:
        if not 0 <= int(self.weekday) <= 6:
            raise ValueError("weekday_out_of_range")
        if self.start_local >= self.end_local:
            raise ValueError("overnight_intervals_must_be_split")


@dataclass(frozen=True)
class CalendarException:
    local_date: date
    closed: bool = False
    intervals: tuple[tuple[time, time], ...] = ()

    def __post_init__(self) -> None:
        for start, end in self.intervals:
            if start >= end:
                raise ValueError("invalid_exception_interval")


@dataclass(frozen=True)
class OperationalCalendar:
    calendar_id: str
    owner_type: str
    owner_ref: str
    timezone_name: str
    weekly_intervals: tuple[OperationalInterval, ...]
    exceptions: tuple[CalendarException, ...]
    version: str
    authority: str
    freshness: str

    def __post_init__(self) -> None:
        if not self.calendar_id or not self.owner_type or not self.owner_ref or not self.version:
            raise ValueError("calendar_identity_required")
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("iana_timezone_required") from exc


@dataclass(frozen=True)
class ResponsePolicy:
    version: str
    acknowledgement_business_seconds: int
    quote_business_seconds: int
    transmit_outside_hours: bool
    human_decision_business_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("response_policy_version_required")
        if self.acknowledgement_business_seconds <= 0 or self.quote_business_seconds <= 0:
            raise ValueError("response_policy_durations_must_be_positive")
        if self.human_decision_business_seconds is not None and self.human_decision_business_seconds <= 0:
            raise ValueError("human_decision_duration_must_be_positive")


def _exception(calendar: OperationalCalendar, value: date) -> CalendarException | None:
    return next((item for item in calendar.exceptions if item.local_date == value), None)


def _intervals_for_date(
    calendar: OperationalCalendar, value: date,
) -> tuple[tuple[time, time], ...]:
    exceptional = _exception(calendar, value)
    if exceptional is not None:
        if exceptional.closed:
            return ()
        return tuple(sorted(exceptional.intervals, key=lambda item: item[0]))
    return tuple(
        (item.start_local, item.end_local)
        for item in sorted(calendar.weekly_intervals, key=lambda item: item.start_local)
        if item.weekday == value.weekday()
    )


def _local_bounds(value: date, start: time, end: time, zone: ZoneInfo) -> tuple[datetime, datetime]:
    return datetime.combine(value, start, tzinfo=zone), datetime.combine(value, end, tzinfo=zone)


def _containing_interval(
    calendar: OperationalCalendar, local_value: datetime,
) -> tuple[datetime, datetime] | None:
    zone = ZoneInfo(calendar.timezone_name)
    for start, end in _intervals_for_date(calendar, local_value.date()):
        lower, upper = _local_bounds(local_value.date(), start, end, zone)
        if lower <= local_value < upper:
            return lower, upper
    return None


def _next_open_local(calendar: OperationalCalendar, local_value: datetime) -> datetime | None:
    containing = _containing_interval(calendar, local_value)
    if containing is not None:
        return local_value
    zone = ZoneInfo(calendar.timezone_name)
    for offset in range(0, 371):
        candidate_date = local_value.date() + timedelta(days=offset)
        for start, end in _intervals_for_date(calendar, candidate_date):
            lower, _ = _local_bounds(candidate_date, start, end, zone)
            if lower >= local_value:
                return lower
    return None


def add_business_seconds(
    calendar: OperationalCalendar, start_at: datetime, seconds: int,
) -> datetime | None:
    """Add elapsed operating seconds and return a UTC instant.

    Durations are measured on the UTC timeline between local interval boundaries, so daylight-saving
    changes cannot be treated as fixed UTC offsets.
    """
    if seconds < 0:
        raise ValueError("negative_business_duration")
    if calendar.freshness.lower() not in _CURRENT:
        return None
    zone = ZoneInfo(calendar.timezone_name)
    cursor = _utc(start_at).astimezone(zone)
    remaining = int(seconds)
    cursor = _next_open_local(calendar, cursor)  # type: ignore[assignment]
    if cursor is None:
        return None
    if remaining == 0:
        return cursor.astimezone(timezone.utc)
    for _ in range(10000):
        containing = _containing_interval(calendar, cursor)
        if containing is None:
            cursor = _next_open_local(calendar, cursor)
            if cursor is None:
                return None
            containing = _containing_interval(calendar, cursor)
        if containing is None:  # pragma: no cover - guarded by next-open lookup
            return None
        _, interval_end = containing
        available = max(
            0, int((interval_end.astimezone(timezone.utc) - cursor.astimezone(timezone.utc)).total_seconds())
        )
        if remaining <= available:
            return cursor.astimezone(timezone.utc) + timedelta(seconds=remaining)
        remaining -= available
        cursor = _next_open_local(calendar, interval_end + timedelta(microseconds=1))
        if cursor is None:
            return None
    raise RuntimeError("business_time_iteration_budget_exceeded")


def evaluate_response_expectation(
    *, calendar: OperationalCalendar | None, policy: ResponsePolicy,
    submitted_at: datetime,
) -> dict[str, Any]:
    submitted = _utc(submitted_at)
    if calendar is None:
        return {
            "calendar_state": "unknown", "sla_clock": "unknown",
            "transmission_state": "transmit_now" if policy.transmit_outside_hours else "blocked_unknown",
            "next_open_at": None, "acknowledgement_due_at": None, "quote_due_at": None,
            "reason": "calendar_missing", "freshness": "missing",
            "calendar_version": None, "policy_version": policy.version,
        }
    if calendar.freshness.lower() not in _CURRENT:
        return {
            "calendar_state": "unknown", "sla_clock": "unknown",
            "transmission_state": "transmit_now" if policy.transmit_outside_hours else "blocked_unknown",
            "next_open_at": None, "acknowledgement_due_at": None, "quote_due_at": None,
            "reason": "calendar_stale", "freshness": calendar.freshness,
            "calendar_version": calendar.version, "policy_version": policy.version,
            "calendar_authority": calendar.authority,
        }
    zone = ZoneInfo(calendar.timezone_name)
    local = submitted.astimezone(zone)
    open_now = _containing_interval(calendar, local) is not None
    next_open = None if open_now else _next_open_local(calendar, local)
    start = local if open_now else next_open
    acknowledgement = (
        add_business_seconds(calendar, start, policy.acknowledgement_business_seconds)
        if start is not None else None
    )
    quote = add_business_seconds(calendar, start, policy.quote_business_seconds) if start is not None else None
    human_decision = (
        add_business_seconds(calendar, quote, policy.human_decision_business_seconds)
        if quote is not None and policy.human_decision_business_seconds is not None else None
    )
    return {
        "calendar_state": "open" if open_now else "closed",
        "sla_clock": "running" if open_now else "paused",
        "transmission_state": (
            "transmit_now" if open_now or policy.transmit_outside_hours else "queue_until_open"
        ),
        "submitted_at": submitted.isoformat(),
        "supplier_local_time": local.isoformat(),
        "timezone": calendar.timezone_name,
        "next_open_at": next_open.astimezone(timezone.utc).isoformat() if next_open else None,
        "acknowledgement_due_at": acknowledgement.isoformat() if acknowledgement else None,
        "quote_due_at": quote.isoformat() if quote else None,
        "human_decision_due_at": human_decision.isoformat() if human_decision else None,
        "reason": None,
        "freshness": calendar.freshness,
        "calendar_id": calendar.calendar_id,
        "calendar_version": calendar.version,
        "calendar_authority": calendar.authority,
        "policy_version": policy.version,
    }


def calendar_from_payload(payload: dict[str, Any]) -> OperationalCalendar:
    """Normalize a governed adapter payload into the agnostic core contract."""
    intervals: list[OperationalInterval] = []
    for raw in payload.get("weekly_intervals") or []:
        intervals.append(OperationalInterval(
            weekday=int(raw["weekday"]),
            start_local=time.fromisoformat(str(raw["start_local"])),
            end_local=time.fromisoformat(str(raw["end_local"])),
        ))
    exceptions: list[CalendarException] = []
    for raw in payload.get("exceptions") or []:
        exception_intervals = tuple(
            (time.fromisoformat(str(item["start_local"])), time.fromisoformat(str(item["end_local"])))
            for item in raw.get("intervals") or []
        )
        exceptions.append(CalendarException(
            local_date=date.fromisoformat(str(raw["local_date"])),
            closed=bool(raw.get("closed")), intervals=exception_intervals,
        ))
    return OperationalCalendar(
        calendar_id=str(payload["calendar_id"]), owner_type=str(payload["owner_type"]),
        owner_ref=str(payload["owner_ref"]), timezone_name=str(payload["timezone"]),
        weekly_intervals=tuple(intervals), exceptions=tuple(exceptions),
        version=str(payload["version"]), authority=str(payload.get("authority") or "unknown"),
        freshness=str(payload.get("freshness") or "unknown"),
    )
