"""Market pipeline — the REAL ingestion → analysis → findings path (default tenant, replay-clean)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import attribution
from src.app.services import market_pipeline as mp


def _anom(is_anom, conf=0.95, sev="warn", z=3.0):
    return SimpleNamespace(is_anomaly=is_anom, confidence=conf, severity=sev, z_score=z)


def _flag_last_outlier(series, domain):
    rest = series[:-1] or [0.0]
    base = sum(rest) / len(rest) if rest else 0.0
    last = series[-1]
    return [_anom(base > 0 and (last > base * 1.5 or last < base * 0.5))]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    # real source tables the backfill reads
    s.execute(text("CREATE TABLE orders (id TEXT, total_cents INTEGER, status TEXT, created_at TEXT)"))
    s.execute(text("CREATE TABLE search_events (id TEXT, event_time TEXT, query TEXT, result_count INTEGER)"))
    attribution.ensure_tables(s)
    # a demand spike across days + a zero-result catalog gap → real findings
    for i, day in enumerate(["2026-06-20", "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-24"]):
        n = 2 if i < 4 else 20
        for j in range(n):
            s.execute(text("INSERT INTO search_events (id, query, result_count, event_time) "
                           "VALUES (:id,'widget',0,:t)"), {"id": f"{day}-{j}", "t": f"{day}T10:00:00"})
    s.execute(text("INSERT INTO orders VALUES ('O1',119900,'paid','2026-06-24')"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_pipeline_ingests_real_rows_and_persists_findings(db):
    out = mp.run_pipeline(db, anomaly_fn=_flag_last_outlier)
    assert out["ingested"] > 0                       # real search + order rows ingested
    assert out["findings"] >= 1 and out["persisted"] >= 1
    st = mp.state(db)
    types = {f["type"] for f in st["findings"]}
    assert "inventory_demand_mismatch" in types       # zero-result demand surfaced from REAL data
    assert st["label"] == "LIVE" and st["signals"] > 0


def test_pipeline_is_idempotent_on_reingest(db):
    first = mp.run_pipeline(db, anomaly_fn=_flag_last_outlier)
    second = mp.run_pipeline(db, anomaly_fn=_flag_last_outlier)
    assert second["ingested"] == 0                    # dedup → nothing new on re-run
    assert first["persisted"] >= 1


def test_pipeline_excludes_replay_tenant(db):
    # a replay-demo signal must NOT leak into the real (default) findings
    from src.app.services import market_signal as ms
    ms.ingest(db, ms.normalize(signal_type="demand", source="search_events",
                               payload={"event_id": "rp-1", "query": "replayonly", "result_count": 0},
                               occurred_at="2026-06-24T10:00:00", dedup_fields=["event_id"],
                               tenant_id="replay-demo"))
    db.commit()
    mp.run_pipeline(db, anomaly_fn=_flag_last_outlier)
    st = mp.state(db)  # default tenant only
    assert all(f.get("entity_ref") != "replayonly" for f in st["findings"])


def test_pipeline_none_db_safe():
    assert mp.run_pipeline(None)["ingested"] == 0
    assert mp.state(None)["active_findings"] == 0
