from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

_log = logging.getLogger("shopsquire.tasks.anomaly")

def _load_metric_histories(*, limit_per_metric: int = 200) -> Dict[str, list[float]]:
    from src.app.models.db import db_session
    from sqlalchemy import text as _sql

    histories: Dict[str, list[float]] = {}
    try:
        with db_session() as db:
            rows = db.execute(
                _sql(
                    "SELECT metric_name, metric_value "
                    "FROM anomaly_metric_history "
                    "ORDER BY snapshot_ts DESC"
                )
            ).fetchall()
    except Exception as exc:
        _log.debug("anomaly history load failed: %s", exc)
        return histories

    for row in rows or []:
        name = str(row[0] or "")
        if not name:
            continue
        bucket = histories.setdefault(name, [])
        if len(bucket) >= limit_per_metric:
            continue
        try:
            bucket.append(float(row[1]))
        except Exception:
            continue
    for name, values in list(histories.items()):
        histories[name] = list(reversed(values))
    return histories


def _persist_metric_snapshot(metrics: Dict[str, Any]) -> None:
    from src.app.models.db import db_session
    from sqlalchemy import text as _sql

    snapshot_ts = str(metrics.get("snapshot_ts") or "")
    if not snapshot_ts:
        return
    try:
        with db_session() as db:
            for metric_name, value in (metrics or {}).items():
                if metric_name == "snapshot_ts" or not isinstance(value, (int, float)):
                    continue
                db.execute(
                    _sql(
                        "INSERT INTO anomaly_metric_history (metric_name, metric_value, snapshot_ts) "
                        "VALUES (:metric_name, :metric_value, :snapshot_ts) "
                        "ON CONFLICT (metric_name, snapshot_ts) DO UPDATE "
                        "SET metric_value = EXCLUDED.metric_value"
                    ),
                    {
                        "metric_name": str(metric_name),
                        "metric_value": float(value),
                        "snapshot_ts": snapshot_ts,
                    },
                )
            db.commit()
    except Exception:
        try:
            with db_session() as db:
                for metric_name, value in (metrics or {}).items():
                    if metric_name == "snapshot_ts" or not isinstance(value, (int, float)):
                        continue
                    db.execute(
                        _sql(
                            "INSERT INTO anomaly_metric_history (metric_name, metric_value, snapshot_ts) "
                            "VALUES (:metric_name, :metric_value, :snapshot_ts) "
                            "ON CONFLICT (metric_name, snapshot_ts) DO UPDATE "
                            "SET metric_value = EXCLUDED.metric_value"
                        ),
                        {
                            "metric_name": str(metric_name),
                            "metric_value": float(value),
                            "snapshot_ts": snapshot_ts,
                        },
                    )
                db.commit()
        except Exception as exc:
            _log.debug("anomaly history persist failed: %s", exc)


def _collect_metrics_snapshot() -> Dict[str, Any]:
    """Query DB for hourly order/refund/fraud aggregates for anomaly detection."""
    from src.app.models.db import db_session
    from sqlalchemy import text as _sql

    metrics: Dict[str, Any] = {}
    try:
        with db_session() as db:
            # Orders in last hour
            row = db.execute(
                _sql("SELECT COUNT(*) FROM orders WHERE created_at >= NOW() - INTERVAL '1 hour'")
            ).fetchone()
            metrics["orders_last_hour"] = int(row[0]) if row else 0

            # Refunds in last hour
            try:
                row = db.execute(
                    _sql("SELECT COUNT(*) FROM refunds WHERE created_at >= NOW() - INTERVAL '1 hour'")
                ).fetchone()
                metrics["refunds_last_hour"] = int(row[0]) if row else 0
            except Exception:
                metrics["refunds_last_hour"] = 0

            # Fraud-flagged orders in last hour
            try:
                row = db.execute(
                    _sql(
                        "SELECT COUNT(*) FROM orders "
                        "WHERE fraud_flag = true AND created_at >= NOW() - INTERVAL '1 hour'"
                    )
                ).fetchone()
                metrics["fraud_flags_last_hour"] = int(row[0]) if row else 0
            except Exception:
                # Try decision_logs fallback
                try:
                    row = db.execute(
                        _sql(
                            "SELECT COUNT(*) FROM decision_logs "
                            "WHERE agent_name LIKE '%fraud%' "
                            "AND created_at >= NOW() - INTERVAL '1 hour'"
                        )
                    ).fetchone()
                    metrics["fraud_flags_last_hour"] = int(row[0]) if row else 0
                except Exception:
                    metrics["fraud_flags_last_hour"] = 0

            # High-risk incidents in last hour
            try:
                row = db.execute(
                    _sql(
                        "SELECT COUNT(*) FROM incidents "
                        "WHERE severity IN ('high', 'critical') "
                        "AND created_at >= NOW() - INTERVAL '1 hour'"
                    )
                ).fetchone()
                metrics["high_risk_incidents_last_hour"] = int(row[0]) if row else 0
            except Exception:
                metrics["high_risk_incidents_last_hour"] = 0

    except Exception as exc:
        _log.warning("anomaly metrics collection partial failure: %s", exc)

    metrics["snapshot_ts"] = datetime.now(timezone.utc).isoformat()
    return metrics


@celery_app.task(name="src.app.tasks.anomaly_tasks.anomaly_hourly_snapshot")
def anomaly_hourly_snapshot() -> Dict[str, Any]:
    """Hourly snapshot: collect order/refund/fraud metrics and run anomaly detection.

    Feeds AnomalyDetector with at least MIN_SAMPLES=12 data points over 12 hours
    before the ensemble (IsolationForest + LOF + Prophet) becomes active.
    Anomalies above threshold are logged to the decision trace.
    """
    enabled = os.getenv("ANOMALY_SNAPSHOT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
    if not enabled:
        return {"status": "disabled"}

    try:
        metrics = _collect_metrics_snapshot()
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:200]}

    results: Dict[str, Any] = {"status": "ok", "metrics": metrics, "anomalies": []}

    try:
        from src.app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector()
        numeric_metrics = {
            metric_name: float(value)
            for metric_name, value in (metrics or {}).items()
            if metric_name != "snapshot_ts" and isinstance(value, (int, float))
        }
        histories = _load_metric_histories(limit_per_metric=detector.MAX_HISTORY)
        detections = detector.detect_metrics(numeric_metrics, histories=histories)
        for detection in detections:
            results["anomalies"].append({
                "metric": detection.domain,
                "value": detection.value,
                "score": detection.confidence,
                "severity": detection.severity,
                "method_votes": detection.method_votes,
                "plain_english": detection.plain_english,
                "ts": metrics["snapshot_ts"],
            })
        _persist_metric_snapshot(metrics)
    except ImportError:
        results["detector"] = "unavailable"
    except Exception as exc:
        results["detector_error"] = str(exc)[:200]

    # Log anomalies to decision trace for observability
    if results["anomalies"]:
        try:
            from src.app.services.decision_log import log_trace_event
            import uuid
            log_trace_event(
                trace_id=str(uuid.uuid4()),
                event_type="anomaly_detected",
                source_type="agent",
                source_id="AnomalyDetector",
                target_type="system",
                target_id=None,
                payload={"anomalies": results["anomalies"], "snapshot_ts": metrics["snapshot_ts"]},
            )
        except Exception:
            pass
        _log.warning(
            "Anomaly snapshot: %d anomaly(s) detected — %s",
            len(results["anomalies"]),
            [a["metric"] for a in results["anomalies"]],
        )
    else:
        _log.info("Anomaly snapshot: no anomalies. metrics=%s", metrics)

    return results
