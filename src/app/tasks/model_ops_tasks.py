from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.demand_forecast import DemandForecaster
from src.app.services.recommendation_als import train_recommend_als
from src.app.workers.celery_app import celery_app


def _ensure_ml_governance_table(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ml_retrain_governance_runs (
                    id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    metadata_json TEXT
                )
                """
            )
        )
    except Exception:
        pass


def _record_governance_run(*, run_type: str, status: str, metadata: Dict[str, Any]) -> None:
    try:
        with db_session() as db:
            _ensure_ml_governance_table(db)
            db.execute(
                text(
                    """
                    INSERT INTO ml_retrain_governance_runs (id, run_type, status, metadata_json)
                    VALUES (:id, :run_type, :status, :metadata_json)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_type": str(run_type or "unknown"),
                    "status": str(status or "unknown"),
                    "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
                },
            )
            db.commit()
    except Exception:
        pass


def _sample_skus_for_forecast(limit: int = 40) -> List[str]:
    out: List[str] = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT sku
                    FROM recommend_interactions
                    WHERE sku IS NOT NULL AND sku <> ''
                    GROUP BY sku
                    ORDER BY COUNT(*) DESC
                    LIMIT :lim
                    """
                ),
                {"lim": max(5, min(int(limit or 40), 200))},
            ).fetchall()
            out = [str(r[0]) for r in (rows or []) if str(r[0] or "").strip()]
    except Exception:
        out = []
    return out


@celery_app.task(bind=True, name="src.app.tasks.model_ops_tasks.train_recommend_cf_nightly")
def train_recommend_cf_nightly(self) -> Dict[str, Any]:
    lookback_days = 120
    topk_per_user = 80
    factors = 12
    iters = 6
    try:
        out = train_recommend_als(
            lookback_days=lookback_days,
            topk_per_user=topk_per_user,
            factors=factors,
            iters=iters,
        )
        _record_governance_run(
            run_type="recommend_cf_train",
            status=str(out.get("status") or "ok"),
            metadata={
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "params": {
                    "lookback_days": lookback_days,
                    "topk_per_user": topk_per_user,
                    "factors": factors,
                    "iters": iters,
                },
                "result": out,
            },
        )
        return {"status": "ok", "job": out}
    except Exception as exc:
        _record_governance_run(
            run_type="recommend_cf_train",
            status="failed",
            metadata={"error": str(exc)[:300]},
        )
        return {"status": "failed", "error": str(exc)[:300]}


@celery_app.task(bind=True, name="src.app.tasks.model_ops_tasks.snapshot_forecast_governance")
def snapshot_forecast_governance(self) -> Dict[str, Any]:
    skus = _sample_skus_for_forecast(limit=40)
    if not skus:
        out = {"status": "no_data", "skus": 0}
        _record_governance_run(run_type="forecast_governance_snapshot", status="no_data", metadata=out)
        return out

    forecaster = DemandForecaster()
    mape_vals: List[float] = []
    quarantined = 0
    methods: Dict[str, int] = {}
    for sku in skus:
        try:
            fc = forecaster.forecast_sku(sku, horizon_days=30)
            meta = fc.meta if isinstance(fc.meta, dict) else {}
            m = meta.get("mape_proxy")
            if m is not None:
                mape_vals.append(float(m))
            quarantined += int(meta.get("quarantined_points") or 0)
            method = str(meta.get("method") or "unknown")
            methods[method] = int(methods.get(method, 0)) + 1
        except Exception:
            continue
    avg_mape = round(sum(mape_vals) / max(1, len(mape_vals)), 4) if mape_vals else None
    status = "ok" if mape_vals else "partial"
    out = {
        "status": status,
        "skus_sampled": len(skus),
        "mape_count": len(mape_vals),
        "avg_mape_proxy": avg_mape,
        "quarantined_points": quarantined,
        "methods": methods,
    }
    _record_governance_run(run_type="forecast_governance_snapshot", status=status, metadata=out)
    return out
