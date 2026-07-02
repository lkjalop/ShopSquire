"""Competitor price source (agnostic CORE) — a REAL market source feeding detect_competitor_undercut.

A competitor_observation row records a rival's price for one of our SKUs. The market-signal backfill
joins it to our canonical price_book_entry (our retail) and emits a 'competitor' signal, which the M3
detector detect_competitor_undercut consumes — so a LIVE undercut surfaces as a finding, not just in
the synthetic replay. This is the genuinely-new real source on top of orders/conversion/search/returns.

Vertical-blind (sku · cents); idempotent record/seed (deterministic id); never raises.
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

# DDL kept textually identical to alembic/versions/20260627_competitor_observation.py (drift-tested).
_DDL = """
CREATE TABLE IF NOT EXISTS competitor_observation (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    sku TEXT NOT NULL,
    competitor TEXT,
    competitor_price_cents INTEGER,
    observed_at TEXT,
    source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_competitor_obs_sku ON competitor_observation(tenant_id, sku)",
)


def ensure_table(db) -> None:
    db.execute(text(_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


def _obs_id(tenant_id: str, sku: str, competitor: str, observed_at: str) -> str:
    raw = "|".join([str(tenant_id), str(sku), str(competitor), str(observed_at)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def record_observation(db, *, sku: str, competitor_price_cents: int, competitor: str = "",
                       observed_at: str = "", source: str = "manual", tenant_id: str = DEFAULT_TENANT,
                       commit: bool = False) -> bool:
    """Idempotently record a competitor price observation (dedup on tenant/sku/competitor/observed_at)."""
    if db is None or not sku:
        return False
    try:
        ensure_table(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        oid = _obs_id(tid, sku, competitor, observed_at)
        exists = db.execute(text("SELECT 1 FROM competitor_observation WHERE id=:i"), {"i": oid}).fetchone()
        if not exists:
            db.execute(text(
                "INSERT INTO competitor_observation (id, tenant_id, sku, competitor, "
                "competitor_price_cents, observed_at, source) VALUES (:i,:t,:k,:c,:p,:o,:s)"),
                {"i": oid, "t": tid, "k": str(sku), "c": competitor,
                 "p": int(competitor_price_cents), "o": observed_at or None, "s": source})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


# relative to today so the demo undercut never ages out of the analysis window (was pinned to 2026-06-26).
_DEMO = [("LAP-021", 99900, "rival-store.example", f"{date.today().isoformat()}T09:00:00")]  # under our 1200.00 → undercut


def seed_demo(db, *, tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> Dict[str, int]:
    """Seed a demo competitor undercut (idempotent). Pairs with the price_book seed so a real-pipeline
    run produces a competitor_undercut finding. Returns {observations}."""
    if db is None:
        return {}
    ensure_table(db)
    n = sum(1 for sku, cents, comp, ts in _DEMO
            if record_observation(db, sku=sku, competitor_price_cents=cents, competitor=comp,
                                  observed_at=ts, source="seed", tenant_id=tenant_id))
    if commit:
        try:
            db.commit()
        except Exception:
            return {"observations": n}
    return {"observations": n}
