"""Funnel source — a REAL market source: cart-funnel drop-off → funnel_dropoff finding via the pipeline."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import funnel_source as fs
from src.app.services import market_pipeline as mp


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _calm(series, domain):
    return [SimpleNamespace(is_anomaly=False, confidence=0.5, severity="info", z_score=0.0)]


def test_record_is_idempotent(db):
    assert fs.record_event(db, stage="payment", entered=60, abandoned=42, observed_at="2026-06-26T08:00:00")
    fs.record_event(db, stage="payment", entered=60, abandoned=42, observed_at="2026-06-26T08:00:00")
    assert db.execute(text("SELECT COUNT(*) FROM cart_funnel_event")).scalar() == 1


def test_seed_demo_idempotent(db):
    out = fs.seed_demo(db)
    assert out["events"] == 2
    fs.seed_demo(db)
    assert db.execute(text("SELECT COUNT(*) FROM cart_funnel_event")).scalar() == 2


def test_live_funnel_dropoff_surfaces_as_finding(db):
    fs.seed_demo(db)  # payment 42/60 → 70% drop-off
    db.commit()
    out = mp.run_pipeline(db, anomaly_fn=_calm)
    assert out["ingested"] >= 2
    findings = mp.state(db)["findings"]
    pay = [f for f in findings if f["type"] == "funnel_dropoff" and f["entity_ref"] == "payment"]
    assert len(pay) == 1
    # the healthy cart stage (20/100) is NOT flagged
    assert not any(f["entity_ref"] == "cart" for f in findings if f["type"] == "funnel_dropoff")
