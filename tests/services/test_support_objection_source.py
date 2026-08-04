"""Support-objection source — a REAL market source: recurring objections → objection_cluster finding."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import market_pipeline as mp
from src.app.services import support_objection_source as so


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
    assert so.record_objection(db, theme="price", raised_at="2026-06-26T01:00:00")
    so.record_objection(db, theme="price", raised_at="2026-06-26T01:00:00")  # same key
    assert db.execute(text("SELECT COUNT(*) FROM support_objection")).scalar() == 1


def test_seed_demo_idempotent(db):
    out = so.seed_demo(db)
    assert out["observations"] == 5
    so.seed_demo(db)
    assert db.execute(text("SELECT COUNT(*) FROM support_objection")).scalar() == 5


def test_live_objection_cluster_surfaces_as_finding(db):
    so.seed_demo(db)  # 4× 'price' → a cluster
    db.commit()
    out = mp.run_pipeline(db, anomaly_fn=_calm)
    assert out["ingested"] >= 4
    findings = mp.state(db)["findings"]
    price = [f for f in findings if f["type"] == "objection_cluster" and f["entity_ref"] == "price"]
    assert len(price) == 1


def test_below_threshold_no_finding(db):
    so.record_objection(db, theme="rare", raised_at="2026-06-26T01:00:00")  # single → no cluster
    db.commit()
    mp.run_pipeline(db, anomaly_fn=_calm)
    assert not any(f["type"] == "objection_cluster" for f in mp.state(db)["findings"])
