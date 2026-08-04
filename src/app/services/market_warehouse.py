"""Market-signal WAREHOUSE sink (agnostic CORE) — David Module 2 store depth + retention.

The raw market_signal table is the event log; it grows unbounded and is expensive to scan for trends.
This module SINKS raw signals into a compact, retained, queryable aggregate (market_signal_rollup):
one row per (tenant, day, signal_type, source) with a count + trust sum/avg + last-seen. That gives the
intelligence store DEPTH that survives retention, and lets the analysis engine read trends without
scanning the raw log.

  • roll_up        — sink raw signals into daily (type, source) aggregates (idempotent upsert per bucket)
  • prune_signals  — RETENTION: drop raw signals past the window (depth is preserved in the rollup)
  • query_depth    — read the trend depth from the rollup (cheap, bounded)
  • sink_and_retain— roll up THEN prune (so nothing is pruned before it is rolled up)

Vertical-blind: speaks only tenant / day / signal_type / source / counts / trust — zero product
vocabulary (signal_type and source are opaque labels). Best-effort; never raises.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"
_log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS market_signal_rollup (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    bucket_date TEXT,
    signal_type TEXT,
    source TEXT,
    signal_count INTEGER,
    trust_sum REAL,
    trust_avg REAL,
    last_occurred_at TEXT,
    updated_at TEXT
)
"""
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_msr_bucket ON market_signal_rollup(tenant_id, bucket_date, signal_type, source)",
    "CREATE INDEX IF NOT EXISTS ix_msr_date ON market_signal_rollup(bucket_date)",
)


def ensure_rollup_table(db) -> None:
    from src.app.services.schema_policy import runtime_ddl_allowed
    if not runtime_ddl_allowed():
        return
    db.execute(text(_DDL))
    for stmt in _INDEXES:
        db.execute(text(stmt))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _now(now_iso: Optional[str]) -> datetime:
    if now_iso:
        try:
            return datetime.fromisoformat(str(now_iso).replace("Z", "").replace("T", " "))
        except ValueError:
            return _utcnow()  # observable fallback (not a silent swallow)
    return _utcnow()


