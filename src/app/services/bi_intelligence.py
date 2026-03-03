from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session


def _safe_num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def margin_intelligence(window_days: int = 90) -> Dict[str, Any]:
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT sku,
                           SUM(COALESCE(revenue_cents,0)) AS revenue_cents,
                           SUM(COALESCE(cost_cents,0)) AS cost_cents,
                           SUM(COALESCE(quantity,1)) AS qty
                    FROM sales_metrics
                    WHERE datetime(event_time) >= datetime('now', :window)
                    GROUP BY sku
                    ORDER BY revenue_cents DESC
                    LIMIT 500
                    """
                ),
                {"window": f"-{max(7, int(window_days))} days"},
            ).fetchall()
    except Exception:
        rows = []
    by_sku: List[Dict[str, Any]] = []
    for r in rows or []:
        sku = str(r[0] or "").strip()
        rev = _safe_num(r[1])
        cost = _safe_num(r[2])
        qty = max(1.0, _safe_num(r[3], 1.0))
        margin = rev - cost
        margin_pct = (margin / rev) if rev > 0 else 0.0
        by_sku.append(
            {
                "sku": sku,
                "revenue_cents": int(rev),
                "cost_cents": int(cost),
                "qty": int(qty),
                "margin_cents": int(margin),
                "margin_pct": round(margin_pct, 4),
                "discount_risk": bool(margin_pct < 0.1 and rev > 0),
            }
        )
    low_margin = [x for x in by_sku if x["discount_risk"]]
    return {"window_days": int(window_days), "sku_count": len(by_sku), "low_margin_count": len(low_margin), "top": by_sku[:100]}


def supplier_scorecard(window_days: int = 60) -> Dict[str, Any]:
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT supplier_id,
                           AVG(COALESCE(score,0)) AS quality_score,
                           AVG(COALESCE(json_extract(payload,'$.lead_time'), 0)) AS lead_time_avg,
                           AVG(COALESCE(json_extract(payload,'$.on_time_rate'), 0)) AS on_time_avg,
                           AVG(COALESCE(json_extract(payload,'$.defect_rate'), 0)) AS defect_rate_avg,
                           COUNT(*) AS audits
                    FROM supplier_score_audits
                    WHERE datetime(created_at) >= datetime('now', :window)
                    GROUP BY supplier_id
                    ORDER BY quality_score DESC
                    """
                ),
                {"window": f"-{max(7, int(window_days))} days"},
            ).fetchall()
    except Exception:
        rows = []
    out = []
    for r in rows or []:
        sid = str(r[0] or "").strip()
        if not sid:
            continue
        on_time = max(0.0, min(1.0, _safe_num(r[3])))
        defect = max(0.0, min(1.0, _safe_num(r[4])))
        score = (0.45 * on_time) + (0.35 * max(0.0, 1.0 - defect)) + (0.20 * max(0.0, min(1.0, _safe_num(r[1]) / 2.0)))
        out.append(
            {
                "supplier_id": sid,
                "score": round(score, 4),
                "quality_score_raw": round(_safe_num(r[1]), 4),
                "lead_time_avg": round(_safe_num(r[2]), 2),
                "on_time_avg": round(on_time, 4),
                "defect_rate_avg": round(defect, 4),
                "audits": int(_safe_num(r[5], 0)),
            }
        )
    return {"window_days": int(window_days), "suppliers": out}


def clv_prediction(window_days: int = 365) -> Dict[str, Any]:
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT uid_hash,
                           COUNT(*) AS orders_n,
                           SUM(COALESCE(order_total_cents,0)) AS revenue_cents,
                           MAX(event_time) AS last_order_at
                    FROM customer_orders
                    WHERE datetime(event_time) >= datetime('now', :window)
                    GROUP BY uid_hash
                    LIMIT 5000
                    """
                ),
                {"window": f"-{max(30, int(window_days))} days"},
            ).fetchall()
    except Exception:
        rows = []
    now = datetime.now(timezone.utc)
    users = []
    for r in rows or []:
        uid = str(r[0] or "").strip()
        if not uid:
            continue
        orders_n = max(1.0, _safe_num(r[1], 1.0))
        revenue = max(0.0, _safe_num(r[2]))
        last = str(r[3] or "")
        recency_days = 30.0
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            recency_days = max(0.0, (now - dt).total_seconds() / 86400.0)
        except Exception:
            pass
        avg_order = revenue / orders_n
        retention = math.exp(-recency_days / 120.0)
        clv = avg_order * orders_n * (1.0 + retention)
        users.append(
            {
                "uid_hash": uid,
                "orders_n": int(orders_n),
                "revenue_cents": int(revenue),
                "recency_days": round(recency_days, 2),
                "retention_score": round(retention, 4),
                "predicted_clv_cents": int(clv),
            }
        )
    users.sort(key=lambda x: x["predicted_clv_cents"], reverse=True)
    return {"window_days": int(window_days), "users": users[:500]}


def churn_prediction(window_days: int = 180) -> Dict[str, Any]:
    clv = clv_prediction(window_days=window_days)
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
                "rfm": {"recency_days": round(recency, 2), "frequency_per_month": round(frequency, 3), "avg_order_cents": int(monetary)},
                "churn_risk": round(max(0.0, min(1.0, risk)), 4),
            }
        )
    out.sort(key=lambda x: x["churn_risk"], reverse=True)
    return {"window_days": int(window_days), "users": out[:500]}


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
