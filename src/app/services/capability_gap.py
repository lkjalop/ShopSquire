"""Capability-gap ledger (agnostic CORE) — a durable record of what users ASKED FOR that the platform
could not (or would not) do.

Every honest refusal is product signal: an unsupported action ("cancel my order" in chat), an unmet
search, or a refused/malicious request (prompt injection) lands here as one row. QA mines the rollup at
the weekly roadmap review — the highest-count gaps become the next build; refused-attack tallies feed the
security review. This is how a BOUNDED platform gets smarter without getting looser.

Vertical-blind: category/utterance are opaque text; no product vocabulary. Best-effort writes (a ledger
failure must never break the user's turn); reads are operator-only at the router.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

# gap categories (open set — these are the conventional ones)
GAP_UNSUPPORTED_ACTION = "unsupported_action"   # user asked for an action the platform can't execute
GAP_UNMET_SEARCH = "unmet_search"               # search/plan produced nothing usable
GAP_REFUSED_REQUEST = "refused_request"         # policy/security refusal (incl. injection attempts)

_DDL = """
CREATE TABLE IF NOT EXISTS capability_gap (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    category TEXT,
    utterance TEXT,
    refusal_reason TEXT,
    surface TEXT,
    uid_hash TEXT,
    trace_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_IDX = "CREATE INDEX IF NOT EXISTS ix_capability_gap_cat ON capability_gap(tenant_id, category, created_at)"


def ensure_table(db) -> None:
    db.execute(text(_DDL))
    db.execute(text(_IDX))


def record_gap(db, *, category: str, utterance: str, refusal_reason: str = "", surface: str = "chat",
               uid_hash: Optional[str] = None, trace_id: Optional[str] = None,
               tenant_id: str = DEFAULT_TENANT) -> bool:
    """Write one gap row. Best-effort: returns whether it persisted; never raises."""
    if db is None:
        return False
    try:
        ensure_table(db)
        db.execute(text(
            "INSERT INTO capability_gap (id, tenant_id, category, utterance, refusal_reason, surface, "
            "uid_hash, trace_id) VALUES (:i,:t,:c,:u,:r,:s,:uh,:tr)"),
            {"i": str(uuid.uuid4()), "t": str(tenant_id).strip() or DEFAULT_TENANT,
             "c": str(category or GAP_UNSUPPORTED_ACTION)[:40], "u": str(utterance or "")[:500],
             "r": str(refusal_reason or "")[:200], "s": str(surface or "chat")[:40],
             "uh": uid_hash, "tr": trace_id})
        db.commit()
        return True
    except Exception:
        return False


def gap_rollup(db, *, limit: int = 50, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
    """The QA/roadmap view: per-category counts + the most recent examples. Best-effort; empty on error."""
    if db is None:
        return {"by_category": [], "recent": []}
    try:
        ensure_table(db)
        t = str(tenant_id).strip() or DEFAULT_TENANT
        cats = db.execute(text(
            "SELECT category, COUNT(*), MAX(created_at) FROM capability_gap "
            "WHERE COALESCE(tenant_id,'default')=:t GROUP BY category ORDER BY COUNT(*) DESC"),
            {"t": t}).fetchall()
        recent = db.execute(text(
            "SELECT category, utterance, refusal_reason, surface, created_at FROM capability_gap "
            "WHERE COALESCE(tenant_id,'default')=:t ORDER BY created_at DESC LIMIT :lim"),
            {"t": t, "lim": int(limit)}).fetchall()
    except Exception:
        return {"by_category": [], "recent": []}
    return {
        "by_category": [{"category": r[0], "count": int(r[1] or 0), "last_seen": r[2]} for r in cats],
        "recent": [{"category": r[0], "utterance": r[1], "refusal_reason": r[2], "surface": r[3],
                    "created_at": r[4]} for r in recent],
    }
