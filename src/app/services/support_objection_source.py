"""Support-objection source (agnostic CORE) — a REAL market source feeding detect_objection_cluster.

A support_objection row records a buyer objection on a theme (price / delivery_time / …). The
market-signal backfill emits a 'support_objection' signal per row, and the M3 detector
detect_objection_cluster surfaces a finding when a theme recurs — so a LIVE objection cluster appears,
not just in synthetic replay. The seam where a support-tool/chat adapter writes objections.

Vertical-blind (opaque theme · entity ref); idempotent record/seed (deterministic id); never raises.
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

# DDL kept textually identical to alembic/versions/20260627_support_objection.py (drift-tested).
_DDL = """
CREATE TABLE IF NOT EXISTS support_objection (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    theme TEXT,
    entity_ref TEXT,
    raised_at TEXT,
    source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_support_objection_theme ON support_objection(tenant_id, theme)",
)


def ensure_table(db) -> None:
    db.execute(text(_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


def _obs_id(tenant_id: str, theme: str, entity_ref: str, raised_at: str) -> str:
    raw = "|".join([str(tenant_id), str(theme), str(entity_ref or ""), str(raised_at)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def record_objection(db, *, theme: str, entity_ref: str = "", raised_at: str = "", source: str = "manual",
                     tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> bool:
    """Idempotently record a buyer objection (dedup on tenant/theme/entity/raised_at)."""
    if db is None or not theme:
        return False
    try:
        ensure_table(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        oid = _obs_id(tid, theme, entity_ref, raised_at)
        exists = db.execute(text("SELECT 1 FROM support_objection WHERE id=:i"), {"i": oid}).fetchone()
        if not exists:
            db.execute(text(
                "INSERT INTO support_objection (id, tenant_id, theme, entity_ref, raised_at, source) "
                "VALUES (:i,:t,:th,:e,:r,:s)"),
                {"i": oid, "t": tid, "th": str(theme), "e": entity_ref or None,
                 "r": raised_at or None, "s": source})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


# enough of the same theme to trip detect_objection_cluster (min_count=3 → "price" cluster).
# Timestamps relative to today so the demo objection cluster never ages out of the analysis window.
_TODAY = date.today().isoformat()
_DEMO = [("price", f"{_TODAY}T0{i}:00:00") for i in range(4)] + [("delivery_time", f"{_TODAY}T05:00:00")]


def seed_demo(db, *, tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> Dict[str, int]:
    """Seed a demo objection cluster (4× 'price' → a finding). Idempotent. Returns {observations}."""
    if db is None:
        return {}
    ensure_table(db)
    n = sum(1 for theme, ts in _DEMO
            if record_objection(db, theme=theme, raised_at=ts, source="seed", tenant_id=tenant_id))
    if commit:
        try:
            db.commit()
        except Exception:
            return {"observations": n}
    return {"observations": n}
