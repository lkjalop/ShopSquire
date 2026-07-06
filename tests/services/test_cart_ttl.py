"""Cart age / TTL classifier — pure time arithmetic, deterministic via injected `now`."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.app.services import cart_ttl


NOW = datetime(2026, 7, 6, 12, 0, 0)


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).strftime("%Y-%m-%d %H:%M:%S")


# ---- parse_timestamp ---------------------------------------------------------

@pytest.mark.parametrize("value", [
    "2026-07-06 08:00:00",        # SQLite CURRENT_TIMESTAMP
    "2026-07-06T08:00:00",        # ISO with T
    "2026-07-06T08:00:00.123456", # ISO with microseconds
    "2026-07-06T08:00:00Z",       # Zulu
    "2026-07-06 08:00:00+00:00",  # tz offset
])
def test_parse_timestamp_formats(value):
    dt = cart_ttl.parse_timestamp(value)
    # normalize sub-second precision — microseconds are preserved when present but irrelevant to idle age
    assert dt.replace(microsecond=0) == datetime(2026, 7, 6, 8, 0, 0)


def test_parse_timestamp_tz_normalized_to_utc():
    # +10:00 local 18:00 == 08:00 UTC (naive)
    assert cart_ttl.parse_timestamp("2026-07-06T18:00:00+10:00") == datetime(2026, 7, 6, 8, 0, 0)


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-date", "garbage"])
def test_parse_timestamp_unparseable_is_none(value):
    assert cart_ttl.parse_timestamp(value) is None


# ---- idle_seconds ------------------------------------------------------------

def test_idle_seconds_basic():
    assert cart_ttl.idle_seconds(_ago(hours=4), now=NOW) == pytest.approx(4 * 3600)


def test_idle_seconds_missing_is_none():
    assert cart_ttl.idle_seconds(None, now=NOW) is None


def test_idle_seconds_future_clamped_to_zero():
    future = (NOW + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    assert cart_ttl.idle_seconds(future, now=NOW) == 0.0


# ---- classify_cart_age -------------------------------------------------------

def test_fresh_under_1h_not_carried_no_nag():
    a = cart_ttl.classify_cart_age(20 * 60, now=NOW)   # 20 min
    assert a["tier"] == "fresh"
    assert a["is_carried"] is False
    assert a["suggest_clear"] is False


def test_warm_1h_to_8h_carried_but_no_forced_clear():
    a = cart_ttl.classify_cart_age(4 * 3600, now=NOW)  # 4h — the demo case
    assert a["tier"] == "warm"
    assert a["is_carried"] is True
    assert a["suggest_clear"] is False
    assert "hour" in a["label"]


def test_stale_over_8h_suggests_clear():
    a = cart_ttl.classify_cart_age(30 * 3600, now=NOW)  # 30h
    assert a["tier"] == "stale"
    assert a["is_carried"] is True
    assert a["suggest_clear"] is True


def test_unknown_age_conservative():
    a = cart_ttl.classify_cart_age(None, now=NOW)
    assert a["tier"] == "unknown"
    assert a["is_carried"] is False
    assert a["suggest_clear"] is False
    assert a["label"] == ""


def test_boundary_exactly_1h_is_warm_not_fresh():
    # fresh is strictly < 3600; exactly 3600 tips into warm
    assert cart_ttl.classify_cart_age(3600, now=NOW)["tier"] == "warm"


def test_boundary_exactly_8h_is_stale():
    assert cart_ttl.classify_cart_age(28800, now=NOW)["tier"] == "stale"


# ---- humanize_idle -----------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (10, "just now"),
    (30 * 60, "~30 min ago"),
    (3600, "~1 hour ago"),
    (4 * 3600, "~4 hours ago"),
    (26 * 3600, "yesterday"),
    (3 * 86400, "~3 days ago"),
])
def test_humanize_idle(seconds, expected):
    assert cart_ttl.humanize_idle(seconds) == expected


def test_humanize_idle_none():
    assert cart_ttl.humanize_idle(None) == ""


# ---- classify_updated_at (end-to-end from a raw timestamp) -------------------

def test_classify_updated_at_roundtrip():
    a = cart_ttl.classify_updated_at(_ago(hours=4), now=NOW)
    assert a["tier"] == "warm"
    assert a["label"] == "~4 hours ago"
