from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.config import get_settings, load_feature_flags
from src.app.schemas.ui_contracts import TransactionTimeseriesResponse
from src.app.services.bi_intelligence import (
    margin_intelligence,
    supplier_scorecard,
    clv_prediction,
    churn_prediction,
    seasonal_anomaly_with_causal_attribution,
)
from src.app.services.bi_query_agent import run_query_agent


router = APIRouter(prefix="/api/v1/admin/bi", tags=["admin", "bi"])


def _dialect_name(db) -> str:
    try:
        name = str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
        if name:
            return name
    except Exception:
        pass
    try:
        from src.app.models.db import get_engine

        return str(getattr(getattr(get_engine(), "dialect", None), "name", "") or "").lower()
    except Exception:
        return ""


def _is_sqlite(dialect: str) -> bool:
    return str(dialect or "").startswith("sqlite")


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


def _parse_ts(value: Any) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    # Handle RFC3339/ISO strings with timezone offsets first.
    try:
        iso = s.replace("Z", "+00:00")
        return datetime.fromisoformat(iso)
    except Exception:
        pass
    s = s.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _json_loads_safe(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        obj = json.loads(str(value or "{}"))
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def _normalized_ts_expr(col: str, dialect: str) -> str:
    if _is_sqlite(dialect):
        return _sql_ts_from_text_sqlite(col)
    return _sql_ts_from_text(col)


def _moving_mean(vals: List[float], win: int = 7) -> List[float]:
    out: List[float] = []
    for i in range(len(vals)):
        lo = max(0, i - win + 1)
        chunk = vals[lo : i + 1]
        out.append(sum(chunk) / max(1, len(chunk)))
    return out


def _std(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mu = sum(vals) / len(vals)
    var = sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)
    return math.sqrt(max(0.0, var))


def _security_type_from_details(details_raw: Any) -> str:
    low = str(details_raw or "").lower()
    if "phish" in low or "bec" in low:
        return "phish"
    if "prompt" in low or "jailbreak" in low:
        return "prompt-injection"
    if "qr" in low:
        return "qr"
    if "steg" in low:
        return "steg"
    if "gan" in low or "deepfake" in low:
        return "gan"
    if "network" in low or "pcap" in low or "dns" in low:
        return "network"
    return "other"


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
            dialect = _dialect_name(db)
            if _is_sqlite(dialect):
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


@router.get("/margin-intelligence")
def margin_intelligence_api(
    window_days: int = Query(default=90, ge=7, le=365),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    try:
        return margin_intelligence(window_days=window_days)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"margin_intelligence_failed: {exc}")


@router.get("/supplier-scorecard")
def supplier_scorecard_api(
    window_days: int = Query(default=60, ge=7, le=365),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    try:
        return supplier_scorecard(window_days=window_days)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"supplier_scorecard_failed: {exc}")


@router.get("/clv")
def clv_api(
    window_days: int = Query(default=365, ge=30, le=730),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    try:
        return clv_prediction(window_days=window_days)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"clv_prediction_failed: {exc}")


@router.get("/churn")
def churn_api(
    window_days: int = Query(default=180, ge=30, le=365),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    try:
        return churn_prediction(window_days=window_days)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"churn_prediction_failed: {exc}")


@router.post("/anomaly/seasonal-causal")
def seasonal_causal_api(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    series = payload.get("series") if isinstance(payload, dict) else None
    cov = payload.get("covariates") if isinstance(payload, dict) else None
    if not isinstance(series, list):
        raise HTTPException(status_code=400, detail="series_array_required")
    try:
        return seasonal_anomaly_with_causal_attribution(series, covariates=cov if isinstance(cov, dict) else None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"seasonal_causal_failed: {exc}")


@router.get("/executive-pulse")
def executive_pulse_api(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    dt_start = _parse_date(start)
    dt_end = _parse_date(end)
    if dt_end <= dt_start:
        raise HTTPException(status_code=400, detail="end_must_be_after_start")

    out: Dict[str, Any] = {
        "window": {"start": dt_start.date().isoformat(), "end": dt_end.date().isoformat()},
        "kpis": {
            "revenue": 0.0,
            "gross_margin_pct": 0.0,
            "refund_pct": 0.0,
            "chargeback_pct": 0.0,
            "approval_rate": 0.0,
            "autonomy_pct": 0.0,
            "mttd_minutes": 0.0,
            "mttr_minutes": 0.0,
        },
        "trend_overlays": {"revenue": [], "causal_factors": []},
        "agentic_ops": {"auto_vs_human": [], "false_positive_drift": [], "per_agent": []},
        "security_incursions_matrix": [],
        "decision_replay": [],
    }
    try:
        with db_session() as db:
            dialect = _dialect_name(db)
            vfrom_expr = _normalized_ts_expr("valid_from", dialect)
            ctime_expr = _normalized_ts_expr("created_at", dialect)
            etime_expr = _normalized_ts_expr("event_time", dialect)
            tx = transactions_timeseries("day", dt_start.date().isoformat(), dt_end.date().isoformat(), role="merchant")
            totals = tx.get("totals") or {}
            revenue = float(totals.get("revenue") or 0.0)
            orders = int(totals.get("orders") or 0)
            refunded = int(totals.get("refunded") or 0)
            chargeback = int(totals.get("chargeback") or 0)
            out["kpis"]["revenue"] = round(revenue, 2)
            out["kpis"]["refund_pct"] = round((100.0 * refunded / max(1, orders)), 2)
            out["kpis"]["chargeback_pct"] = round((100.0 * chargeback / max(1, orders)), 2)

            margin = margin_intelligence(window_days=max(7, (dt_end - dt_start).days))
            top = margin.get("top") or []
            total_rev_c = sum(int(x.get("revenue_cents") or 0) for x in top)
            total_margin_c = sum(int(x.get("margin_cents") or 0) for x in top)
            out["kpis"]["gross_margin_pct"] = round((100.0 * total_margin_c / max(1, total_rev_c)), 2)

            dec_rows = db.execute(
                sql_text(
                    f"""
                    SELECT valid_from, policy_version, approval_required, execution_status, agent_name
                    FROM decision_logs
                    WHERE {vfrom_expr} >= :start_ts
                      AND {vfrom_expr} < :end_ts
                    ORDER BY valid_from
                    """
                ),
                {
                    "start_ts": dt_start if not _is_sqlite(dialect) else dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_ts": dt_end if not _is_sqlite(dialect) else dt_end.strftime("%Y-%m-%d %H:%M:%S"),
                },
            ).fetchall()
            total_dec = len(dec_rows or [])
            approved = 0
            autonomous = 0
            policy_rollup: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"decisions": 0, "approved": 0})
            auto_by_day: Dict[str, Dict[str, int]] = defaultdict(lambda: {"auto": 0, "human": 0})
            agent_rollup: Dict[str, Dict[str, float]] = defaultdict(lambda: {"errors": 0.0, "total": 0.0, "latency_ms_sum": 0.0, "latency_n": 0.0})
            for r in dec_rows or []:
                ts = _parse_ts(r[0])
                day = ts.date().isoformat() if ts else ""
                policy = str(r[1] or "unknown")
                approval_required = bool(r[2])
                status = str(r[3] or "").lower()
                agent = str(r[4] or "unknown")
                is_approved = status in ("approved", "executed")
                approved += 1 if is_approved else 0
                if not approval_required:
                    autonomous += 1
                    auto_by_day[day]["auto"] += 1
                else:
                    auto_by_day[day]["human"] += 1
                policy_rollup[policy]["decisions"] += 1
                policy_rollup[policy]["approved"] += 1 if is_approved else 0
                agent_rollup[agent]["total"] += 1
                if status in ("error", "failed", "rejected"):
                    agent_rollup[agent]["errors"] += 1
            out["kpis"]["approval_rate"] = round((100.0 * approved / max(1, total_dec)), 2)
            out["kpis"]["autonomy_pct"] = round((100.0 * autonomous / max(1, total_dec)), 2)

            try:
                trace_rows = db.execute(
                    sql_text(
                        f"""
                        SELECT source_id, payload, event_type
                        FROM decision_trace_events
                        WHERE {ctime_expr} >= :start_ts
                          AND {ctime_expr} < :end_ts
                        """
                    ),
                    {
                        "start_ts": dt_start if not _is_sqlite(dialect) else dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_ts": dt_end if not _is_sqlite(dialect) else dt_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                ).fetchall()
                for tr in trace_rows or []:
                    agent = str(tr[0] or "unknown")
                    payload = {}
                    try:
                        payload = json.loads(str(tr[1] or "{}"))
                    except Exception:
                        payload = {}
                    lat = payload.get("latency_ms")
                    if lat is not None:
                        try:
                            agent_rollup[agent]["latency_ms_sum"] += float(lat)
                            agent_rollup[agent]["latency_n"] += 1
                        except Exception:
                            pass
            except Exception:
                pass

            out["agentic_ops"]["auto_vs_human"] = [
                {"bucket": k, "auto": v["auto"], "human": v["human"]} for k, v in sorted(auto_by_day.items())
            ]
            out["agentic_ops"]["per_agent"] = [
                {
                    "agent": a,
                    "error_rate": round((100.0 * v["errors"] / max(1.0, v["total"])), 2),
                    "avg_latency_ms": round((v["latency_ms_sum"] / max(1.0, v["latency_n"])), 2),
                    "count": int(v["total"]),
                }
                for a, v in sorted(agent_rollup.items(), key=lambda x: x[1]["total"], reverse=True)
            ][:20]

            weekly_fp: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "fp": 0})
            for r in dec_rows or []:
                ts = _parse_ts(r[0])
                if ts is None:
                    continue
                week = ts.strftime("%Y-W%W")
                status = str(r[3] or "").lower()
                weekly_fp[week]["total"] += 1
                if status == "rejected":
                    weekly_fp[week]["fp"] += 1
            out["agentic_ops"]["false_positive_drift"] = [
                {
                    "week": w,
                    "fp_rate": round(100.0 * v["fp"] / max(1, v["total"]), 2),
                    "total": v["total"],
                }
                for w, v in sorted(weekly_fp.items())
            ]

            out["decision_replay"] = [
                {
                    "policy_version": p,
                    "decisions": v["decisions"],
                    "approval_rate": round(100.0 * v["approved"] / max(1, v["decisions"]), 2),
                }
                for p, v in sorted(policy_rollup.items(), key=lambda x: x[1]["decisions"], reverse=True)
            ]

            try:
                sec_rows = db.execute(
                    sql_text(
                        """
                        SELECT event_time, severity, event_type, NULL as correction_ts
                        FROM security_event_ingest
                        WHERE event_time >= :start_ts
                          AND event_time < :end_ts
                        ORDER BY event_time
                        """
                    ),
                    {
                        "start_ts": dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_ts": dt_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                ).fetchall()
            except Exception:
                sec_rows = []
            if not sec_rows:
                sec_rows = db.execute(
                    sql_text(
                        f"""
                        SELECT event_time, severity, details, correction_ts
                        FROM security_events
                        WHERE {etime_expr} >= :start_ts
                          AND {etime_expr} < :end_ts
                        ORDER BY event_time
                        """
                    ),
                    {
                        "start_ts": dt_start if not _is_sqlite(dialect) else dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_ts": dt_end if not _is_sqlite(dialect) else dt_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                ).fetchall()
            mttd: List[float] = []
            mttr: List[float] = []
            matrix: Dict[tuple, int] = defaultdict(int)
            causal_counter: Dict[str, int] = defaultdict(int)
            for s in sec_rows or []:
                ts = _parse_ts(s[0])
                if ts is None:
                    continue
                corr = _parse_ts(s[3])
                diff = (corr - ts).total_seconds() / 60.0 if corr else None
                if diff is not None:
                    mttr.append(max(0.0, diff))
                    mttd.append(max(0.0, min(15.0, diff * 0.4)))
                week = ts.strftime("%Y-W%W")
                sev = str(s[1] or "unknown").lower()
                inc_t = _security_type_from_details(s[2])
                matrix[(week, inc_t, sev)] += 1
                if "promo" in str(s[2] or "").lower():
                    causal_counter["promo"] += 1
                if "supplier" in str(s[2] or "").lower():
                    causal_counter["supplier_outage"] += 1
                if "traffic" in str(s[2] or "").lower():
                    causal_counter["traffic_drop"] += 1
            out["kpis"]["mttd_minutes"] = round(sum(mttd) / max(1, len(mttd)), 2)
            out["kpis"]["mttr_minutes"] = round(sum(mttr) / max(1, len(mttr)), 2)
            out["security_incursions_matrix"] = [
                {"week": k[0], "type": k[1], "severity": k[2], "count": v}
                for k, v in sorted(matrix.items())
            ]

            rev_series = tx.get("series") or []
            buckets = [str(x.get("bucket")) for x in rev_series]
            vals = [float(x.get("revenue") or 0.0) for x in rev_series]
            baseline = _moving_mean(vals, win=7)
            sigma = _std(vals) or 0.0
            causal = sorted(causal_counter.items(), key=lambda x: x[1], reverse=True)
            out["trend_overlays"]["causal_factors"] = [{"id": k, "count": v} for k, v in causal[:6]]
            out["trend_overlays"]["revenue"] = [
                {
                    "bucket": buckets[i],
                    "actual": round(vals[i], 2),
                    "baseline": round(baseline[i], 2),
                    "anomaly_low": round(max(0.0, baseline[i] - 2.0 * sigma), 2),
                    "anomaly_high": round(baseline[i] + 2.0 * sigma, 2),
                    "is_anomaly": bool(abs(vals[i] - baseline[i]) > (2.0 * sigma if sigma > 0 else 999999)),
                }
                for i in range(len(vals))
            ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"executive_pulse_failed: {exc}")
    return out


@router.get("/trend-pack/alarms")
def trend_pack_alarms_api(
    weeks: int = Query(default=8, ge=2, le=52),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=max(14, weeks * 7))
    payload = executive_pulse_api(start=start_date.isoformat(), end=end_date.isoformat(), role="merchant")
    fp = payload.get("agentic_ops", {}).get("false_positive_drift", [])[-weeks:]
    replay = payload.get("decision_replay", [])
    alarms: List[Dict[str, Any]] = []
    if fp:
        rates = [float(x.get("fp_rate") or 0.0) for x in fp]
        if len(rates) >= 2 and rates[-1] > (sum(rates[:-1]) / max(1, len(rates) - 1)) * 1.25:
            alarms.append({"type": "false_positive_drift", "severity": "high", "message": "Weekly false-positive rate spiked >25% above baseline."})
    if replay:
        top = replay[:2]
        if len(top) >= 2:
            delta = abs(float(top[0].get("approval_rate") or 0.0) - float(top[1].get("approval_rate") or 0.0))
            if delta >= 10.0:
                alarms.append({"type": "policy_regression", "severity": "medium", "message": "Approval-rate shift across policy versions exceeds 10 points."})
    return {"status": "ok", "weeks": weeks, "alarms": alarms, "alarm_count": len(alarms)}


@router.post("/query-agent")
def nl_bi_query_agent_api(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    query = str((payload or {}).get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query_required")
    start = (payload or {}).get("start")
    end = (payload or {}).get("end")
    limit = int((payload or {}).get("limit") or 200)
    try:
        with db_session() as db:
            res = run_query_agent(db=db, query=query, start=start, end=end, limit=limit)
            return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"bi_query_agent_failed: {exc}")


@router.get("/agentic-rag/summary")
def agentic_rag_summary_api(
    days: int = Query(default=7, ge=1, le=90),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    try:
        with db_session() as db:
            dialect = _dialect_name(db)
            ctime_expr = _normalized_ts_expr("created_at", dialect)
            if _is_sqlite(dialect):
                where_clause = f"{ctime_expr} >= datetime('now', :window)"
                where_params = {"window": f"-{int(days)} days"}
            else:
                where_clause = f"{ctime_expr} >= (NOW() - (:days * INTERVAL '1 day'))"
                where_params = {"days": int(days)}
            rows = db.execute(
                sql_text(
                    f"""
                    SELECT event_type, payload
                    FROM decision_trace_events
                    WHERE {where_clause}
                      AND event_type IN ('rag_plan','rag_retrieve','rag_rank','context_injected','rag_decide','rag_verify')
                    ORDER BY created_at DESC
                    LIMIT 5000
                    """
                ),
                where_params,
            ).fetchall()
            counts: Dict[str, int] = defaultdict(int)
            contexts_injected = 0
            verify_failures = 0
            avg_budget_util = 0.0
            budget_n = 0
            for r in rows or []:
                ev = str(r[0] or "")
                counts[ev] += 1
                payload = {}
                try:
                    payload = json.loads(str(r[1] or "{}"))
                except Exception:
                    payload = {}
                if ev == "context_injected":
                    contexts_injected += len(payload.get("context_ids") or [])
                    b = float(payload.get("budget_chars") or 0.0)
                    u = float(payload.get("used_chars") or 0.0)
                    if b > 0:
                        avg_budget_util += (u / b)
                        budget_n += 1
                if ev == "rag_verify" and not bool(payload.get("pass_gate", True)):
                    verify_failures += 1
            return {
                "status": "ok",
                "days": int(days),
                "event_counts": counts,
                "contexts_injected": int(contexts_injected),
                "verify_failures": int(verify_failures),
                "avg_budget_utilization": round((avg_budget_util / max(1, budget_n)), 4),
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"agentic_rag_summary_failed: {exc}")


@router.get("/ml-governance/summary")
def ml_governance_summary_api(
    days: int = Query(default=30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    out: Dict[str, Any] = {
        "days": int(days),
        "cf_training": {"runs": [], "last_success_model_version": None, "last_success_at": None},
        "forecast_governance": {"runs": [], "avg_mape_proxy": None, "avg_quarantined_points": None},
    }
    try:
        with db_session() as db:
            dialect = _dialect_name(db)
            if _is_sqlite(dialect):
                where = "datetime(created_at) >= datetime('now', :window)"
                params = {"window": f"-{int(days)} days"}
            else:
                where = "created_at >= (NOW() - (:days * INTERVAL '1 day'))"
                params = {"days": int(days)}

            try:
                rows = db.execute(
                    sql_text(
                        f"""
                        SELECT run_type, status, created_at, metadata_json
                        FROM ml_retrain_governance_runs
                        WHERE {where}
                        ORDER BY created_at DESC
                        LIMIT 500
                        """
                    ),
                    params,
                ).fetchall()
            except Exception:
                rows = []

            cf_runs: List[Dict[str, Any]] = []
            fg_runs: List[Dict[str, Any]] = []
            mape_vals: List[float] = []
            q_vals: List[float] = []
            for r in rows or []:
                run_type = str(r[0] or "")
                status = str(r[1] or "")
                created_at = str(r[2] or "")
                meta = _json_loads_safe(r[3])
                item = {"status": status, "created_at": created_at, "meta": meta}
                if run_type == "recommend_cf_train":
                    cf_runs.append(item)
                elif run_type == "forecast_governance_snapshot":
                    fg_runs.append(item)
                    try:
                        m = meta.get("avg_mape_proxy")
                        if m is not None:
                            mape_vals.append(float(m))
                        q_vals.append(float(meta.get("quarantined_points") or 0.0))
                    except Exception:
                        pass

            out["cf_training"]["runs"] = cf_runs[:20]
            out["forecast_governance"]["runs"] = fg_runs[:20]
            out["forecast_governance"]["avg_mape_proxy"] = (
                round(sum(mape_vals) / max(1, len(mape_vals)), 4) if mape_vals else None
            )
            out["forecast_governance"]["avg_quarantined_points"] = (
                round(sum(q_vals) / max(1, len(q_vals)), 2) if q_vals else None
            )

            try:
                cf_model = db.execute(
                    sql_text(
                        """
                        SELECT model_version, trained_at
                        FROM recommend_cf_model
                        ORDER BY trained_at DESC
                        LIMIT 1
                        """
                    )
                ).fetchone()
            except Exception:
                cf_model = None
            if cf_model:
                out["cf_training"]["last_success_model_version"] = str(cf_model[0] or "")
                out["cf_training"]["last_success_at"] = str(cf_model[1] or "")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ml_governance_summary_failed: {exc}")
    return out


@router.get("/hitl/reviewer-consistency")
def hitl_reviewer_consistency_api(
    days: int = Query(default=30, ge=1, le=180),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    out: Dict[str, Any] = {"days": int(days), "reviewers": [], "summary": {"total_reviews": 0, "median_turnaround_minutes": 0.0}}
    try:
        with db_session() as db:
            try:
                rows = db.execute(
                    sql_text(
                        """
                        SELECT reviewer_id, status, created_at, updated_at
                        FROM human_review_tasks
                        ORDER BY created_at DESC
                        LIMIT 5000
                        """
                    )
                ).fetchall()
            except Exception:
                rows = []
            since = datetime.utcnow() - timedelta(days=int(days))
            rollup: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"total": 0, "approved": 0, "rejected": 0, "escalated": 0, "turnaround": []})
            all_turnaround: List[float] = []
            for r in rows or []:
                reviewer = str(r[0] or "unassigned").strip() or "unassigned"
                status = str(r[1] or "").lower()
                created = _parse_ts(r[2])
                updated = _parse_ts(r[3])
                if created is not None and created.tzinfo is not None:
                    created = created.replace(tzinfo=None)
                if updated is not None and updated.tzinfo is not None:
                    updated = updated.replace(tzinfo=None)
                if created is None or created < since:
                    continue
                bucket = rollup[reviewer]
                bucket["total"] += 1
                if status in ("approved", "completed"):
                    bucket["approved"] += 1
                elif status in ("rejected", "denied"):
                    bucket["rejected"] += 1
                elif status in ("escalated", "needs_escalation"):
                    bucket["escalated"] += 1
                if updated is not None and updated >= created:
                    mins = max(0.0, (updated - created).total_seconds() / 60.0)
                    bucket["turnaround"].append(mins)
                    all_turnaround.append(mins)

            def _median(vals: List[float]) -> float:
                if not vals:
                    return 0.0
                x = sorted(vals)
                m = len(x) // 2
                if len(x) % 2 == 1:
                    return float(x[m])
                return float((x[m - 1] + x[m]) / 2.0)

            items: List[Dict[str, Any]] = []
            for reviewer, v in sorted(rollup.items(), key=lambda kv: kv[1]["total"], reverse=True):
                total = int(v["total"])
                approval_rate = round(100.0 * float(v["approved"]) / max(1, total), 2)
                rejection_rate = round(100.0 * float(v["rejected"]) / max(1, total), 2)
                escalation_rate = round(100.0 * float(v["escalated"]) / max(1, total), 2)
                med = _median(v["turnaround"])
                consistency_band = "high"
                if rejection_rate > 35.0 or escalation_rate > 45.0:
                    consistency_band = "watch"
                if rejection_rate > 50.0 or escalation_rate > 60.0:
                    consistency_band = "low"
                items.append(
                    {
                        "reviewer_id": reviewer,
                        "total_reviews": total,
                        "approval_rate": approval_rate,
                        "rejection_rate": rejection_rate,
                        "escalation_rate": escalation_rate,
                        "median_turnaround_minutes": round(float(med), 2),
                        "consistency_band": consistency_band,
                    }
                )
            out["reviewers"] = items[:50]
            out["summary"]["total_reviews"] = int(sum(int(x["total_reviews"]) for x in out["reviewers"]))
            out["summary"]["median_turnaround_minutes"] = round(_median(all_turnaround), 2)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"hitl_reviewer_consistency_failed: {exc}")
    return out


@router.get("/db-stack/status")
def db_stack_status_api(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    out = {
        "postgres_source_of_truth": False,
        "timescaledb_extension": False,
        "timescale_cagg_orders_hourly": False,
        "redis_configured": False,
        "neo4j_pilot_enabled": False,
        "security_event_storage_targets": [],
        "security_event_storage_paths": {},
    }
    try:
        settings = get_settings()
        out["redis_configured"] = bool(str(getattr(settings, "redis_url", "") or "").strip())
    except Exception:
        pass
    try:
        import os

        out["neo4j_pilot_enabled"] = str(os.getenv("FRAUD_GRAPH_NEO4J_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
        raw_targets = str(os.getenv("SECURITY_EVENT_STORAGE_TARGETS", "database") or "")
        out["security_event_storage_targets"] = [x.strip() for x in raw_targets.split(",") if x.strip()]
        out["security_event_storage_paths"] = {
            "object": str(os.getenv("SECURITY_EVENT_OBJECT_PATH", "data/security-events/object") or "data/security-events/object"),
            "warehouse": str(os.getenv("SECURITY_EVENT_WAREHOUSE_PATH", "data/security-events/warehouse") or "data/security-events/warehouse"),
            "lakehouse": str(os.getenv("SECURITY_EVENT_LAKEHOUSE_PATH", "data/security-events/lakehouse") or "data/security-events/lakehouse"),
            "block": str(os.getenv("SECURITY_EVENT_BLOCK_PATH", "data/security-events/block") or "data/security-events/block"),
        }
    except Exception:
        pass
    try:
        with db_session() as db:
            dialect = _dialect_name(db)
            out["postgres_source_of_truth"] = dialect == "postgresql"
            if dialect == "postgresql":
                out["timescaledb_extension"] = _has_timescaledb(db)
                out["timescale_cagg_orders_hourly"] = _relation_exists(db, "orders_hourly")
    except Exception:
        pass
    return out


@router.get("/security-events/trend-pack")
def security_events_trend_pack_api(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    dt_start = _parse_date(start)
    dt_end = _parse_date(end)
    if dt_end <= dt_start:
        raise HTTPException(status_code=400, detail="end_must_be_after_start")

    matrix: Dict[tuple, int] = defaultdict(int)
    vendor_counts: Dict[str, int] = defaultdict(int)
    action_counts: Dict[str, int] = defaultdict(int)
    hourly_volume: Dict[str, int] = defaultdict(int)
    asn_counts: Dict[str, int] = defaultdict(int)
    country_counts: Dict[str, int] = defaultdict(int)
    impossible_travel_count = 0
    vpn_count = 0
    tor_count = 0
    hosting_count = 0
    high_geo_risk_count = 0
    started = datetime.utcnow()
    query_ms = 0.0
    with db_session() as db:
        try:
            rows = db.execute(
                sql_text(
                    """
                    SELECT event_time, event_type, severity, vendor, policy_action,
                           asn, geo_country, is_vpn, is_tor, is_hosting, geo_risk, impossible_travel
                    FROM security_event_ingest
                    WHERE event_time >= :start_ts
                      AND event_time < :end_ts
                    ORDER BY event_time
                    """
                ),
                {
                    "start_ts": dt_start.strftime("%Y-%m-%d 00:00:00"),
                    "end_ts": dt_end.strftime("%Y-%m-%d 00:00:00"),
                },
            ).fetchall()
        except Exception:
            rows = []
    query_ms = (datetime.utcnow() - started).total_seconds() * 1000.0

    for r in rows or []:
        ts = _parse_ts(r[0])
        if ts is None:
            continue
        week = ts.strftime("%Y-W%W")
        et = str(r[1] or "other").lower()
        if bool(r[11]):
            et = "impossible-travel"
        sev = str(r[2] or "unknown").lower()
        ven = str(r[3] or "unknown").lower()
        act = str(r[4] or "allow").lower()
        matrix[(week, et, sev)] += 1
        vendor_counts[ven] += 1
        action_counts[act] += 1
        hourly_volume[ts.strftime("%Y-%m-%d %H:00")] += 1
        asn = str(r[5] or "").strip()
        country = str(r[6] or "").strip()
        if asn:
            asn_counts[asn] += 1
        if country:
            country_counts[country] += 1
        vpn_count += 1 if bool(r[7]) else 0
        tor_count += 1 if bool(r[8]) else 0
        hosting_count += 1 if bool(r[9]) else 0
        try:
            high_geo_risk_count += 1 if float(r[10] or 0.0) >= 0.7 else 0
        except Exception:
            pass
        impossible_travel_count += 1 if bool(r[11]) else 0

    return {
        "window": {"start": dt_start.date().isoformat(), "end": dt_end.date().isoformat()},
        "security_incursions_matrix": [
            {"week": k[0], "type": k[1], "severity": k[2], "count": v}
            for k, v in sorted(matrix.items())
        ],
        "trend_overlays": {
            "vendor_counts": [{"vendor": k, "count": v} for k, v in sorted(vendor_counts.items(), key=lambda x: x[1], reverse=True)],
            "policy_actions": [{"action": k, "count": v} for k, v in sorted(action_counts.items(), key=lambda x: x[1], reverse=True)],
            "hourly_volume": [{"bucket": k, "count": v} for k, v in sorted(hourly_volume.items())],
            "asn_counts": [{"asn": k, "count": v} for k, v in sorted(asn_counts.items(), key=lambda x: x[1], reverse=True)[:20]],
            "country_counts": [{"country": k, "count": v} for k, v in sorted(country_counts.items(), key=lambda x: x[1], reverse=True)[:20]],
        },
        "geo_risk_summary": {
            "impossible_travel": int(impossible_travel_count),
            "vpn": int(vpn_count),
            "tor": int(tor_count),
            "hosting": int(hosting_count),
            "high_geo_risk": int(high_geo_risk_count),
        },
        "dashboard_query_latency_ms": round(float(query_ms), 2),
        "rows": len(rows or []),
    }


@router.get("/memory-health")
def memory_health_api(
    days: int = Query(7, ge=1, le=90),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    now = datetime.utcnow()
    start = now - timedelta(days=int(days))
    out: Dict[str, Any] = {
        "window": {"start": start.date().isoformat(), "end": now.date().isoformat()},
        "days": int(days),
        "totals": {
            "events": 0,
            "memory_miss": 0,
            "shortlist_lock_failed": 0,
            "disambiguation_prompts": 0,
            "summary_checkpoints": 0,
        },
        "averages": {
            "memory_confidence": 0.0,
            "summary_age_sec": 0.0,
        },
        "stale_slots_top": [],
    }
    conf_sum = 0.0
    conf_n = 0
    age_sum = 0.0
    age_n = 0
    stale_rollup: Dict[str, int] = defaultdict(int)
    try:
        with db_session() as db:
            rows = db.execute(
                sql_text(
                    """
                    SELECT event_type, payload, created_at
                    FROM decision_trace_events
                    WHERE created_at >= :start_ts
                      AND (
                        source_id = 'Conversation_Memory_Agent'
                        OR event_type IN ('memory_health', 'session_summary_checkpoint', 'memory_disambiguation_prompted')
                      )
                    ORDER BY created_at DESC
                    """
                ),
                {"start_ts": start.strftime("%Y-%m-%d %H:%M:%S")},
            ).fetchall()
    except Exception:
        rows = []
    for r in rows or []:
        et = str((r[0] if len(r) > 0 else "") or "")
        payload = _json_loads_safe(r[1] if len(r) > 1 else {})
        out["totals"]["events"] += 1
        if et == "memory_disambiguation_prompted":
            out["totals"]["disambiguation_prompts"] += 1
        if et == "session_summary_checkpoint":
            out["totals"]["summary_checkpoints"] += 1
        if et == "memory_health":
            if bool(payload.get("memory_miss")):
                out["totals"]["memory_miss"] += 1
            if bool(payload.get("shortlist_lock_failed")):
                out["totals"]["shortlist_lock_failed"] += 1
            try:
                if payload.get("memory_confidence") is not None:
                    conf_sum += float(payload.get("memory_confidence") or 0.0)
                    conf_n += 1
            except Exception:
                pass
            try:
                if payload.get("summary_age_sec") is not None:
                    age_sum += float(payload.get("summary_age_sec") or 0.0)
                    age_n += 1
            except Exception:
                pass
            for s in (payload.get("stale_slots") or []):
                stale_rollup[str(s)] += 1
    out["averages"]["memory_confidence"] = round(conf_sum / conf_n, 4) if conf_n else 0.0
    out["averages"]["summary_age_sec"] = round(age_sum / age_n, 2) if age_n else 0.0
    out["stale_slots_top"] = [
        {"slot": slot, "count": count}
        for slot, count in sorted(stale_rollup.items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]
    return out
