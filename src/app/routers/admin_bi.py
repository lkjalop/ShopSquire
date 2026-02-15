from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER


router = APIRouter(prefix="/api/v1/admin/bi", tags=["admin", "bi"])


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


@router.get("/transactions/timeseries")
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

    ts_expr = _sql_ts_from_text("created_at")
    bucket = "day" if granularity == "day" else "month"
    bucket_expr = f"date_trunc('{bucket}', {ts_expr})"

    rows: List[Dict[str, Any]] = []
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
                item = {
                    "bucket": bucket_ts.date().isoformat() if bucket_ts else None,
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
    }