def _trust(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0  # observable fallback — a non-numeric trust contributes 0, never crashes the rollup


def _day(occurred_at: Any, ingested_at: Any) -> Optional[str]:
    """The YYYY-MM-DD bucket for a signal — prefer the event time, fall back to ingest time."""
    for v in (occurred_at, ingested_at):
        s = str(v or "").strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
    return None


def roll_up(db, *, tenant_id: str = DEFAULT_TENANT, since: Optional[str] = None) -> int:
    """Aggregate raw market_signal rows into daily (signal_type, source) buckets. Idempotent: a bucket is
    recomputed and replaced, so re-running after new signals lands updates rather than duplicates. ``since``
    (a YYYY-MM-DD or ISO string) bounds the scan to signals ingested at/after it. Returns buckets written."""
    try:
        ensure_rollup_table(db)
        sql = ("SELECT signal_type, source, trust_score, occurred_at, ingested_at "
               "FROM market_signal WHERE tenant_id = :tn")
        params: Dict[str, Any] = {"tn": tenant_id}
        if since:
            sql += " AND ingested_at >= :since"
            params["since"] = str(since)
        rows = db.execute(text(sql), params).fetchall()
        # group by (bucket_date, signal_type, source)
        agg: Dict[tuple, Dict[str, Any]] = {}
        for st, src, trust, occ, ing in rows:
            bucket = _day(occ, ing)
            if bucket is None:
                continue
            key = (bucket, str(st or ""), str(src or ""))
            a = agg.setdefault(key, {"count": 0, "trust_sum": 0.0, "last": ""})
            a["count"] += 1
            a["trust_sum"] += _trust(trust)
            occ_s = str(occ or "")
            if occ_s > a["last"]:
                a["last"] = occ_s
        now = _now(None).isoformat()
        written = 0
        for (bucket, st, src), a in agg.items():
            rid = f"{tenant_id}:{bucket}:{st}:{src}"
            cnt = int(a["count"])
            tsum = round(float(a["trust_sum"]), 6)
            tavg = round(tsum / cnt, 6) if cnt else 0.0
            # portable upsert: delete the deterministic-id row then insert the recomputed aggregate
            db.execute(text("DELETE FROM market_signal_rollup WHERE id = :id"), {"id": rid})
            db.execute(
                text("INSERT INTO market_signal_rollup (id, tenant_id, bucket_date, signal_type, source, "
                     "signal_count, trust_sum, trust_avg, last_occurred_at, updated_at) "
                     "VALUES (:id,:tn,:bd,:st,:src,:cnt,:ts,:ta,:last,:ua)"),
                {"id": rid, "tn": tenant_id, "bd": bucket, "st": st, "src": src, "cnt": cnt,
                 "ts": tsum, "ta": tavg, "last": a["last"], "ua": now},
            )
            written += 1
        return written
    except Exception as exc:
        _log.warning("market_warehouse.roll_up failed: %s", exc)
        return 0


def prune_signals(db, *, older_than_days: int, tenant_id: str = DEFAULT_TENANT,
                  now_iso: Optional[str] = None) -> int:
    """RETENTION: delete raw market_signal rows ingested before the cutoff (now - older_than_days). The
    aggregated depth lives in the rollup, so trends survive. older_than_days <= 0 is a NO-OP (never prune
    by accident). Returns the number of rows deleted."""
    if not older_than_days or int(older_than_days) <= 0:
        return 0
    try:
        # retention is in DAYS — compare on the ingest DATE (substr 1..10) so the T-vs-space timestamp
        # separator can't skew the boundary. Keeps the last `older_than_days` days; older rows are pruned.
        cutoff_date = (_now(now_iso) - timedelta(days=int(older_than_days))).strftime("%Y-%m-%d")
        res = db.execute(
            text("DELETE FROM market_signal WHERE tenant_id = :tn AND substr(ingested_at, 1, 10) < :cut"),
            {"tn": tenant_id, "cut": cutoff_date},
        )
        return int(getattr(res, "rowcount", 0) or 0)
    except Exception as exc:
        _log.warning("market_warehouse.prune_signals failed: %s", exc)
        return 0


def query_depth(db, *, tenant_id: str = DEFAULT_TENANT, signal_type: Optional[str] = None,
                source: Optional[str] = None, days: int = 90, now_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read the trend depth from the rollup: daily buckets in the last ``days``, newest first. Cheap +
    bounded (scans aggregates, not the raw log). Filters by signal_type/source when given."""
    try:
        ensure_rollup_table(db)
        cutoff = (_now(now_iso) - timedelta(days=int(days))).strftime("%Y-%m-%d") if days and int(days) > 0 else "0000-00-00"
        sql = ("SELECT bucket_date, signal_type, source, signal_count, trust_avg, last_occurred_at "
               "FROM market_signal_rollup WHERE tenant_id = :tn AND bucket_date >= :cut")
        params: Dict[str, Any] = {"tn": tenant_id, "cut": cutoff}
        if signal_type:
            sql += " AND signal_type = :st"
            params["st"] = str(signal_type)
        if source:
            sql += " AND source = :src"
            params["src"] = str(source)
        sql += " ORDER BY bucket_date DESC, signal_type, source"
        rows = db.execute(text(sql), params).fetchall()
        return [{"bucket_date": r[0], "signal_type": r[1], "source": r[2],
                 "signal_count": int(r[3] or 0), "trust_avg": float(r[4] or 0.0),
                 "last_occurred_at": r[5]} for r in rows]
    except Exception as exc:
        _log.warning("market_warehouse.query_depth failed: %s", exc)
        return []


def sink_and_retain(db, *, tenant_id: str = DEFAULT_TENANT, retention_days: Optional[int] = None,
                    since: Optional[str] = None, now_iso: Optional[str] = None) -> Dict[str, int]:
    """Roll up THEN prune — the warehouse maintenance step. Rolling up first guarantees nothing is pruned
    before its depth is captured. ``retention_days`` None/<=0 → no pruning. Returns {rolled_up, pruned}."""
    rolled = roll_up(db, tenant_id=tenant_id, since=since)
    pruned = prune_signals(db, older_than_days=int(retention_days or 0), tenant_id=tenant_id, now_iso=now_iso) \
        if retention_days else 0
    return {"rolled_up": rolled, "pruned": pruned}
