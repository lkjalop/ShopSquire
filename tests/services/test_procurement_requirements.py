from datetime import date

from src.app.services.procurement_requirements import explicit_needed_by


def test_explicit_named_month_and_iso_dates_are_normalized():
    today = date(2026, 7, 20)
    assert explicit_needed_by("required by 15 August 2026", today=today) == "2026-08-15"
    assert explicit_needed_by("deliver before August 21st, 2026", today=today) == "2026-08-21"
    assert explicit_needed_by("needed 2026-09-03", today=today) == "2026-09-03"


def test_ambiguous_or_past_dates_require_clarification():
    today = date(2026, 7, 20)
    assert explicit_needed_by("needed by 08/09/2026", today=today) is None
    assert explicit_needed_by("needed by 15 June 2026", today=today) is None
    assert explicit_needed_by("needed sometime next month", today=today) is None
