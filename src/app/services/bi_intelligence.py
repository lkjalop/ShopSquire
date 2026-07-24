from __future__ import annotations

import json
import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.bi_intelligence")


def _safe_num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _in_window(value: Any, *, days: int, now: datetime | None = None) -> bool:
    parsed = _utc(value)
    if parsed is None:
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return current - timedelta(days=max(1, int(days))) <= parsed <= current + timedelta(minutes=5)


def _unavailable(metric: str, *, tenant_id: str, window_days: int, reason: str) -> Dict[str, Any]:
    return {
        "metric": metric,
        "tenant_id": tenant_id,
        "window_days": int(window_days),
        "status": "unavailable",
        "reason": reason,
    }


def margin_intelligence(window_days: int = 90, *, tenant_id: str) -> Dict[str, Any]:
    """Returns-adjusted revenue by SKU.

    Gross margin remains unavailable until a validated landed-cost fact can be
    matched to the sale. This endpoint must not silently treat seeded cost as COGS.
    """
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required")
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT event_type, sku, value, quantity, currency, occurred_at
                    FROM marketing_event_fact
                    WHERE tenant_id=:tenant AND status='active'
                      AND event_type IN ('purchase','return','refund')
                    ORDER BY occurred_at DESC
                    LIMIT 10000
                    """
                ),
                {"tenant": tenant},
            ).fetchall()
    except Exception as exc:
        logger.warning("margin intelligence unavailable for tenant %s: %s", tenant, exc)
        return _unavailable(
            "margin_intelligence", tenant_id=tenant, window_days=window_days,
            reason="canonical_marketing_facts_unavailable",
        ) | {"sku_count": 0, "low_margin_count": 0, "top": []}
    rows = [row for row in rows if _in_window(row[5], days=window_days)]
    aggregates: Dict[tuple[str, str], Dict[str, Any]] = {}
    for event_type, raw_sku, value, quantity, currency, _occurred_at in rows:
        sku = str(raw_sku or "").strip()
        ccy = str(currency or "").strip().upper()
        if not sku or not ccy or value is None:
            continue
        bucket = aggregates.setdefault((sku, ccy), {
            "sku": sku, "currency": ccy, "revenue_cents": 0,
            "returned_cents": 0, "net_revenue_cents": 0, "qty": 0,
        })
        amount = max(0, int(round(float(value))))
        units = max(1, int(quantity or 1))
        if str(event_type) == "purchase":
            bucket["revenue_cents"] += amount
            bucket["qty"] += units
        else:
            bucket["returned_cents"] += amount
            bucket["qty"] = max(0, int(bucket["qty"]) - units)
        bucket["net_revenue_cents"] = (
            int(bucket["revenue_cents"]) - int(bucket["returned_cents"]))
    by_sku: List[Dict[str, Any]] = []
    for bucket in aggregates.values():
        by_sku.append(bucket | {
            "cost_cents": None,
            "margin_cents": None,
            "margin_pct": None,
            "discount_risk": None,
            "economics_status": "insufficient_data",
            "economics_reason": "matched_landed_cogs_required",
        })
    by_sku.sort(key=lambda item: int(item["net_revenue_cents"]), reverse=True)
    return {
        "tenant_id": tenant,
        "window_days": int(window_days),
        "status": "observed" if by_sku else "insufficient_data",
        "sku_count": len(by_sku),
        "low_margin_count": None,
        "top": by_sku[:100],
    }


def supplier_scorecard(window_days: int = 60, *, tenant_id: str) -> Dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required")
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT supplier_id, score, payload, created_at
                    FROM supplier_score_audits
                    WHERE tenant_id=:tenant
                    ORDER BY created_at DESC
                    LIMIT 10000
                    """
                ),
                {"tenant": tenant},
            ).fetchall()
    except Exception as exc:
        logger.warning("supplier scorecard unavailable for tenant %s: %s", tenant, exc)
        return _unavailable(
            "supplier_scorecard", tenant_id=tenant, window_days=window_days,
            reason="tenant_scoped_supplier_audits_unavailable",
        ) | {"suppliers": []}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for supplier_id, score, raw_payload, created_at in rows:
        if not _in_window(created_at, days=window_days):
            continue
        try:
            payload = json.loads(raw_payload or "{}") if isinstance(raw_payload, str) else dict(raw_payload or {})
        except (TypeError, ValueError):
            payload = {}
        sid = str(supplier_id or "").strip()
        if sid:
            grouped.setdefault(sid, []).append({"score": score, "payload": payload})
    out = []
    for sid, audits in grouped.items():
        on_times = [_safe_num(item["payload"].get("on_time_rate")) for item in audits]
        defects = [_safe_num(item["payload"].get("defect_rate")) for item in audits]
        leads = [_safe_num(item["payload"].get("lead_time")) for item in audits]
        quality = [_safe_num(item.get("score")) for item in audits]
        on_time = max(0.0, min(1.0, sum(on_times) / max(1, len(on_times))))
        defect = max(0.0, min(1.0, sum(defects) / max(1, len(defects))))
        quality_avg = sum(quality) / max(1, len(quality))
        score = (0.45 * on_time) + (0.35 * max(0.0, 1.0 - defect)) + (
            0.20 * max(0.0, min(1.0, quality_avg / 2.0)))
        out.append(
            {
                "supplier_id": sid,
                "score": round(score, 4),
                "quality_score_raw": round(quality_avg, 4),
                "lead_time_avg": round(sum(leads) / max(1, len(leads)), 2),
                "on_time_avg": round(on_time, 4),
                "defect_rate_avg": round(defect, 4),
                "audits": len(audits),
            }
        )
    out.sort(key=lambda item: float(item["score"]), reverse=True)
    return {
        "tenant_id": tenant,
        "window_days": int(window_days),
        "status": "observed" if out else "insufficient_data",
        "suppliers": out,
    }


