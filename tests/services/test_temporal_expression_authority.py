from datetime import datetime, timezone

from src.app.services.temporal_expression_authority import resolve_temporal_expression


def test_relative_duration_resolves_on_buyers_timezone_timeline() -> None:
    result = resolve_temporal_expression(
        "within four days",
        timezone_name="Australia/Sydney",
        interpretation_instant=datetime(2026, 8, 16, 2, 0, tzinfo=timezone.utc),
    )

    assert result.status == "resolved"
    assert result.resolved_utc_instant == "2026-08-20T02:00:00+00:00"
    assert result.interpretation_instant == "2026-08-16T02:00:00+00:00"
    assert result.calendar_source == "iana_tzdb"
    assert "Australia/Sydney" in result.calendar_version
    assert result.confidence == 1.0
    assert result.unresolved_reason is None


def test_relative_duration_observes_daylight_saving_transition() -> None:
    result = resolve_temporal_expression(
        "within 2 days",
        timezone_name="Australia/Sydney",
        interpretation_instant="2026-10-03T02:00:00+00:00",
    )

    # Noon local on 3 October becomes noon daylight time on 5 October.
    assert result.resolved_utc_instant == "2026-10-05T01:00:00+00:00"


def test_relative_weekday_fails_closed_with_one_clarification() -> None:
    result = resolve_temporal_expression(
        "next Thursday",
        timezone_name="Australia/Sydney",
        interpretation_instant="2026-08-16T02:00:00+00:00",
    )

    assert result.status == "ambiguous"
    assert result.resolved_utc_instant is None
    assert result.confidence == 0.0
    assert result.unresolved_reason == (
        "relative_weekday_requires_date_and_time_confirmation"
    )
    assert result.clarification_question


def test_explicit_instant_without_timezone_fails_closed() -> None:
    result = resolve_temporal_expression(
        "2026-08-20T17:00:00",
        timezone_name="Australia/Sydney",
        interpretation_instant="2026-08-16T02:00:00+00:00",
    )

    assert result.status == "ambiguous"
    assert result.unresolved_reason == "explicit_instant_missing_timezone"
    assert result.resolved_utc_instant is None
