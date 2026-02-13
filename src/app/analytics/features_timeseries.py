from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Any, List

from sqlalchemy import text

from src.app.analytics.anomaly import adaptive_ewma, isolation_forest_score


def security_timeseries(db, days: int = 14) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = []
    try:
        dialect = getattr(db.bind.dialect, "name", "")
    except Exception:
        dialect = ""
    if "postgres" in dialect:
        sql = """
            SELECT time_bucket('1 day', time) AS bucket,
                   COUNT(*) AS count,
                   AVG(risk_adj) AS risk_avg
            FROM security_observer_timeseries
            WHERE time >= :since
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        rows = db.execute(text(sql), {"since": since}).fetchall()
    else:
        sql = """
            SELECT DATE(time) AS bucket,
                   COUNT(*) AS count,
                   AVG(risk_adj) AS risk_avg
            FROM security_observer_timeseries
            WHERE time >= :since
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        rows = db.execute(text(sql), {"since": since.isoformat()}).fetchall()

    points: List[Dict[str, Any]] = []
    counts: List[float] = []
    for bucket, count, risk_avg in rows:
        points.append({"bucket": str(bucket), "count": int(count or 0), "risk_avg": float(risk_avg or 0.0)})
        counts.append(float(count or 0))

    latest = counts[-1] if counts else 0.0
    ewma = adaptive_ewma(counts) if counts else 0.0
    anomaly_score = isolation_forest_score(counts, latest) if counts else 0.0
    is_spike = latest > ewma * 1.5 if ewma else False

    return {
        "window_days": days,
        "series": points,
        "baseline_ewma": round(float(ewma), 4),
        "latest": latest,
        "anomaly_score": round(float(anomaly_score), 4),
        "spike": is_spike,
    }
