"""Source adapters (orders/conversion/search → market_signal) + idempotent backfill."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import attribution
from src.app.services.market_signal_adapters import (
    backfill_from_db,
    from_conversion,
    from_order,
    from_search,
)


# ── pure mappers ─────────────────────────────────────────────────────────────
def test_from_order_maps_envelope():
    sig = from_order({"id": "O1", "total_cents": 119900, "status": "paid", "created_at": "2026-06-25"})
    assert sig and sig.signal_type == "order" and sig.source == "orders"
    assert sig.payload["order_id"] == "O1" and sig.trust_score == 1.0


def test_from_conversion_high_trust():
    sig = from_conversion({"order_id": "O1", "decision_id": "D1", "value_cents": 119900, "converted_at": "2026-06-25"})
    assert sig and sig.signal_type == "conversion" and sig.trust_score == 1.0


def test_from_search_demand_lower_trust():
    sig = from_search({"id": "S1", "query": "laptop", "result_count": 5, "event_time": "2026-06-25"})
    assert sig and sig.signal_type == "demand" and sig.source == "search_events"
    assert sig.trust_score == 0.8


def test_mappers_reject_missing_id():
    assert from_order({"total_cents": 1}) is None
    assert from_conversion({"decision_id": "D"}) is None
    assert from_search({"query": "x"}) is None


# ── backfill (idempotent) ────────────────────────────────────────────────────
@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    s.execute(text("CREATE TABLE orders (id TEXT, total_cents INTEGER, status TEXT, created_at TEXT)"))
    s.execute(text("CREATE TABLE search_events (id TEXT, event_time TEXT, uid_hash TEXT, query TEXT, "
                   "filters_json TEXT, result_skus_json TEXT, result_count INTEGER, view_mode TEXT, "
                   "trace_id TEXT, session_id TEXT)"))
    attribution.ensure_tables(s)
    s.execute(text("INSERT INTO orders VALUES ('O1',119900,'paid','2026-06-25')"))
    s.execute(text("INSERT INTO search_events (id, query, result_count, event_time) VALUES ('S1','laptop',5,'2026-06-25')"))
    s.execute(text("INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, attributed_skus_json, "
                   "value_cents, converted_at) VALUES ('c1','D1','O1','u','[\"GAM-1\"]',119900,'2026-06-25')"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_backfill_ingests_all_sources(db):
    counts = backfill_from_db(db)
    assert counts["orders"] == 1 and counts["conversion_event"] == 1 and counts["search_events"] == 1
    total = db.execute(text("SELECT COUNT(*) FROM market_signal")).fetchone()[0]
    assert total == 3
    # one of each signal_type present
    types = {r[0] for r in db.execute(text("SELECT DISTINCT signal_type FROM market_signal")).fetchall()}
    assert {"order", "conversion", "demand"} <= types


def test_backfill_is_idempotent(db):
    backfill_from_db(db)
    second = backfill_from_db(db)
    assert all(v == 0 for v in second.values())  # dedup → nothing new on re-run
    assert db.execute(text("SELECT COUNT(*) FROM market_signal")).fetchone()[0] == 3


def test_backfill_source_filter(db):
    counts = backfill_from_db(db, sources=["orders"])
    assert counts == {"orders": 1}
    assert db.execute(text("SELECT COUNT(*) FROM market_signal")).fetchone()[0] == 1


def test_backfill_none_db_safe():
    assert backfill_from_db(None) == {}
