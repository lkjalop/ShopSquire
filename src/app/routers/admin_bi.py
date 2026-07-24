from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
import logging
from typing import Dict, Any, List

logger = logging.getLogger("shopsquire.admin_bi")

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text as sql_text
from prometheus_client import generate_latest
from pydantic import BaseModel, Field

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.config import get_settings, load_feature_flags
from src.app.feature_flags import get_flags as _ff_get_flags
from src.app.schemas.ui_contracts import TransactionTimeseriesResponse
from src.app.schemas.metric_evidence import (
    AuditorMetricProjection, MetricEvidence, OperatorMetricProjection,
)
from src.app.services.bi_intelligence import (
    margin_intelligence,
    supplier_scorecard,
    clv_prediction,
    churn_prediction,
    seasonal_anomaly_with_causal_attribution,
)
from src.app.services.bi_query_agent import run_query_agent


router = APIRouter(prefix="/api/v1/admin/bi", tags=["admin", "bi"])


def _executive_metric_projection(tenant_id: str) -> OperatorMetricProjection:
    from src.app.services.market_metrics import summarize_marketing_facts
    from src.app.services.market_projection import projections

    with db_session() as db:
        product_metrics = projections(db, tenant_id=tenant_id, window_days=30)
        try:
            marketing = summarize_marketing_facts(db, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("marketing metric projection unavailable for %s: %s", tenant_id, exc)
            marketing = {"data_quality": {}, "event_count": 0}
    metrics = []
    for projection in product_metrics.values():
        for payload in projection.get("metrics") or []:
            metrics.append(MetricEvidence.model_validate(payload))
    rfm = clv_prediction(window_days=365, tenant_id=tenant_id)
    churn = churn_prediction(window_days=180, tenant_id=tenant_id)
    return OperatorMetricProjection(
        tenant_id=tenant_id,
        metrics=metrics,
        data_quality={
            **dict(marketing.get("data_quality") or {}),
            "event_count": int(marketing.get("event_count") or 0),
        },
        estimates={
            "rfm_method": rfm.get("method"),
            "rfm_status": rfm.get("status"),
            "customer_estimate_count": len(rfm.get("users") or []),
            "churn_method": churn.get("method"),
            "churn_status": churn.get("status"),
            "high_churn_estimate_count": sum(
                float(row.get("churn_risk") or 0.0) >= 0.7
                for row in churn.get("users") or []),
        },
        actions=[],
    )


@router.get("/executive-metrics", response_model=OperatorMetricProjection)
def executive_metrics_api(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> OperatorMetricProjection:
    """Operator projection only; buyer traces never fetch this endpoint."""
    _ = role
    from src.app.platform.tenant_context import current_tenant_id
    return _executive_metric_projection(str(current_tenant_id() or "default"))


@router.get("/executive-metrics/audit", response_model=AuditorMetricProjection)
def executive_metrics_audit_api(
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> AuditorMetricProjection:
    """Auditor projection adds rejected evidence; it remains read-only."""
    _ = role
    from src.app.platform.tenant_context import current_tenant_id
    tenant_id = str(current_tenant_id() or "default")
    operator = _executive_metric_projection(tenant_id)
    with db_session() as db:
        try:
            quarantined = int(db.execute(sql_text(
                "SELECT COUNT(*) FROM market_fact_quarantine WHERE tenant_id=:tenant"
            ), {"tenant": tenant_id}).scalar_one() or 0)
        except Exception:
            quarantined = 0
    return AuditorMetricProjection(
        **operator.model_dump(),
        quarantined_evidence_count=quarantined,
        policy_decisions=[],
    )


class NewsletterDraftRequest(BaseModel):
    skus: List[str] = Field(default_factory=list, max_length=10)


def _parse_prometheus_samples(metric_name: str) -> List[tuple[Dict[str, str], float]]:
    out: List[tuple[Dict[str, str], float]] = []
    try:
        blob = generate_latest().decode("utf-8", errors="ignore")
    except Exception:
        return out
    for line in blob.splitlines():
        ln = line.strip()
        if not ln or ln.startswith("#"):
            continue
        if not ln.startswith(metric_name):
            continue
        try:
            label_map: Dict[str, str] = {}
            val_s = ""
            if "{" in ln and "}" in ln:
                left = ln.find("{")
                right = ln.rfind("}")
                labels_raw = ln[left + 1 : right]
                val_s = ln[right + 1 :].strip()
                for part in labels_raw.split(","):
                    if "=" not in part:
                        continue
                    k, v = part.split("=", 1)
                    label_map[str(k).strip()] = str(v).strip().strip('"')
            else:
                val_s = ln[len(metric_name) :].strip()
            val = float(str(val_s or "0").split(" ")[0])
            out.append((label_map, val))
        except Exception:
            continue
    return out


def _counter_sum_from_prom(metric_name: str) -> float:
    total = 0.0
    for _, val in _parse_prometheus_samples(metric_name):
        try:
            total += float(val)
        except Exception:
            continue
    return total


def _http_p95_ms_from_prom(path: str, method: str = "GET") -> float | None:
    buckets = []
    m = "shopsquire_http_request_duration_seconds_bucket"
    for labels, val in _parse_prometheus_samples(m):
        if str(labels.get("path") or "") != str(path):
            continue
        if str(labels.get("method") or "").upper() != str(method).upper():
            continue
        le_s = str(labels.get("le") or "")
        try:
            le = float("inf") if le_s == "+Inf" else float(le_s)
            buckets.append((le, float(val)))
        except Exception:
            continue
    if not buckets:
        return None
    buckets.sort(key=lambda x: x[0])
    total = max(0.0, float(buckets[-1][1]))
    if total <= 0.0:
        return None
    target = 0.95 * total
    for le, cumulative in buckets:
        if cumulative >= target:
            if le == float("inf"):
                return None
            return round(le * 1000.0, 2)
    return None


def _slo_state(value: float | None, warn: float, crit: float) -> str:
    if value is None:
        return "unknown"
    if value >= crit:
        return "critical"
    if value >= warn:
        return "warn"
    return "ok"


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
        ff = _ff_get_flags() or {}
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
        pass
    # Accept Unix timestamps (seconds or milliseconds)
    try:
        ts = float(str(s))
        if ts > 1e10:  # milliseconds
            ts /= 1000
        return datetime.utcfromtimestamp(ts)
    except Exception:
        pass
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
    from src.app.platform.tenant_context import current_tenant_id
    try:
        return margin_intelligence(
            window_days=window_days, tenant_id=str(current_tenant_id() or "default"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"margin_intelligence_failed: {exc}")


@router.get("/product-projection")
def product_projection_api(
    sku: str = Query(..., min_length=1, max_length=160),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Operator-only projection; wholesale and margin never enter the public trace."""
    _ = role
    from src.app.platform.tenant_context import current_tenant_id
    from src.app.services.market_projection import operator_product_projection
    with db_session() as db:
        result = operator_product_projection(
            db, sku=sku, tenant_id=str(current_tenant_id() or "default"))
    if not result.get("available"):
        raise HTTPException(status_code=404, detail=result.get("reason") or "projection_unavailable")
    return result


@router.post("/product-projection/{sku}/proposals/{action_type}")
def submit_product_action_proposal(
    sku: str,
    action_type: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Queue an eligible commercial proposal for human review.

    Approval records authorization only. This endpoint never applies a discount,
    sends a supplier message, or creates a purchase order.
    """
    action = str(action_type or "").strip().lower()
    if action not in {"discount", "replenishment"}:
        raise HTTPException(status_code=404, detail="unknown_commercial_action")
    from src.app.platform.tenant_context import current_tenant_id
    from src.app.routers.approvals import enqueue_approval
    from src.app.services.market_projection import operator_product_projection

    tenant_id = str(current_tenant_id() or "default")
    with db_session() as db:
        projection = operator_product_projection(db, sku=sku, tenant_id=tenant_id)
    if not projection.get("available"):
        raise HTTPException(status_code=404, detail=projection.get("reason") or "projection_unavailable")
    proposal = (projection.get("action_proposals") or {}).get(action) or {}
    eligible = (
        bool(proposal.get("eligible"))
        if action == "discount" else bool(proposal.get("authorized"))
    )
    if not eligible:
        raise HTTPException(status_code=409, detail={
            "reason": "proposal_not_authorized",
            "action_type": action,
            "reasons": proposal.get("reasons") or [],
        })
    approval_id = enqueue_approval(
        f"commercial_{action}",
        {
            "tenant_id": tenant_id,
            "sku": str(sku),
            "proposal": proposal,
            "execution": "not_implemented_by_approval",
        },
        reason="human_review_required",
        created_by=role,
    )
    return {
        "queued": True,
        "approval_id": approval_id,
        "action_type": action,
        "human_gate": "required",
        "executed": False,
    }


@router.post("/newsletter-draft")
def newsletter_draft_api(
    request: NewsletterDraftRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Create an editable evidence-bounded draft; never publish or send it."""
    _ = role
    from src.app.platform.tenant_context import current_tenant_id
    from src.app.services.market_projection import operator_product_projection
    from src.app.services.newsletter_draft import build_newsletter_draft

    tenant_id = str(current_tenant_id() or "default")
    projections = []
    with db_session() as db:
        for sku in dict.fromkeys(str(value).strip() for value in request.skus if str(value).strip()):
            item = operator_product_projection(db, sku=sku, tenant_id=tenant_id)
            if item.get("available"):
                projections.append(item)
    draft = build_newsletter_draft(projections)
    return {"tenant_id": tenant_id, **draft}


@router.get("/supplier-scorecard")
def supplier_scorecard_api(
    window_days: int = Query(default=60, ge=7, le=365),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    from src.app.platform.tenant_context import current_tenant_id
    try:
        return supplier_scorecard(
            window_days=window_days, tenant_id=str(current_tenant_id() or "default"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"supplier_scorecard_failed: {exc}")


@router.get("/clv")
def clv_api(
    window_days: int = Query(default=365, ge=30, le=730),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    from src.app.platform.tenant_context import current_tenant_id
    try:
        return clv_prediction(
            window_days=window_days, tenant_id=str(current_tenant_id() or "default"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"clv_prediction_failed: {exc}")


@router.get("/churn")
def churn_api(
    window_days: int = Query(default=180, ge=30, le=365),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    from src.app.platform.tenant_context import current_tenant_id
    try:
        return churn_prediction(
            window_days=window_days, tenant_id=str(current_tenant_id() or "default"))
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

            from src.app.platform.tenant_context import current_tenant_id
            margin = margin_intelligence(
                window_days=max(7, (dt_end - dt_start).days),
                tenant_id=str(current_tenant_id() or "default"),
            )
            top = margin.get("top") or []
            total_rev_c = sum(int(x.get("revenue_cents") or 0) for x in top)
            known_margin = [x for x in top if x.get("margin_cents") is not None]
            if known_margin and total_rev_c > 0:
                total_margin_c = sum(int(x["margin_cents"]) for x in known_margin)
                out["kpis"]["gross_margin_pct"] = round(
                    (100.0 * total_margin_c / total_rev_c), 2)
            else:
                out["kpis"]["gross_margin_pct"] = None
                out["kpis"]["gross_margin_status"] = "unavailable"

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


@router.get("/persona-success")
def persona_success_api(
    days: int = Query(7, ge=1, le=90),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    now = datetime.utcnow()
    start = now - timedelta(days=int(days))
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {
        "window": {"start": start.date().isoformat(), "end": now.date().isoformat()},
        "days": int(days),
        "totals": {
            "traces": 0,
            "reformulated": 0,
            "reupload_required": 0,
        },
        "personas": [],
    }
    try:
        with db_session() as db:
            dialect = _dialect_name(db)
            ctime_expr = _normalized_ts_expr("created_at", dialect)
            rows = db.execute(
                sql_text(
                    f"""
                    SELECT trace_id, event_type, payload, created_at
                    FROM decision_trace_events
                    WHERE {ctime_expr} >= :start_ts
                      AND event_type IN ('user_query', 'image_reupload_requested', 'session_summary_checkpoint')
                    ORDER BY {ctime_expr} ASC
                    """
                ),
                {"start_ts": start_s if _is_sqlite(dialect) else start},
            ).fetchall()
    except Exception:
        rows = []

    traces: Dict[str, Dict[str, Any]] = {}
    reformulation_markers = (
        "actually",
        "instead",
        "change",
        "changed",
        "not this",
        "not that",
        "different",
        "rephrase",
        "another option",
    )
    for r in rows or []:
        trace_id = str((r[0] if len(r) > 0 else "") or "").strip()
        if not trace_id:
            continue
        et = str((r[1] if len(r) > 1 else "") or "").strip().lower()
        payload = _json_loads_safe(r[2] if len(r) > 2 else {})
        st = traces.setdefault(
            trace_id,
            {
                "persona": "unknown",
                "persona_confidence": 0.0,
                "resolved_turn": 0,
                "reformulated": False,
                "reupload_required": False,
            },
        )
        if et == "user_query":
            q = str(payload.get("query") or "").lower()
            if any(m in q for m in reformulation_markers):
                st["reformulated"] = True
            constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
            p = str(
                constraints.get("buyer_persona")
                or constraints.get("buyer_persona_candidate")
                or payload.get("buyer_persona")
                or "unknown"
            ).strip() or "unknown"
            try:
                conf = float(
                    constraints.get("buyer_persona_confidence")
                    or payload.get("buyer_persona_confidence")
                    or 0.0
                )
            except Exception:
                conf = 0.0
            if conf >= float(st.get("persona_confidence") or 0.0):
                st["persona"] = p
                st["persona_confidence"] = conf
        elif et == "image_reupload_requested":
            st["reupload_required"] = True
        elif et == "session_summary_checkpoint":
            try:
                turn = int(payload.get("turn") or 0)
            except Exception:
                turn = 0
            if turn > int(st.get("resolved_turn") or 0):
                st["resolved_turn"] = turn

    rollup: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"traces": 0, "sum_resolution_turns": 0, "reformulated": 0, "reupload_required": 0}
    )
    for _, st in traces.items():
        persona = str(st.get("persona") or "unknown")
        grp = rollup[persona]
        grp["traces"] += 1
        grp["sum_resolution_turns"] += max(1, int(st.get("resolved_turn") or 0))
        grp["reformulated"] += 1 if bool(st.get("reformulated")) else 0
        grp["reupload_required"] += 1 if bool(st.get("reupload_required")) else 0

    personas = []
    for persona, grp in sorted(rollup.items(), key=lambda kv: kv[1]["traces"], reverse=True):
        count = int(grp.get("traces") or 0)
        personas.append(
            {
                "persona": persona,
                "traces": count,
                "resolution_turns_avg": round(float(grp.get("sum_resolution_turns") or 0) / float(max(1, count)), 3),
                "reformulation_rate": round(float(grp.get("reformulated") or 0) / float(max(1, count)), 4),
                "reupload_rate": round(float(grp.get("reupload_required") or 0) / float(max(1, count)), 4),
            }
        )
        out["totals"]["traces"] += count
        out["totals"]["reformulated"] += int(grp.get("reformulated") or 0)
        out["totals"]["reupload_required"] += int(grp.get("reupload_required") or 0)
    out["personas"] = personas
    return out


@router.get("/slo-alerts")
def slo_alerts_api(
    window_hours: int = Query(24, ge=1, le=168),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    now = datetime.utcnow()
    start = now - timedelta(hours=int(window_hours))
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")

    recommend_traces: Dict[str, Dict[str, Any]] = {}
    memory_events = 0
    shortlist_failures = 0
    nqe_total = 0
    nqe_converted = 0

    try:
        with db_session() as db:
            dialect = _dialect_name(db)
            ctime_expr = _normalized_ts_expr("created_at", dialect)
            trace_rows = db.execute(
                sql_text(
                    f"""
                    SELECT trace_id, event_type, source_id, payload
                    FROM decision_trace_events
                    WHERE {ctime_expr} >= :start_ts
                    """
                ),
                {"start_ts": start_s if _is_sqlite(dialect) else start},
            ).fetchall()
            for r in trace_rows or []:
                trace_id = str(r[0] or "").strip()
                et = str(r[1] or "").strip()
                src = str(r[2] or "").strip()
                payload = _json_loads_safe(r[3] if len(r) > 3 else {})

                if et == "memory_health":
                    memory_events += 1
                    if bool(payload.get("shortlist_lock_failed")):
                        shortlist_failures += 1

                is_reco_signal = src in {
                    "Candidate_Retrieval_Agent",
                    "Product_Ranking_Agent",
                    "Category_Filter_Agent",
                    "Price_Filter_Agent",
                    "Spec_Filter_Agent",
                } or et in {"candidate_retrieval", "ranking_complete", "nqe_fallback_alternatives", "output"}
                if not is_reco_signal or not trace_id:
                    continue
                st = recommend_traces.setdefault(trace_id, {"irrelevant": False})
                if et == "nqe_fallback_alternatives":
                    st["irrelevant"] = True
                if src == "Category_Filter_Agent":
                    try:
                        strict = bool(payload.get("strict"))
                        before = int(payload.get("candidates_before") or 0)
                        after = int(payload.get("candidates_after") or 0)
                        if strict and before > 0 and after == 0:
                            st["irrelevant"] = True
                    except Exception:
                        pass
                if et == "output":
                    try:
                        if int(payload.get("results_count") or 0) == 0 and str(payload.get("status") or "").lower() in {"ok", "success", "clarifying_questions"}:
                            st["irrelevant"] = True
                    except Exception:
                        pass
    except Exception:
        pass

    try:
        with db_session() as db:
            dialect = _dialect_name(db)
            ctime_expr = _normalized_ts_expr("created_at", dialect)
            rows = db.execute(
                sql_text(
                    f"""
                    SELECT converted
                    FROM nqe_feedback_events
                    WHERE {ctime_expr} >= :start_ts
                    """
                ),
                {"start_ts": start_s if _is_sqlite(dialect) else start},
            ).fetchall()
            nqe_total = len(rows or [])
            nqe_converted = sum(1 for r in (rows or []) if bool((r[0] if len(r) > 0 else False)))
    except Exception:
        nqe_total = 0
        nqe_converted = 0

    recommend_p95_ms = _http_p95_ms_from_prom("/api/v1/recommend/suggest", method="GET")
    chat_p95_ms = _http_p95_ms_from_prom("/api/v1/chat/query", method="POST")
    trace_events_total = _counter_sum_from_prom("shopsquire_decision_events_total")
    trace_write_failures = _counter_sum_from_prom("shopsquire_decision_trace_write_failures_total")

    irrelevant_traces = sum(1 for _, v in recommend_traces.items() if bool(v.get("irrelevant")))
    recommend_total = len(recommend_traces)
    irrelevant_rate = (float(irrelevant_traces) / float(max(1, recommend_total))) if recommend_total else 0.0
    nqe_conversion_rate = (float(nqe_converted) / float(max(1, nqe_total))) if nqe_total else 0.0
    shortlist_loss_rate = (float(shortlist_failures) / float(max(1, memory_events))) if memory_events else 0.0
    trace_drop_rate = (float(trace_write_failures) / float(max(1.0, trace_events_total + trace_write_failures))) if (trace_events_total + trace_write_failures) > 0 else 0.0

    thresholds = {
        "recommend_p95_ms": {"warn": 1200.0, "critical": 2500.0},
        "chat_p95_ms": {"warn": 1300.0, "critical": 2800.0},
        "irrelevant_result_rate": {"warn": 0.25, "critical": 0.40},
        "nqe_conversion_rate_min": {"warn": 0.12, "critical": 0.08},
        "shortlist_loss_rate": {"warn": 0.02, "critical": 0.05},
        "trace_event_drop_rate": {"warn": 0.01, "critical": 0.03},
    }
    alerts = [
        {
            "name": "recommend_p95_latency",
            "state": _slo_state(recommend_p95_ms, thresholds["recommend_p95_ms"]["warn"], thresholds["recommend_p95_ms"]["critical"]),
            "value": recommend_p95_ms,
            "unit": "ms",
        },
        {
            "name": "chat_p95_latency",
            "state": _slo_state(chat_p95_ms, thresholds["chat_p95_ms"]["warn"], thresholds["chat_p95_ms"]["critical"]),
            "value": chat_p95_ms,
            "unit": "ms",
        },
        {
            "name": "irrelevant_result_rate",
            "state": _slo_state(irrelevant_rate, thresholds["irrelevant_result_rate"]["warn"], thresholds["irrelevant_result_rate"]["critical"]),
            "value": round(irrelevant_rate, 4),
            "unit": "ratio",
        },
        {
            "name": "nqe_conversion_rate",
            "state": "critical"
            if nqe_conversion_rate < thresholds["nqe_conversion_rate_min"]["critical"]
            else ("warn" if nqe_conversion_rate < thresholds["nqe_conversion_rate_min"]["warn"] else "ok"),
            "value": round(nqe_conversion_rate, 4),
            "unit": "ratio",
        },
        {
            "name": "shortlist_loss_rate",
            "state": _slo_state(shortlist_loss_rate, thresholds["shortlist_loss_rate"]["warn"], thresholds["shortlist_loss_rate"]["critical"]),
            "value": round(shortlist_loss_rate, 4),
            "unit": "ratio",
        },
        {
            "name": "trace_event_drop_rate",
            "state": _slo_state(trace_drop_rate, thresholds["trace_event_drop_rate"]["warn"], thresholds["trace_event_drop_rate"]["critical"]),
            "value": round(trace_drop_rate, 6),
            "unit": "ratio",
        },
    ]

    return {
        "window": {"hours": int(window_hours), "start": start.isoformat(), "end": now.isoformat()},
        "metrics": {
            "recommend_p95_latency_ms": recommend_p95_ms,
            "chat_p95_latency_ms": chat_p95_ms,
            "irrelevant_result_rate": round(irrelevant_rate, 4),
            "nqe_conversion_rate": round(nqe_conversion_rate, 4),
            "shortlist_loss_rate": round(shortlist_loss_rate, 4),
            "trace_event_drop_rate": round(trace_drop_rate, 6),
        },
        "denominators": {
            "recommend_traces": int(recommend_total),
            "nqe_feedback_events": int(nqe_total),
            "memory_health_events": int(memory_events),
            "trace_events_total_counter": float(trace_events_total),
            "trace_write_failures_total_counter": float(trace_write_failures),
        },
        "thresholds": thresholds,
        "alerts": alerts,
        "status": "critical" if any(a["state"] == "critical" for a in alerts) else ("warn" if any(a["state"] == "warn" for a in alerts) else "ok"),
    }


@router.get("/security-events/stream")
async def security_events_stream(
    request: Request,
    last_id: int = Query(default=0, ge=0, description="Last seen row id; returns only newer events"),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> StreamingResponse:
    """Server-Sent Events stream for live security events.

    Polls both `security_event_ingest` and `security_events` tables every 3 s and
    pushes new rows to the client as ``data: <JSON>\\n\\n`` frames.

    Query params:
    - **last_id**: cursor — only rows with `id > last_id` are emitted (default 0 = all recent)

    The stream closes after 120 s of inactivity or on client disconnect.
    """
    _ = role

    async def event_gen():
        cursor = int(last_id)
        deadline = asyncio.get_event_loop().time() + 120
        while asyncio.get_event_loop().time() < deadline:
            if await request.is_disconnected():
                break
            rows: List[Dict[str, Any]] = []
            try:
                with db_session() as db:
                    # Primary: security_event_ingest (has rowid-like id)
                    try:
                        raw = db.execute(
                            sql_text(
                                """
                                SELECT id, event_time, event_type, severity, vendor, tenant_id
                                FROM security_event_ingest
                                WHERE id > :cursor
                                ORDER BY id ASC
                                LIMIT 50
                                """
                            ),
                            {"cursor": cursor},
                        ).fetchall()
                        for r in raw or []:
                            rows.append(
                                {
                                    "id": int(r[0] or 0),
                                    "event_time": str(r[1] or ""),
                                    "event_type": str(r[2] or ""),
                                    "severity": str(r[3] or "unknown"),
                                    "vendor": str(r[4] or ""),
                                    "tenant_id": str(r[5] or ""),
                                    "source": "security_event_ingest",
                                }
                            )
                    except Exception:
                        pass
                    # Fallback: security_events
                    if not rows:
                        try:
                            raw2 = db.execute(
                                sql_text(
                                    """
                                    SELECT id, event_time, severity, details, tenant_id
                                    FROM security_events
                                    WHERE id > :cursor
                                    ORDER BY id ASC
                                    LIMIT 50
                                    """
                                ),
                                {"cursor": cursor},
                            ).fetchall()
                            for r in raw2 or []:
                                rows.append(
                                    {
                                        "id": int(r[0] or 0),
                                        "event_time": str(r[1] or ""),
                                        "event_type": _security_type_from_details(r[3]),
                                        "severity": str(r[2] or "unknown"),
                                        "vendor": "",
                                        "tenant_id": str(r[4] or ""),
                                        "source": "security_events",
                                    }
                                )
                        except Exception:
                            pass
            except Exception:
                pass

            for row in rows:
                new_id = int(row.get("id") or 0)
                if new_id > cursor:
                    cursor = new_id
                yield f"data: {json.dumps(row)}\n\n"

            if not rows:
                # Heartbeat keeps the connection alive
                yield ": heartbeat\n\n"

            await asyncio.sleep(3)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/recommend-latency")
def recommend_latency_api(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Return p50/p95/p99 latency percentiles for the recommend pipeline (warm vs cold)."""
    _ = role
    from src.app.observability.latency_tracker import get_recommend_tracker
    return get_recommend_tracker().summary()



# ── Investor metrics (B1) — ONE screen composing the aggregates that already exist ─────────────────────
# "Show me the numbers": exec KPIs + bounded-autonomy proof + governance pulse + procurement cycle time +
# the capability-gap ledger. Mostly REUSE: each block delegates to an existing service/route function and
# degrades independently (a failed block returns its error note, never a 500 for the whole screen).

@router.get("/investor-metrics")
def investor_metrics(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone
    out: Dict[str, Any] = {"window_days": int(days), "sections": {}}
    _end = datetime.now(timezone.utc).date()
    _start = _end - timedelta(days=int(days))

    # 1) Executive KPIs (revenue, margin%, refund/chargeback, autonomy%, MTTD/MTTR)
    try:
        out["sections"]["executive"] = executive_pulse_api(start=_start.isoformat(), end=_end.isoformat(), role=role)
    except Exception as exc:
        logger.debug("investor-metrics executive block failed: %s", exc)
        out["sections"]["executive"] = {"error": "unavailable"}

    # 2) Bounded autonomy — the RFQ decision trail + the market-adaptation gate (allow vs governed-deny)
    try:
        from src.app.services.adaptive_action_gate import load_recent_audit
        with db_session() as db:
            rfq = load_recent_audit(db, limit=500, action_type="supplier_rfq_send")
            mkt = load_recent_audit(db, limit=500, action_type="adjust_ranking")
        out["sections"]["autonomy"] = {
            "rfq": {"sent": sum(1 for r in rfq if r["decision"] == "allow"),
                    "escalated": sum(1 for r in rfq if r["decision"] != "allow")},
            "market_adaptation": {"allowed": sum(1 for r in mkt if r["decision"] == "allow"),
                                  "denied_governed": sum(1 for r in mkt if r["decision"] == "deny")},
        }
        # M6 close-the-loop: outcomes attributed BACK to each adaptation (conversion value per
        # exposure segment) + the terminal keep/revert verdicts — "the adaptations are measured".
        try:
            from src.app.services.market_outcome import load_attribution_rollup, load_recent_outcomes
            with db_session() as db:
                out["sections"]["autonomy"]["adaptation_outcomes"] = {
                    "attributed": load_attribution_rollup(db, limit=12),
                    "verdicts": load_recent_outcomes(db, limit=6),
                }
        except Exception as exc:
            logger.debug("investor-metrics adaptation-outcomes block failed: %s", exc)
    except Exception as exc:
        logger.debug("investor-metrics autonomy block failed: %s", exc)
        out["sections"]["autonomy"] = {"error": "unavailable"}

    # 3) Market-intelligence governance pulse (signals → findings → shadow decisions → experiments)
    try:
        from src.app.services.governance_pulse import governance_pulse
        with db_session() as db:
            out["sections"]["governance"] = governance_pulse(db)
    except Exception as exc:
        logger.debug("investor-metrics governance block failed: %s", exc)
        out["sections"]["governance"] = {"error": "unavailable"}

    # 4) Procurement cycle time — median/p90 hours from first to last bitemporal transition per case
    try:
        with db_session() as db:
            rows = db.execute(sql_text(
                "SELECT case_id, MIN(valid_from) AS a, MAX(valid_from) AS b "
                "FROM fulfillment_case_version GROUP BY case_id HAVING COUNT(*) >= 2"
            )).fetchall()
        durs: List[float] = []
        for _cid, a, b in rows:
            try:
                ta = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
                tb = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
                durs.append(max(0.0, (tb - ta).total_seconds() / 3600.0))
            except (TypeError, ValueError):
                continue
        durs.sort()
        n = len(durs)
        out["sections"]["procurement"] = {
            "cases_measured": n,
            "cycle_hours_median": round(durs[n // 2], 2) if n else None,
            "cycle_hours_p90": round(durs[min(n - 1, int(n * 0.9))], 2) if n else None,
        }
    except Exception as exc:
        logger.debug("investor-metrics procurement block failed: %s", exc)
        out["sections"]["procurement"] = {"error": "unavailable"}

    # 5) Capability-gap ledger — what buyers asked for that we couldn't/wouldn't do (the QA roadmap feed)
    try:
        from src.app.services.capability_gap import gap_rollup
        with db_session() as db:
            out["sections"]["capability_gaps"] = gap_rollup(db, limit=10)
    except Exception as exc:
        logger.debug("investor-metrics capability block failed: %s", exc)
        out["sections"]["capability_gaps"] = {"error": "unavailable"}

    # 6) Fraud screening volume — per-order fraud_score decision events (blocked = level high)
    try:
        with db_session() as db:
            frow = db.execute(sql_text(
                "SELECT COUNT(*), SUM(CASE WHEN payload LIKE '%\"level\": \"high\"%' "
                "OR payload LIKE '%\"level\":\"high\"%' THEN 1 ELSE 0 END) "
                "FROM decision_trace_events WHERE event_type='fraud_score'")).fetchone()
        out["sections"]["fraud"] = {"scored": int(frow[0] or 0), "high_risk": int(frow[1] or 0)}
    except Exception as exc:
        logger.debug("investor-metrics fraud block failed: %s", exc)
        out["sections"]["fraud"] = {"error": "unavailable"}

    return out
