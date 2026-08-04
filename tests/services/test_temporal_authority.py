from datetime import date, datetime, time, timezone

from src.app.services.temporal_authority import (
    CalendarException,
    OperationalCalendar,
    OperationalInterval,
    ResponsePolicy,
    evaluate_response_expectation,
)


def _weekday_calendar(*, freshness: str = "current") -> OperationalCalendar:
    return OperationalCalendar(
        calendar_id="cal-supplier-mel",
        owner_type="supplier_facility",
        owner_ref="FAC-MEL",
        timezone_name="Australia/Melbourne",
        weekly_intervals=tuple(
            OperationalInterval(weekday=weekday, start_local=time(9), end_local=time(17))
            for weekday in range(5)
        ),
        exceptions=(CalendarException(local_date=date(2026, 8, 10), closed=True),),
        version="calendar-v3",
        authority="tenant_contract",
        freshness=freshness,
    )


def test_weekend_and_public_holiday_pause_supplier_response_clock() -> None:
    expectation = evaluate_response_expectation(
        calendar=_weekday_calendar(),
        policy=ResponsePolicy(
            version="response-v2",
            acknowledgement_business_seconds=2 * 60 * 60,
            quote_business_seconds=8 * 60 * 60,
            transmit_outside_hours=True,
        ),
        submitted_at=datetime(2026, 8, 8, 0, 4, tzinfo=timezone.utc),
    )

    assert expectation["calendar_state"] == "closed"
    assert expectation["sla_clock"] == "paused"
    assert expectation["transmission_state"] == "transmit_now"
    assert expectation["next_open_at"] == "2026-08-10T23:00:00+00:00"
    assert expectation["acknowledgement_due_at"] == "2026-08-11T01:00:00+00:00"
    assert expectation["quote_due_at"] == "2026-08-11T07:00:00+00:00"
    assert expectation["calendar_version"] == "calendar-v3"
    assert expectation["policy_version"] == "response-v2"


def test_exact_closing_boundary_is_closed_and_queues_phone_contact() -> None:
    expectation = evaluate_response_expectation(
        calendar=_weekday_calendar(),
        policy=ResponsePolicy(
            version="phone-v1",
            acknowledgement_business_seconds=3600,
            quote_business_seconds=7200,
            transmit_outside_hours=False,
        ),
        submitted_at=datetime(2026, 8, 7, 7, 0, tzinfo=timezone.utc),  # 17:00 Melbourne
    )

    assert expectation["calendar_state"] == "closed"
    assert expectation["transmission_state"] == "queue_until_open"
    assert expectation["next_open_at"] == "2026-08-10T23:00:00+00:00"


def test_missing_or_stale_calendar_is_unknown_not_open() -> None:
    expectation = evaluate_response_expectation(
        calendar=_weekday_calendar(freshness="stale"),
        policy=ResponsePolicy(
            version="response-v2",
            acknowledgement_business_seconds=3600,
            quote_business_seconds=7200,
            transmit_outside_hours=True,
        ),
        submitted_at=datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc),
    )

    assert expectation["calendar_state"] == "unknown"
    assert expectation["sla_clock"] == "unknown"
    assert expectation["acknowledgement_due_at"] is None
    assert expectation["quote_due_at"] is None
    assert expectation["reason"] == "calendar_stale"


def test_dst_transition_uses_iana_timezone_not_fixed_utc_offset() -> None:
    calendar = OperationalCalendar(
        calendar_id="cal-dst",
        owner_type="supplier_facility",
        owner_ref="FAC-MEL",
        timezone_name="Australia/Melbourne",
        weekly_intervals=(OperationalInterval(weekday=0, start_local=time(9), end_local=time(17)),),
        exceptions=(),
        version="dst-v1",
        authority="tenant_contract",
        freshness="current",
    )
    expectation = evaluate_response_expectation(
        calendar=calendar,
        policy=ResponsePolicy(
            version="response-v1",
            acknowledgement_business_seconds=3600,
            quote_business_seconds=3600,
            transmit_outside_hours=False,
        ),
        submitted_at=datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc),
    )

    # DST starts in Melbourne on 4 Oct 2026. Monday 09:00 is UTC+11, not a fixed UTC+10.
    assert expectation["next_open_at"] == "2026-10-04T22:00:00+00:00"
    assert expectation["acknowledgement_due_at"] == "2026-10-04T23:00:00+00:00"
