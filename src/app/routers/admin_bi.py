from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.config import get_settings, load_feature_flags
from src.app.schemas.ui_contracts import TransactionTimeseriesResponse


router = APIRouter(prefix="/api/v1/admin/bi", tags=["admin", "bi"])


def _timescale_flags() -> Dict[str, Any]:
    try:
        ff = load_feature_flags(get_settings().feature_flags_path) or {}
    except Exception:
        ff = {}
    cfg = ff.get("TIMESCALE", {}) if isinstance(ff.get("TIMESCALE"), dict) else {}
    return {
        "compat_enabled": bool(cfg.get("bi_compat_enabled", True)),
        "use_cagg": bool(cfg.get("bi_use_cagg", False)),
    }


def _has_timescaledb(db) -> bool:
    try:
        row = db.execute(sql_text("SELECT 1 FROM pg_catalog.pg_extension WHERE extname='timescaledb'")).fetchone()
        return bool(row)
    except Exception:
        return False


def _relation_exists(db, name: str) -> bool:
    try:
        row = db.execute(sql_text("SELECT to_regclass(:n)"), {"n": name}).fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def _parse_date(s: str) -> datetime:
    try:
        return datetime.strptime(str(s), "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_date_expected_yyyy_mm_dd")


def _sql_ts_from_text(col: str) -> str:
    # Orders/security tables store timestamps as TEXT for demo portability.
    # Normalize common ISO formats into a Postgres timestamp for aggregation.
    #
    # Handles:
    # - "2026-02-13 06:47:11.148457"
    # - "2026-02-13T10:10:26.450261"
    # - "2026-02-13T10:10:26.450261Z"
    return f"""
    (
      CASE
        WHEN {col} IS NULL OR {col} = '' THEN NULL
        WHEN {col} LIKE '%Z' THEN replace(replace({col}, 'T', ' '), 'Z', '')::timestamp
        WHEN {col} LIKE '%T%' THEN replace({col}, 'T', ' ')::timestamp
        ELSE {col}::timestamp
      END
    )
    """


def _sql_ts_from_text_sqlite(col: str) -> str:
    # SQLite-safe timestamp normalization for TEXT columns.
    return f"datetime(replace(replace({col}, 'T', ' '), 'Z', ''))"


