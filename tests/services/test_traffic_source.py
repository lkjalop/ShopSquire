"""Traffic-source attribution — the marketing-BI foundation (utm/referrer → channel → per-channel BI)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import traffic_source as ts


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# ── canonicalisation (pure) ──────────────────────────────────────────────────
def test_canonical_channel_priority():
    assert ts.canonical_channel(utm_source="Google", utm_medium="CPC") == "google/cpc"
    assert ts.canonical_channel(utm_source="newsletter") == "newsletter"
    assert ts.canonical_channel(gclid="abc123") == "paid:google"
    assert ts.canonical_channel(fbclid="xyz") == "paid:meta"
    assert ts.canonical_channel(referrer="https://www.reddit.com/r/x") == "referral:reddit.com"
    assert ts.canonical_channel() == "direct"
    # explicit UTM wins over a referrer
    assert ts.canonical_channel(utm_source="klaviyo", utm_medium="email",
                                referrer="https://mail.google.com") == "klaviyo/email"


def test_parse_from_properties_flat_and_nested():
    flat = ts.parse_from_properties({"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "spring"})
    assert flat["channel"] == "google/cpc" and flat["utm_campaign"] == "spring"
    nested = ts.parse_from_properties({"utm": {"source": "meta", "medium": "paid"}})
    assert nested["channel"] == "meta/paid"
    assert ts.parse_from_properties({})["channel"] == "direct"


# ── capture → signals → BI ───────────────────────────────────────────────────
def test_capture_records_first_touch_and_emits_signals(db):
    # a visit from google/cpc
    r1 = ts.capture(db, session_hash="sess-1", properties={"utm_source": "google", "utm_medium": "cpc"},
                    action="page_view", occurred_at="2026-07-01T09:00:00")
    assert r1["channel"] == "google/cpc" and r1["emitted"] == "demand"
    # the SAME session returns direct and converts → attributed to the FIRST-touch channel (google/cpc)
    r2 = ts.capture(db, session_hash="sess-1", properties={}, action="purchase",
                    occurred_at="2026-07-01T09:05:00")
    assert r2["channel"] == "google/cpc" and r2["emitted"] == "conversion"   # first-touch, not 'direct'


def test_channel_breakdown_computes_conversion_rate(db):
    # google/cpc: 2 sessions, 1 converts; direct: 1 session, 0 convert
    ts.capture(db, session_hash="g1", properties={"utm_source": "google", "utm_medium": "cpc"}, action="view")
    ts.capture(db, session_hash="g1", properties={}, action="purchase")
    ts.capture(db, session_hash="g2", properties={"utm_source": "google", "utm_medium": "cpc"}, action="view")
    ts.capture(db, session_hash="d1", properties={}, action="view")
    bd = ts.channel_breakdown(db)
    by = {c["channel"]: c for c in bd["channels"]}
    assert by["google/cpc"]["visits"] == 2 and by["google/cpc"]["conversions"] == 1
    assert by["google/cpc"]["conversion_rate"] == 0.5
    assert by["direct"]["visits"] == 1 and by["direct"]["conversions"] == 0


def test_capture_is_safe_without_session(db):
    assert ts.capture(db, session_hash=None, properties={"utm_source": "x"}, action="view")["channel"] is None


def test_verified_human_visits_excludes_bot_suspect(db):
    # 2 human visits + 1 datacenter/VPN visit (bot-suspect) from the same channel
    ts.capture(db, session_hash="h1", properties={"utm_source": "google"}, action="view", bot_suspect=False)
    ts.capture(db, session_hash="h2", properties={"utm_source": "google"}, action="view", bot_suspect=False)
    ts.capture(db, session_hash="b1", properties={"utm_source": "google"}, action="view", bot_suspect=True)
    bd = ts.channel_breakdown(db)
    s = bd["summary"]
    assert s["total_visits"] == 3 and s["verified_human_visits"] == 2 and s["bot_suspect_visits"] == 1
    assert s["human_ratio"] == round(2 / 3, 4)
    g = next(c for c in bd["channels"] if c["channel"] == "google")
    assert g["visits"] == 3 and g["verified_human_visits"] == 2
