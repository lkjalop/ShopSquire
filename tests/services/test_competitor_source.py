"""Competitor source — a REAL market source: rival observation ⋈ our price_book → undercut finding."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import commerce_catalog as cc
from src.app.services import competitor_source as cs
from src.app.services import market_pipeline as mp


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_record_is_idempotent(db):
    assert cs.record_observation(db, sku="LAP-021", competitor_price_cents=99900,
                                 competitor="rival.example", observed_at="2026-06-26T09:00:00")
    cs.record_observation(db, sku="LAP-021", competitor_price_cents=99900,
                          competitor="rival.example", observed_at="2026-06-26T09:00:00")  # same key
    n = db.execute(text("SELECT COUNT(*) FROM competitor_observation")).scalar()
    assert n == 1


def test_seed_demo(db):
    out = cs.seed_demo(db)
    assert out["observations"] == 1
    cs.seed_demo(db)  # idempotent
    assert db.execute(text("SELECT COUNT(*) FROM competitor_observation")).scalar() == 1


def _flag_last_outlier(series, domain):
    return [SimpleNamespace(is_anomaly=False, confidence=0.5, severity="info", z_score=0.0)]


def test_live_competitor_undercut_surfaces_as_finding(db):
    # our retail (price_book) 1200.00, rival 999.00 → ~17% undercut → a critical finding from REAL data
    cc.upsert_price(db, sku="LAP-021", list_cents=120000, channel="default", currency="AUD", source="seed")
    cs.seed_demo(db)
    db.commit()
    out = mp.run_pipeline(db, anomaly_fn=_flag_last_outlier)
    assert out["ingested"] >= 1
    types = {f["type"] for f in mp.state(db)["findings"]}
    assert "competitor_undercut" in types


def test_no_finding_without_our_price(db):
    # rival observation but no price_book entry → can't compute an undercut → no finding (honest)
    cs.seed_demo(db)
    db.commit()
    mp.run_pipeline(db, anomaly_fn=_flag_last_outlier)
    types = {f["type"] for f in mp.state(db)["findings"]}
    assert "competitor_undercut" not in types
