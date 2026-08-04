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


# ── §6 coarsened network fingerprint (non-PII: {asn, country, risk_tier}, never the IP) ───────
def test_coarsen_network_is_non_pii_and_tiers_risk():
    # a plain residential visit → low risk, ASN + country kept, NO ip field anywhere
    c = ts._coarsen_network({"asn": 4764, "country": "au", "is_hosting": False, "is_vpn": False, "is_tor": False})
    assert c == {"risk_tier": "low", "asn": 4764, "country": "AU"}
    # datacenter/VPN → medium; Tor → high
    assert ts._coarsen_network({"asn": 14618, "country": "US", "is_hosting": True})["risk_tier"] == "medium"
    assert ts._coarsen_network({"asn": 1, "country": "US", "is_tor": True})["risk_tier"] == "high"
    # unknown country (ZZ) and a 0/None ASN are dropped, never faked
    c2 = ts._coarsen_network({"asn": 0, "country": "ZZ", "is_vpn": True})
    assert c2 == {"risk_tier": "medium"} and "ip" not in c2
    assert ts._coarsen_network(None) is None and ts._coarsen_network({}) is None


def test_network_breakdown_aggregates_by_country_asn_risk(db):
    ts.capture(db, session_hash="n1", properties={"utm_source": "google"}, action="view",
               network={"asn": 4764, "country": "AU", "risk_tier": "low"})
    ts.capture(db, session_hash="n2", properties={"utm_source": "google"}, action="view",
               network={"asn": 4764, "country": "AU", "risk_tier": "low"})
    # a datacenter visitor (bot-suspect) from the same ASN — counted as a visit, NOT verified-human
    ts.capture(db, session_hash="n3", properties={"utm_source": "google"}, action="view", bot_suspect=True,
               network={"asn": 14618, "country": "US", "risk_tier": "medium"})
    nb = ts.network_breakdown(db)
    au = next(r for r in nb["by_country"] if r["country"] == "AU")
    assert au["visits"] == 2 and au["verified_human_visits"] == 2
    us = next(r for r in nb["by_country"] if r["country"] == "US")
    assert us["visits"] == 1 and us["verified_human_visits"] == 0   # datacenter visit is not verified-human
    assert any(r["asn"] == 4764 and r["visits"] == 2 for r in nb["by_asn"])
    tiers = {r["risk_tier"]: r["visits"] for r in nb["by_risk_tier"]}
    assert tiers.get("low") == 2 and tiers.get("medium") == 1
    assert nb["coverage"]["with_network"] == 3 and nb["coverage"]["coverage_ratio"] == 1.0


def test_capture_without_network_carries_no_fingerprint(db):
    # a visit with no network enrichment must not fabricate a net block — coverage stays 0
    ts.capture(db, session_hash="p1", properties={"utm_source": "google"}, action="view")
    nb = ts.network_breakdown(db)
    assert nb["coverage"]["with_network"] == 0 and nb["by_country"] == []
