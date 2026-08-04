"""Procurement notifications (agnostic CORE) — the operator's "something needs your attention" feed.

When a buyer confirms a cart (cases materialize), amends a confirmed order (supersession), or a supplier
reports an out-of-band change, the operator should learn immediately — not only when they happen to refresh
the queue. This is a small durable feed the admin polls: write on the event, read unseen, mark seen.

Vertical-blind: kind · summary · ref are opaque strings — no product vocabulary. Best-effort; never raises
into a caller (a notification failure must never break the action that triggered it).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.procurement_notifications")

_DDL = """
CREATE TABLE IF NOT EXISTS procurement_notifications (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT,
    kind        TEXT,
    summary     TEXT,
    ref         TEXT,
    created_at  TEXT,
    seen        INTEGER DEFAULT 0
)
"""


def _now_iso(now_iso: Optional[str]) -> str:
    if now_iso:
        return str(now_iso)
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def notify(db, *, kind: str, summary: str, ref: Optional[str] = None, tenant_id: str = "default",
           now_iso: Optional[str] = None) -> Optional[str]:
    """Record one operator notification. Returns the id, or None on any failure (best-effort)."""
    summary = str(summary or "").strip()
    if db is None or not summary:
        return None
    nid = f"pn-{uuid.uuid4().hex[:12]}"
    try:
        db.execute(text(_DDL))
        db.execute(text(
            "INSERT INTO procurement_notifications (id, tenant_id, kind, summary, ref, created_at, seen) "
            "VALUES (:i, :t, :k, :s, :r, :c, 0)"),
            {"i": nid, "t": str(tenant_id or "default"), "k": str(kind or "info"), "s": summary,
             "r": (str(ref) if ref else None), "c": _now_iso(now_iso)})
        db.commit()
        return nid
    except Exception as exc:
        logger.debug("notify insert failed (%s): %s", kind, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def list_notifications(db, *, tenant_id: str = "default", unseen_only: bool = False,
                       limit: int = 50) -> List[Dict[str, Any]]:
    """Recent notifications (newest first). unseen_only filters to seen=0. Best-effort; []."""
    if db is None:
        return []
    try:
        db.execute(text(_DDL))
        where = "WHERE tenant_id=:t" + (" AND seen=0" if unseen_only else "")
        rows = db.execute(text(
            f"SELECT id, kind, summary, ref, created_at, seen FROM procurement_notifications "
            f"{where} ORDER BY created_at DESC LIMIT :lim"),
            {"t": str(tenant_id or "default"), "lim": int(limit)}).fetchall()
        return [{"id": r[0], "kind": r[1], "summary": r[2], "ref": r[3], "created_at": r[4],
                 "seen": bool(r[5])} for r in (rows or [])]
    except Exception as exc:
        logger.debug("list_notifications failed: %s", exc)
        return []


def unseen_count(db, *, tenant_id: str = "default") -> int:
    if db is None:
        return 0
    try:
        db.execute(text(_DDL))
        row = db.execute(text("SELECT COUNT(*) FROM procurement_notifications WHERE tenant_id=:t AND seen=0"),
                         {"t": str(tenant_id or "default")}).fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def mark_seen(db, *, ids: Optional[List[str]] = None, tenant_id: str = "default") -> int:
    """Mark the given notification ids seen (or ALL unseen for the tenant when ids is None). Returns the
    number updated. Best-effort; 0 on failure."""
    if db is None:
        return 0
    try:
        db.execute(text(_DDL))
        if ids:
            ids = [str(i) for i in ids if i]
            if not ids:
                return 0
            ph = ", ".join(f":id{i}" for i in range(len(ids)))
            params: Dict[str, Any] = {"t": str(tenant_id or "default")}
            params.update({f"id{i}": v for i, v in enumerate(ids)})
            n = db.execute(text(
                f"UPDATE procurement_notifications SET seen=1 WHERE tenant_id=:t AND id IN ({ph})"),
                params).rowcount
        else:
            n = db.execute(text(
                "UPDATE procurement_notifications SET seen=1 WHERE tenant_id=:t AND seen=0"),
                {"t": str(tenant_id or "default")}).rowcount
        db.commit()
        return int(n or 0)
    except Exception as exc:
        logger.debug("mark_seen failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return 0
