"""Market pipeline — the REAL ingestion → analysis → findings path (default tenant, replay-clean)."""
from __future__ import annotations

from datetime import date, timedelta
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
    s.execute(text(
        "CREATE TABLE orders (id TEXT, total_cents INTEGER, status TEXT, created_at TEXT, "
        "updated_at TEXT, tenant_id TEXT)"))
    # search_events must carry the columns the backfill SELECTs (id, query, result_count, event_time,
    # uid_hash, session_id) — the adapter was extended with uid_hash/session_id and this minimal fixture
    # wasn't, so the SELECT errored and 0 rows ingested (the real cause of the 0-findings, not date rot).
    s.execute(text("CREATE TABLE search_events (id TEXT, event_time TEXT, query TEXT, result_count INTEGER, "
                   "uid_hash TEXT, session_id TEXT, tenant_id TEXT)"))
    attribution.ensure_tables(s)
    # a demand spike across days + a zero-result catalog gap → real findings. Dates are RELATIVE to today
    # (last 5 days, oldest first; spike on the newest) so the fixture never ages out of the pipeline's
    # recency window — the hardcoded 2026-06 dates rotted and ingested 0 search_events → 0 findings.
    days = [(date.today() - timedelta(days=4 - i)).isoformat() for i in range(5)]
    for i, day in enumerate(days):
        n = 2 if i < 4 else 20
        for j in range(n):
            # distinct uid_hash per searcher — detect_inventory_demand_mismatch gates on DISTINCT users
            # (anti-flood), so anonymous zero-result rows never manufacture the catalog-gap finding.
            s.execute(text("INSERT INTO search_events "
                           "(id, query, result_count, event_time, uid_hash, tenant_id) "
                           "VALUES (:id,'widget',0,:t,:u,'default')"),
                      {"id": f"{day}-{j}", "t": f"{day}T10:00:00", "u": f"u{j}"})
    s.execute(text(
        "INSERT INTO orders (id,total_cents,status,created_at,updated_at,tenant_id) "
        "VALUES ('O1',119900,'paid',:d,:d,'default')"), {"d": days[-1]})
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