@router.get("/transactions/timeseries", response_model=TransactionTimeseriesResponse)
def transactions_timeseries(
    granularity: str = Query(default="day", pattern="^(day|month)$"),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD (exclusive end)"),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    dt_start = _parse_date(start)
    dt_end = _parse_date(end)
    if dt_end <= dt_start:
        raise HTTPException(status_code=400, detail="end_must_be_after_start")

    rows: List[Dict[str, Any]] = []
    source = "orders_raw"
    totals = {
        "orders": 0,
        "revenue": 0.0,
        "paid": 0,
        "refunded": 0,
        "chargeback": 0,
        "pending_payment": 0,
    }
    try:
        with db_session() as db:
            dialect = str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
            if dialect == "sqlite":
                ts_expr = _sql_ts_from_text_sqlite("created_at")
                bucket_expr = (
                    f"substr({ts_expr}, 1, 10)"
                    if granularity == "day"
                    else f"(substr({ts_expr}, 1, 7) || '-01')"
                )
                q = sql_text(
                    f"""
                    SELECT
                      {bucket_expr} AS bucket_ts,
                      COUNT(*) AS orders,
                      COALESCE(SUM(total_cents), 0) AS revenue_cents,
                      COALESCE(SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END), 0) AS paid,
                      COALESCE(SUM(CASE WHEN status = 'refunded' THEN 1 ELSE 0 END), 0) AS refunded,
                      COALESCE(SUM(CASE WHEN status = 'chargeback' THEN 1 ELSE 0 END), 0) AS chargeback,
                      COALESCE(SUM(CASE WHEN status = 'pending_payment' THEN 1 ELSE 0 END), 0) AS pending_payment
                    FROM orders
                    WHERE {ts_expr} >= datetime(:start_ts)
                      AND {ts_expr} < datetime(:end_ts)
                    GROUP BY 1
                    ORDER BY 1
                    """
                )
                res = db.execute(
                    q,
                    {
                        "start_ts": dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_ts": dt_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                ).fetchall()
            else:
                ts_expr = _sql_ts_from_text("created_at")
                bucket = "day" if granularity == "day" else "month"
                ts_cfg = _timescale_flags()
                ts_available = _has_timescaledb(db)
                use_time_bucket = bool(ts_cfg["compat_enabled"] and ts_available)
                use_cagg = bool(ts_cfg["use_cagg"] and ts_available and granularity == "day" and _relation_exists(db, "orders_hourly"))
                if use_cagg:
                    source = "timescale_cagg_orders_hourly"
                    q = sql_text(
                        """
                        SELECT
                          date_trunc('day', bucket) AS bucket_ts,
                          COALESCE(SUM(order_count), 0)::int AS orders,
                          COALESCE(SUM(revenue_cents), 0)::bigint AS revenue_cents,
                          0::int AS paid,
                          0::int AS refunded,
                          0::int AS chargeback,
                          0::int AS pending_payment
                        FROM orders_hourly
                        WHERE bucket >= :start_ts
                          AND bucket < :end_ts
                        GROUP BY 1
                        ORDER BY 1
                        """
                    )
                    res = db.execute(q, {"start_ts": dt_start, "end_ts": dt_end}).fetchall()
                else:
                    if use_time_bucket:
                        source = "orders_raw_time_bucket"
                        bucket_interval = "1 day" if bucket == "day" else "1 month"
                        bucket_expr = f"time_bucket('{bucket_interval}', {ts_expr})"
                    else:
                        source = "orders_raw_date_trunc"
                        bucket_expr = f"date_trunc('{bucket}', {ts_expr})"
                    q = sql_text(
                        f"""
                        SELECT
                          {bucket_expr} AS bucket_ts,
                          COUNT(*)::int AS orders,
                          COALESCE(SUM(total_cents), 0)::bigint AS revenue_cents,
                          COALESCE(SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END), 0)::int AS paid,
                          COALESCE(SUM(CASE WHEN status = 'refunded' THEN 1 ELSE 0 END), 0)::int AS refunded,
                          COALESCE(SUM(CASE WHEN status = 'chargeback' THEN 1 ELSE 0 END), 0)::int AS chargeback,
                          COALESCE(SUM(CASE WHEN status = 'pending_payment' THEN 1 ELSE 0 END), 0)::int AS pending_payment
                        FROM orders
                        WHERE {ts_expr} >= :start_ts
                          AND {ts_expr} < :end_ts
                        GROUP BY 1
                        ORDER BY 1
                        """
                    )
                    res = db.execute(q, {"start_ts": dt_start, "end_ts": dt_end}).fetchall()
            for r in res or []:
                bucket_ts = r[0]
                rev_cents = int(r[2] or 0)
                if bucket_ts is None:
                    bucket_iso = None
                elif hasattr(bucket_ts, "date"):
                    bucket_iso = bucket_ts.date().isoformat()
                else:
                    s = str(bucket_ts)
                    bucket_iso = s[:10] if len(s) >= 10 else s
                    if granularity == "month" and bucket_iso and len(bucket_iso) >= 7:
                        bucket_iso = bucket_iso[:7] + "-01"
                item = {
                    "bucket": bucket_iso,
                    "orders": int(r[1] or 0),
                    "revenue": round(rev_cents / 100.0, 2),
                    "paid": int(r[3] or 0),
                    "refunded": int(r[4] or 0),
                    "chargeback": int(r[5] or 0),
                    "pending_payment": int(r[6] or 0),
                }
                rows.append(item)
                totals["orders"] += item["orders"]
                totals["revenue"] += float(item["revenue"])
                totals["paid"] += item["paid"]
                totals["refunded"] += item["refunded"]
                totals["chargeback"] += item["chargeback"]
                totals["pending_payment"] += item["pending_payment"]
    except Exception:
        # Keep demo stable even if DB is not ready; frontend will show empty state.
        rows = []

    # Derived metrics
    aov = (totals["revenue"] / max(1, totals["orders"])) if totals["orders"] else 0.0
    totals["aov"] = round(float(aov), 2)

    return {
        "granularity": granularity,
        "start": dt_start.date().isoformat(),
        "end": dt_end.date().isoformat(),
        "series": rows,
        "totals": totals,
        "source": source,
    }
