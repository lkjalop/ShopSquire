"""Funnel / cart-abandonment source (agnostic CORE) — a REAL market source feeding detect_funnel_dropoff.

A cart_funnel_event row records, for one purchase-funnel stage, how many buyers ENTERED it and how many
ABANDONED. The market-signal backfill emits a 'funnel' signal per row, and the M3 detector
detect_funnel_dropoff surfaces a finding when a stage loses a high fraction of the buyers who reached it
— a LIVE drop-off, not just synthetic replay. The seam where a storefront/analytics adapter writes funnel
snapshots.

Vertical-blind (opaque stage label · counts); idempotent record/seed (deterministic id); never raises.
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

# DDL kept textually identical to alembic/versions/20260627_cart_funnel_event.py (drift-tested).
_DDL = """
CREATE TABLE IF NOT EXISTS cart_funnel_event (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    stage TEXT,
    entered INTEGER DEFAULT 0,
    abandoned INTEGER DEFAULT 0,
    observed_at TEXT,
    source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_cart_funnel_stage ON cart_funnel_event(tenant_id, stage)",
)


def ensure_table(db) -> None:
    db.execute(text(_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


def _obs_id(tenant_id: str, stage: str, observed_at: str) -> str:
    raw = "|".join([str(tenant_id), str(stage), str(observed_at)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def record_event(db, *, stage: str, entered: int, abandoned: int, observed_at: str = "",
                 source: str = "manual", tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> bool:
    """Idempotently record a funnel-stage snapshot (dedup on tenant/stage/observed_at)."""
    if db is None or not stage:
        return False
    try:
        ensure_table(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        oid = _obs_id(tid, stage, observed_at)
        exists = db.execute(text("SELECT 1 FROM cart_funnel_event WHERE id=:i"), {"i": oid}).fetchone()
        if not exists:
            db.execute(text(
                "INSERT INTO cart_funnel_event (id, tenant_id, stage, entered, abandoned, observed_at, "
                "source) VALUES (:i,:t,:st,:en,:ab,:o,:s)"),
                {"i": oid, "t": tid, "st": str(stage), "en": int(entered), "ab": int(abandoned),
                 "o": observed_at or None, "s": source})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


# a payment stage bleeding ~70% of carts → a finding (entered well above the detector's min_volume).
# Timestamps relative to today, computed at CALL time (not import) so the demo funnel drop never ages out.
def _demo():
    today = date.today().isoformat()
    return [("cart", 100, 20, f"{today}T08:00:00"), ("payment", 60, 42, f"{today}T08:00:00")]


def seed_demo(db, *, tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> Dict[str, int]:
    """Seed a demo funnel with a payment-stage drop-off (42/60 → 70%). Idempotent. Returns {events}."""
    if db is None:
        return {}
    ensure_table(db)
    n = sum(1 for stage, entered, abandoned, ts in _demo()
            if record_event(db, stage=stage, entered=entered, abandoned=abandoned, observed_at=ts,
                            source="seed", tenant_id=tenant_id))
    if commit:
        try:
            db.commit()
        except Exception:
            return {"events": n}
    return {"events": n}