def clv_prediction(window_days: int = 365, *, tenant_id: str) -> Dict[str, Any]:
    """Tenant-scoped RFM estimate, not a trained lifetime-value prediction."""
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required")
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT event_type, subject_hash, value, currency, occurred_at
                    FROM marketing_event_fact
                    WHERE tenant_id=:tenant AND status='active'
                      AND event_type IN ('purchase','return','refund')
                    ORDER BY occurred_at DESC
                    LIMIT 20000
                    """
                ),
                {"tenant": tenant},
            ).fetchall()
    except Exception as exc:
        logger.warning("RFM value unavailable for tenant %s: %s", tenant, exc)
        return _unavailable(
            "rfm_value_estimate", tenant_id=tenant, window_days=window_days,
            reason="canonical_customer_events_unavailable",
        ) | {"users": [], "method": "rfm_heuristic_v1"}
    now = datetime.now(timezone.utc)
    aggregates: Dict[tuple[str, str], Dict[str, Any]] = {}
    for event_type, subject_hash, value, currency, occurred_at in rows:
        uid = str(subject_hash or "").strip()
        ccy = str(currency or "").strip().upper()
        occurred = _utc(occurred_at)
        if not uid or not ccy or value is None or occurred is None:
            continue
        if not _in_window(occurred, days=window_days, now=now):
            continue
        bucket = aggregates.setdefault((uid, ccy), {
            "uid_hash": uid, "currency": ccy, "orders_n": 0,
            "revenue_cents": 0, "returned_cents": 0, "last_order_at": None,
        })
        if str(event_type) == "purchase":
            bucket["orders_n"] += 1
            bucket["revenue_cents"] += max(0, int(round(float(value))))
            if bucket["last_order_at"] is None or occurred > bucket["last_order_at"]:
                bucket["last_order_at"] = occurred
        else:
            bucket["returned_cents"] += max(0, int(round(float(value))))
    users = []
    for bucket in aggregates.values():
        orders_n = int(bucket["orders_n"])
        if orders_n <= 0 or bucket["last_order_at"] is None:
            continue
        revenue = max(0, int(bucket["revenue_cents"]) - int(bucket["returned_cents"]))
        recency_days = max(0.0, (now - bucket["last_order_at"]).total_seconds() / 86400.0)
        avg_order = revenue / float(orders_n)
        retention = math.exp(-recency_days / 120.0)
        clv = avg_order * orders_n * (1.0 + retention)
        users.append(
            {
                "uid_hash": bucket["uid_hash"],
                "currency": bucket["currency"],
                "orders_n": int(orders_n),
                "revenue_cents": int(revenue),
                "recency_days": round(recency_days, 2),
                "retention_score": round(retention, 4),
                "estimated_value_cents": int(clv),
                "estimate_status": "estimated",
            }
        )
    users.sort(key=lambda x: x["estimated_value_cents"], reverse=True)
    return {
        "tenant_id": tenant,
        "window_days": int(window_days),
        "status": "estimated" if users else "insufficient_data",
        "method": "rfm_heuristic_v1",
        "users": users[:500],
    }


def churn_prediction(window_days: int = 180, *, tenant_id: str) -> Dict[str, Any]:
    clv = clv_prediction(window_days=window_days, tenant_id=tenant_id)
    out = []
    for u in clv.get("users", []):
        recency = float(u.get("recency_days") or 0.0)
        frequency = float(u.get("orders_n") or 1.0) / max(1.0, window_days / 30.0)
        monetary = float(u.get("revenue_cents") or 0.0) / max(1.0, float(u.get("orders_n") or 1.0))
        # Simple RFM-derived hazard score.
        risk = (0.55 * min(1.0, recency / 90.0)) + (0.30 * max(0.0, 1.0 - min(1.0, frequency / 2.0))) + (
            0.15 * max(0.0, 1.0 - min(1.0, monetary / 200000.0))
        )
        out.append(
            {
                "uid_hash": u.get("uid_hash"),
                "currency": u.get("currency"),
                "rfm": {"recency_days": round(recency, 2), "frequency_per_month": round(frequency, 3), "avg_order_cents": int(monetary)},
                "churn_risk": round(max(0.0, min(1.0, risk)), 4),
                "estimate_status": "estimated",
            }
        )
    out.sort(key=lambda x: x["churn_risk"], reverse=True)
    return {
        "tenant_id": str(tenant_id),
        "window_days": int(window_days),
        "status": "estimated" if out else clv.get("status", "insufficient_data"),
        "method": "rfm_risk_heuristic_v1",
        "users": out[:500],
    }


def seasonal_anomaly_with_causal_attribution(series: List[float], covariates: Dict[str, List[float]] | None = None) -> Dict[str, Any]:
    vals = [float(v) for v in (series or [])]
    if len(vals) < 14:
        return {"status": "insufficient_data", "anomalies": []}
    # 7-day seasonal decomposition approximation.
    season = []
    for i in range(len(vals)):
        same_phase = [vals[j] for j in range(i % 7, len(vals), 7)]
        season.append(sum(same_phase) / max(1, len(same_phase)))
    trend = []
    win = 7
    for i in range(len(vals)):
        lo = max(0, i - win + 1)
        chunk = vals[lo : i + 1]
        trend.append(sum(chunk) / max(1, len(chunk)))
    resid = [vals[i] - trend[i] - (season[i] - (sum(season) / len(season))) for i in range(len(vals))]
    mean = sum(resid) / len(resid)
    var = sum((r - mean) ** 2 for r in resid) / max(1, len(resid) - 1)
    std = math.sqrt(max(1e-9, var))
    anomalies = []
    for i, r in enumerate(resid):
        z = (r - mean) / std
        if abs(z) >= 2.8:
            anomalies.append({"index": i, "zscore": round(z, 4), "residual": round(r, 4)})
    # Simple causal attribution: correlation with covariates at anomaly points.
    causes = []
    cov = covariates if isinstance(covariates, dict) else {}
    if anomalies and cov:
        idxs = [int(a["index"]) for a in anomalies]
        for name, seq in cov.items():
            arr = [float(x) for x in (seq or [])]
            if len(arr) != len(vals):
                continue
            num = 0.0
            den_a = 0.0
            den_b = 0.0
            for i in idxs:
                a = resid[i]
                b = arr[i]
                num += a * b
                den_a += a * a
                den_b += b * b
            corr = num / math.sqrt(max(1e-9, den_a * den_b)) if den_a > 0 and den_b > 0 else 0.0
            causes.append({"factor": str(name), "correlation": round(float(corr), 4)})
        causes.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    return {"status": "ok", "anomaly_count": len(anomalies), "anomalies": anomalies[:30], "causal_factors": causes[:5]}
