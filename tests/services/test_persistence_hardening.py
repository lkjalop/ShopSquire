"""S1 hardening — tenant isolation, schema version, dedup/supersede lifecycle, correction, freshness.

These guard the deck's thesis that bad/stale/duplicated input must not drive autonomous behaviour:
signals dedup per-tenant and can be freshness-gated; findings supersede (not accumulate) on re-run,
are tenant-scoped, and a human correction is never silently overwritten by a later batch run.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import market_signal as ms
from src.app.services.market_analysis import (
    MarketFinding,
    correct_finding,
    load_recent_findings,
    persist_findings,
)
from src.app.services.market_signal_adapters import backfill_from_db


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# ── signals ──────────────────────────────────────────────────────────────────
def test_signal_dedup_is_per_tenant(db):
    payload = {"order_id": "O1"}
    a = ms.normalize(signal_type="order", source="orders", payload=payload, dedup_fields=["order_id"], tenant_id="t-a")
    b = ms.normalize(signal_type="order", source="orders", payload=payload, dedup_fields=["order_id"], tenant_id="t-b")
    a2 = ms.normalize(signal_type="order", source="orders", payload=payload, dedup_fields=["order_id"], tenant_id="t-a")
    assert ms.ingest(db, a) is True
    assert ms.ingest(db, b) is True   # same payload, DIFFERENT tenant → not a duplicate
    assert ms.ingest(db, a2) is False  # same tenant + payload → deduped
    rows = db.execute(text("SELECT tenant_id, schema_version FROM market_signal ORDER BY tenant_id")).fetchall()
    assert [r[0] for r in rows] == ["t-a", "t-b"]
    assert all(r[1] == ms.SCHEMA_VERSION for r in rows)  # version stamped


def test_backfill_freshness_gate_drops_stale_order(db):
    db.execute(text("CREATE TABLE orders (id TEXT, total_cents INTEGER, status TEXT, created_at TEXT, "
                    "tenant_id TEXT DEFAULT 'default')"))
    db.execute(text("INSERT INTO orders (id,total_cents,status,created_at) "
                    "VALUES ('O-fresh', 100, 'paid', '2026-06-25 12:00:00')"))
    db.execute(text("INSERT INTO orders (id,total_cents,status,created_at) "
                    "VALUES ('O-stale', 100, 'paid', '2020-01-01 00:00:00')"))
    db.commit()
    counts = backfill_from_db(db, sources=["orders"], max_age_seconds=86400, now_iso="2026-06-25 12:30:00")
    assert counts["orders"] == 1  # only the fresh order survives the freshness gate
    kept = db.execute(text("SELECT payload_json FROM market_signal")).fetchall()
    assert any("O-fresh" in r[0] for r in kept) and not any("O-stale" in r[0] for r in kept)


# ── findings ─────────────────────────────────────────────────────────────────
def _f(entity="q1", sev="warn", conf=0.7, summ="s", window="daily"):
    return MarketFinding("demand_shift", entity, sev, conf, summ, {}, window)


def test_finding_rerun_supersedes_not_duplicates(db):
    assert persist_findings(db, [_f(summ="old")]) == 1
    assert persist_findings(db, [_f(summ="new")]) == 1  # same (type,entity,window) → supersede
    active = load_recent_findings(db)
    assert len(active) == 1 and active[0].summary == "new"  # only the latest is active
    total = db.execute(text("SELECT COUNT(*) FROM market_finding")).scalar()
    superseded = db.execute(text("SELECT COUNT(*) FROM market_finding WHERE status='superseded'")).scalar()
    assert total == 2 and superseded == 1  # the old row is retained, marked superseded


def test_findings_are_tenant_scoped(db):
    persist_findings(db, [_f(entity="qa")], tenant_id="t-a")
    persist_findings(db, [_f(entity="qb")], tenant_id="t-b")
    a = load_recent_findings(db, tenant_id="t-a")
    b = load_recent_findings(db, tenant_id="t-b")
    assert [x.entity_ref for x in a] == ["qa"] and [x.entity_ref for x in b] == ["qb"]


def test_human_correction_survives_a_later_batch_run(db):
    persist_findings(db, [_f(summ="machine-v1")])
    fid = db.execute(text("SELECT id FROM market_finding WHERE status='active'")).scalar()
    assert correct_finding(db, fid, note="false positive — seasonal") is True
    assert load_recent_findings(db) == []  # corrected → no longer 'active'
    # a later batch run must NOT overwrite the human's verdict; it adds a fresh active row alongside
    persist_findings(db, [_f(summ="machine-v2")])
    corrected = db.execute(text("SELECT status, correction_note, corrected_by_human FROM market_finding "
                                "WHERE id=:i"), {"i": fid}).fetchone()
    assert corrected[0] == "corrected" and "seasonal" in corrected[1] and corrected[2] == 1
    active = load_recent_findings(db)
    assert len(active) == 1 and active[0].summary == "machine-v2"


def test_correct_finding_safe_on_missing(db):
    assert correct_finding(db, "nope") is False
    assert correct_finding(None, "x") is False


def test_unobserved_findings_expire_on_next_run(db):
    # run 1 produces findings for two entities
    persist_findings(db, [_f(entity="q-stays"), _f(entity="q-gone")], expire_unobserved=True)
    assert {f.entity_ref for f in load_recent_findings(db)} == {"q-stays", "q-gone"}
    # run 2 only re-observes q-stays → q-gone's anomaly is gone and must EXPIRE (not linger active)
    persist_findings(db, [_f(entity="q-stays", summ="still here")], expire_unobserved=True)
    active = load_recent_findings(db)
    assert [f.entity_ref for f in active] == ["q-stays"]
    expired = db.execute(text("SELECT entity_ref FROM market_finding WHERE status='expired'")).fetchall()
    assert {r[0] for r in expired} == {"q-gone"}


def test_empty_run_expires_all_active(db):
    persist_findings(db, [_f(entity="q1"), _f(entity="q2")], expire_unobserved=True)
    persist_findings(db, [], expire_unobserved=True)  # nothing observed → all active retired
    assert load_recent_findings(db) == []


def test_human_corrected_findings_never_expire(db):
    persist_findings(db, [_f(entity="q-keep")])
    fid = db.execute(text("SELECT id FROM market_finding WHERE status='active'")).scalar()
    correct_finding(db, fid, note="keep me")
    persist_findings(db, [], expire_unobserved=True)  # a corrected row is human-owned, not expired
    row = db.execute(text("SELECT status FROM market_finding WHERE id=:i"), {"i": fid}).fetchone()
    assert row[0] == "corrected"  # untouched by expiry


def test_expire_unobserved_off_by_default_leaves_old_active(db):
    persist_findings(db, [_f(entity="q-old")])
    persist_findings(db, [_f(entity="q-new")])  # default: no expiry → both active (legacy behaviour)
    assert {f.entity_ref for f in load_recent_findings(db)} == {"q-old", "q-new"}
