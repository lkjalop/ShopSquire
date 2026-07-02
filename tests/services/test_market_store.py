"""Market Intelligence Store (deck Module 2): trend_indicator / competitor_snapshot / offer_policy +
the M3→M2 persist path. Agnostic core — opaque entity_ref, numbers, enums; no product vocab."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import market_store as ms
from src.app.services.market_analysis import MarketFinding, FINDING_DEMAND_SHIFT, FINDING_COMPETITOR_UNDERCUT


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_record_and_read_trend_indicator(db):
    assert ms.record_trend_indicator(db, entity_ref="laptops", indicator_type="demand", direction="spike",
                                     value=120.0, baseline=80.0, confidence=0.9, observed_at="2026-07-01T09:00:00")
    rows = ms.list_trend_indicators(db, entity_ref="laptops")
    assert len(rows) == 1 and rows[0]["direction"] == "spike" and rows[0]["value"] == 120.0


def test_record_competitor_snapshot_and_offer_policy(db):
    assert ms.record_competitor_snapshot(db, entity_ref="GAM-1", our_price_cents=199900,
                                         competitor_price_cents=189900, competitor="acme")
    cs = ms.list_competitor_snapshots(db, entity_ref="GAM-1")
    assert cs and cs[0]["competitor_price_cents"] == 189900 and cs[0]["competitor"] == "acme"
    assert ms.record_offer_policy(db, entity_ref="GAM-1", action="increase", discount_pct=0.10,
                                  floor_margin_pct=0.10, rationale="surplus + soft demand", decided_at="2026-07-01")
    op = ms.list_offer_policies(db, entity_ref="GAM-1")
    assert op and op[0]["action"] == "increase" and op[0]["discount_pct"] == 0.10


def test_ordered_history_dual_mode(db):
    for i, v in enumerate([80.0, 100.0, 130.0]):
        ms.record_trend_indicator(db, entity_ref="cat", indicator_type="demand", direction="spike",
                                  value=v, observed_at=f"2026-07-0{i+1}T00:00:00")
    rows = ms.list_trend_indicators(db, entity_ref="cat")
    assert [r["value"] for r in rows] == [130.0, 100.0, 80.0]   # newest first (historical read)


def test_persist_findings_maps_m3_to_m2(db):
    findings = [
        MarketFinding(FINDING_DEMAND_SHIFT, "laptops", "critical", 0.9, "demand spike",
                      {"direction": "spike", "latest": 140, "baseline": 90}, "recent"),
        MarketFinding(FINDING_COMPETITOR_UNDERCUT, "GAM-1", "warn", 0.7, "undercut",
                      {"our_price_cents": 199900, "competitor_price_cents": 179900, "competitor": "acme"}, "recent"),
    ]
    counts = ms.persist_history(db, findings, observed_at="2026-07-01T10:00:00")
    assert counts == {"trends": 1, "competitors": 1}
    assert ms.list_trend_indicators(db, entity_ref="laptops")[0]["value"] == 140.0
    assert ms.list_competitor_snapshots(db, entity_ref="GAM-1")[0]["competitor"] == "acme"


def test_writers_are_best_effort_on_bad_db():
    # None db never raises — returns False (ingest must never break on a store failure)
    assert ms.record_trend_indicator(None, entity_ref="x", indicator_type="demand", direction="spike") is False
    assert ms.persist_history(None, [MarketFinding(FINDING_DEMAND_SHIFT, "x", "warn", 0.5, "s",
                               {"direction": "spike"}, "recent")]) == {"trends": 0, "competitors": 0}
