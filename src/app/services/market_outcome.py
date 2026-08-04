"""Decision-outcome + attribution store (agnostic CORE) — David Module 2/6 close-the-loop.

Persists the TERMINAL evaluation of an autonomous decision (keep / scale / revise / revert + uplift) and
the metric events attributed to it, so the experimentation module can answer "did the change actually
work?" and so any future customer-facing execution is measurable + reversible (the Phase-3 prerequisite).

Append-only logs (a decision accrues an outcome history). Vertical-blind: decision labels + metric names
are opaque. Idempotent table creation; best-effort writes; never raises into a caller.

Tables:
  decision_outcome(id, tenant_id, decision_ref, source, target_metric, uplift_pct, decision, significant,
                   n_control, n_treatment, reverted, window, recorded_at)
  attribution_event(id, tenant_id, decision_ref, metric, value, segment, occurred_at, recorded_at)
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

_OUTCOME_DDL = """
CREATE TABLE IF NOT EXISTS decision_outcome (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    decision_ref TEXT,
    source TEXT,
    target_metric TEXT,
    uplift_pct REAL,
    decision TEXT,
    significant INTEGER DEFAULT 0,
    n_control INTEGER DEFAULT 0,
    n_treatment INTEGER DEFAULT 0,
    reverted INTEGER DEFAULT 0,
    window TEXT,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_ATTRIBUTION_DDL = """
CREATE TABLE IF NOT EXISTS attribution_event (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    decision_ref TEXT,
    metric TEXT,
    value REAL,
    segment TEXT,
    occurred_at TEXT,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_decision_outcome_ref ON decision_outcome(tenant_id, decision_ref)",
    "CREATE INDEX IF NOT EXISTS ix_attribution_event_ref ON attribution_event(tenant_id, decision_ref)",
)


def ensure_tables(db) -> None:
    if db is None:
        return
    db.execute(text(_OUTCOME_DDL))
    db.execute(text(_ATTRIBUTION_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


def _as_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _as_float(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def record_outcome(db, *, decision_ref: str, decision: Optional[str], uplift_pct: Any = None,
                   significant: Any = None, n_control: Any = None, n_treatment: Any = None,
                   reverted: Any = False, source: str = "experiment", target_metric: Optional[str] = None,
                   window: str = "evaluation", tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> Optional[str]:
    """Append one terminal decision outcome (keep/scale/revise/revert + uplift). Returns the row id, or
    None on failure. Best-effort; never raises."""
    if db is None or not str(decision_ref or "").strip():
        return None
    try:
        ensure_tables(db)
        oid = str(uuid.uuid4())
        db.execute(
            text("INSERT INTO decision_outcome (id, tenant_id, decision_ref, source, target_metric, "
                 "uplift_pct, decision, significant, n_control, n_treatment, reverted, window) "
                 "VALUES (:id,:tn,:dr,:src,:tm,:up,:dc,:sig,:nc,:nt,:rv,:win)"),
            {"id": oid, "tn": str(tenant_id or DEFAULT_TENANT), "dr": str(decision_ref), "src": str(source or ""),
             "tm": (str(target_metric) if target_metric else None), "up": _as_float(uplift_pct),
             "dc": (str(decision) if decision else None), "sig": 1 if significant else 0,
             "nc": _as_int(n_control), "nt": _as_int(n_treatment), "rv": 1 if reverted else 0,
             "win": str(window or "")},
        )
        if commit:
            db.commit()
        return oid
    except Exception:
        return None


def record_attribution(db, *, decision_ref: str, metric: str, value: Any, segment: Optional[str] = None,
                       occurred_at: Optional[str] = None, tenant_id: str = DEFAULT_TENANT,
                       commit: bool = False) -> Optional[str]:
    """Append one metric event attributed to a decision (for segment-specific outcome analysis). Returns
    the row id, or None. Best-effort; never raises."""
    if db is None or not str(decision_ref or "").strip() or not str(metric or "").strip():
        return None
    try:
        ensure_tables(db)
        aid = str(uuid.uuid4())
        db.execute(
            text("INSERT INTO attribution_event (id, tenant_id, decision_ref, metric, value, segment, "
                 "occurred_at) VALUES (:id,:tn,:dr,:mt,:vl,:sg,:oc)"),
            {"id": aid, "tn": str(tenant_id or DEFAULT_TENANT), "dr": str(decision_ref), "mt": str(metric),
             "vl": _as_float(value), "sg": (str(segment) if segment else None),
             "oc": (str(occurred_at) if occurred_at else None)},
        )
        if commit:
            db.commit()
        return aid
    except Exception:
        return None


def load_attribution_rollup(db, *, decision_ref: Optional[str] = None, limit: int = 20,
                            tenant_id: str = DEFAULT_TENANT) -> List[Dict[str, Any]]:
    """Attributed metric events rolled up per (decision_ref, metric, segment): event count + value sum.
    The read side of the M6 close-loop — "what outcomes accrued to this adaptation, split by exposure
    segment?" Newest-activity refs first. Best-effort; never raises."""
    if db is None:
        return []
    try:
        ensure_tables(db)
        sql = ("SELECT decision_ref, metric, segment, COUNT(*), SUM(value), MAX(recorded_at) "
               "FROM attribution_event WHERE COALESCE(tenant_id,'default')=:t ")
        params: Dict[str, Any] = {"t": str(tenant_id or DEFAULT_TENANT), "lim": int(limit)}
        if decision_ref:
            sql += "AND decision_ref=:dr "
            params["dr"] = str(decision_ref)
        rows = db.execute(text(sql + "GROUP BY decision_ref, metric, segment "
                                     "ORDER BY MAX(recorded_at) DESC LIMIT :lim"), params).fetchall()
    except Exception:
        return []
    return [{"decision_ref": r[0], "metric": r[1], "segment": r[2], "events": int(r[3] or 0),
             "total_value": (float(r[4]) if r[4] is not None else None), "last_event_at": r[5]} for r in rows]


def load_recent_outcomes(db, *, decision_ref: Optional[str] = None, limit: int = 50,
                         tenant_id: str = DEFAULT_TENANT) -> List[Dict[str, Any]]:
    """Recent decision outcomes (optionally for one decision_ref), newest first. Best-effort."""
    if db is None:
        return []
    try:
        ensure_tables(db)
        sql = ("SELECT decision_ref, source, target_metric, uplift_pct, decision, significant, "
               "n_control, n_treatment, reverted, recorded_at FROM decision_outcome "
               "WHERE COALESCE(tenant_id,'default')=:t ")
        params: Dict[str, Any] = {"t": str(tenant_id or DEFAULT_TENANT), "lim": int(limit)}
        if decision_ref:
            sql += "AND decision_ref=:dr "
            params["dr"] = str(decision_ref)
        rows = db.execute(text(sql + "ORDER BY recorded_at DESC LIMIT :lim"), params).fetchall()
    except Exception:
        return []
    return [{"decision_ref": r[0], "source": r[1], "target_metric": r[2], "uplift_pct": r[3],
             "decision": r[4], "significant": bool(r[5]), "n_control": int(r[6] or 0),
             "n_treatment": int(r[7] or 0), "reverted": bool(r[8]), "recorded_at": r[9]} for r in rows]
