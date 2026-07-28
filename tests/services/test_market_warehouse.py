"""Module-2 warehouse sink: raw market signals are rolled into a durable daily (type, source) depth
aggregate; retention prunes the raw log past a day window while the depth SURVIVES in the rollup."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import market_signal as ms
from src.app.services import market_warehouse as mw


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    ms.ensure_table(s)
    try:
        yield s
    finally:
        s.close()


def _ins(db, stype, src, trust, ts):
    db.execute(text(
        "INSERT INTO market_signal (id,tenant_id,signal_type,source,dedup_key,trust_score,payload_json,"
        "occurred_at,ingested_at) VALUES (:i,'default',:t,:s,:d,:tr,'{}',:o,:g)"),
        {"i": str(uuid.uuid4()), "t": stype, "s": src, "d": str(uuid.uuid4()), "tr": trust, "o": ts, "g": ts})


def test_roll_up_aggregates_by_day_type_source(db):
    _ins(db, "demand", "orders", 0.9, "2026-06-25 10:00:00")
    _ins(db, "demand", "orders", 0.7, "2026-06-25 11:00:00")
    _ins(db, "competitor", "price", 0.8, "2026-06-26 09:00:00")
    db.commit()
    assert mw.roll_up(db, tenant_id="default") == 2  # two distinct (day,type,source) buckets
    db.commit()
    depth = {(d["bucket_date"], d["signal_type"]): d for d in mw.query_depth(db, tenant_id="default", now_iso="2026-06-27 00:00:00")}
    dem = depth[("2026-06-25", "demand")]
    assert dem["signal_count"] == 2 and abs(dem["trust_avg"] - 0.8) < 1e-9
    assert depth[("2026-06-26", "competitor")]["signal_count"] == 1


def test_roll_up_is_idempotent(db):
    _ins(db, "demand", "orders", 0.5, "2026-06-25 10:00:00")
    db.commit()
    mw.roll_up(db, tenant_id="default"); db.commit()
    _ins(db, "demand", "orders", 0.9, "2026-06-25 12:00:00")  # same bucket, new signal
    db.commit()
    mw.roll_up(db, tenant_id="default"); db.commit()  # re-run: bucket UPDATED, not duplicated
    rows = db.execute(text("SELECT count(*), max(signal_count) FROM market_signal_rollup")).fetchone()
    assert rows[0] == 1 and rows[1] == 2  # one bucket row, count now 2


def test_prune_keeps_window_and_depth_survives(db):
    _ins(db, "demand", "orders", 0.9, "2026-06-25 10:00:00")
    _ins(db, "demand", "orders", 0.7, "2026-06-25 11:00:00")
    _ins(db, "competitor", "price", 0.8, "2026-06-26 09:00:00")
    db.commit()
    mw.roll_up(db, tenant_id="default"); db.commit()
    pruned = mw.prune_signals(db, older_than_days=1, tenant_id="default", now_iso="2026-06-27 00:00:00")
    db.commit()
    assert pruned == 2  # the two 06-25 rows; the in-window 06-26 row stays
    assert db.execute(text("SELECT count(*) FROM market_signal")).scalar() == 1
    assert len(mw.query_depth(db, tenant_id="default", now_iso="2026-06-27 00:00:00")) == 2  # depth survives prune


def test_prune_is_noop_for_zero_or_negative_window(db):
    _ins(db, "demand", "orders", 0.9, "2026-06-01 10:00:00")
    db.commit()
    assert mw.prune_signals(db, older_than_days=0, tenant_id="default", now_iso="2026-06-27 00:00:00") == 0
    assert mw.prune_signals(db, older_than_days=-5, tenant_id="default", now_iso="2026-06-27 00:00:00") == 0
    assert db.execute(text("SELECT count(*) FROM market_signal")).scalar() == 1  # nothing deleted


def test_query_depth_filters_by_type_and_window(db):
    _ins(db, "demand", "orders", 0.9, "2026-06-26 10:00:00")
    _ins(db, "competitor", "price", 0.8, "2026-06-26 10:00:00")
    _ins(db, "demand", "orders", 0.9, "2026-01-01 10:00:00")  # outside a 30-day window
    db.commit()
    mw.roll_up(db, tenant_id="default"); db.commit()
    only_demand = mw.query_depth(db, tenant_id="default", signal_type="demand", now_iso="2026-06-27 00:00:00", days=30)
    assert {d["signal_type"] for d in only_demand} == {"demand"}
    assert all(d["bucket_date"] >= "2026-05-28" for d in only_demand)  # Jan row excluded by the 30-day window


def test_sink_and_retain_rolls_then_prunes(db):
    _ins(db, "demand", "orders", 0.9, "2026-06-20 10:00:00")
    _ins(db, "demand", "orders", 0.9, "2026-06-26 10:00:00")
    db.commit()
    out = mw.sink_and_retain(db, tenant_id="default", retention_days=2, now_iso="2026-06-27 00:00:00")
    db.commit()
    assert out["rolled_up"] == 2 and out["pruned"] == 1  # rolled both days, pruned the 06-20 row
    assert db.execute(text("SELECT count(*) FROM market_signal")).scalar() == 1


def test_run_pipeline_reports_rolled_up_key():
    # the warehouse step is wired into the real pipeline (rollup runs; retention env-gated, default off)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    db = sessionmaker(bind=eng, future=True)()
    ms.ensure_table(db)
    from datetime import datetime, timezone
    current_day = datetime.now(timezone.utc).date().isoformat()
    _ins(db, "demand", "orders", 0.9, f"{current_day} 10:00:00")
    db.commit()
    from src.app.services import market_pipeline as mp
    res = mp.run_pipeline(db, anomaly_fn=lambda *a, **k: None)
    assert "rolled_up" in res and "pruned" in res
    assert res["rolled_up"] >= 1 and res["pruned"] == 0  # default: no retention pruning
    # the operator state view consumes the warehouse depth (written above)
    st = mp.state(db)
    assert "depth" in st and st["depth_buckets"] >= 1
    db.close()
