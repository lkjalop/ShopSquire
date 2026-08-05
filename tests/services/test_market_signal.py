"""Unit tests for the market_signal envelope + ingestion (services/market_signal.py).

Covers the deck's reliability controls: schema validation, dedup (idempotent), trust gating,
freshness. Isolated in-memory SQLite.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.market_signal import MarketSignal, ingest, is_fresh, normalize
from tests.market_migration_helpers import apply_market_migration


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    apply_market_migration(s)
    try:
        yield s
    finally:
        s.close()


# ── normalize / schema validation ────────────────────────────────────────────
def test_normalize_valid():
    sig = normalize(signal_type="demand", source="search_events", payload={"q": "laptop"}, trust_score=0.8)
    assert isinstance(sig, MarketSignal)
    assert sig.signal_type == "demand" and sig.source == "search_events"
    assert sig.trust_score == 0.8 and sig.dedup_key


def test_normalize_rejects_missing_fields():
    assert normalize(signal_type="", source="x", payload={}) is None
    assert normalize(signal_type="d", source="", payload={}) is None
    assert normalize(signal_type="d", source="x", payload="not-a-dict") is None  # type: ignore[arg-type]


def test_trust_clamped_to_unit_interval():
    assert normalize(signal_type="d", source="s", payload={}, trust_score=5).trust_score == 1.0
    assert normalize(signal_type="d", source="s", payload={}, trust_score=-1).trust_score == 0.0


def test_dedup_key_deterministic_with_fields():
    a = normalize(signal_type="d", source="s", payload={"sku": "X", "n": 1}, dedup_fields=["sku"])
    b = normalize(signal_type="d", source="s", payload={"sku": "X", "n": 999}, dedup_fields=["sku"])
    assert a.dedup_key == b.dedup_key  # only the dedup field matters


# ── ingestion: idempotent + trust gate ───────────────────────────────────────
def test_ingest_idempotent(db):
    sig = normalize(signal_type="conversion", source="orders", payload={"order": "O1"}, dedup_fields=["order"])
    assert ingest(db, sig) is True
    assert ingest(db, sig) is False  # duplicate dedup_key
    db.commit()
    n = db.execute(text("SELECT COUNT(*) FROM market_signal WHERE dedup_key=:k"), {"k": sig.dedup_key}).fetchone()[0]
    assert n == 1


def test_ingest_quarantines_low_trust(db):
    sig = normalize(signal_type="d", source="unverified_feed", payload={"x": 1}, trust_score=0.2)
    assert ingest(db, sig, min_trust=0.5) is False  # below the trust floor → quarantined
    assert ingest(db, sig, min_trust=0.0) is True   # allowed when floor is open


def test_ingest_none_safe():
    assert ingest(None, None) is False


# ── freshness ────────────────────────────────────────────────────────────────
def test_is_fresh_window():
    fresh = MarketSignal("d", "s", {}, "2026-06-25T12:00:00", 1.0, "k")
    assert is_fresh(fresh, max_age_seconds=3600, now_iso="2026-06-25T12:30:00") is True
    stale = MarketSignal("d", "s", {}, "2026-06-25T00:00:00", 1.0, "k")
    assert is_fresh(stale, max_age_seconds=3600, now_iso="2026-06-25T12:30:00") is False


def test_is_fresh_tolerant_when_undated():
    undated = MarketSignal("d", "s", {}, "", 1.0, "k")
    assert is_fresh(undated, max_age_seconds=1, now_iso="2026-06-25T12:00:00") is True  # never wrongly drop


def test_ingest_drops_stale_when_enforced(db):
    stale = normalize(signal_type="d", source="s", payload={"x": 1}, occurred_at="2020-01-01T00:00:00")
    assert ingest(db, stale, max_age_seconds=3600, now_iso="2026-06-25T12:00:00") is False
    fresh = normalize(signal_type="d", source="s", payload={"x": 2}, occurred_at="2026-06-25T11:59:00")
    assert ingest(db, fresh, max_age_seconds=3600, now_iso="2026-06-25T12:00:00") is True


def test_dedup_unique_index_present(db):
    idx = db.execute(text(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_market_signal_dedup'")).fetchone()
    assert idx is not None  # race-safe dedup is enforced at the DB level
