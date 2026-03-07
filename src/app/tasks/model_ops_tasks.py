from __future__ import annotations

import json
import os
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


def _fetch_visual_products(limit: int = 50000) -> tuple[List[Dict[str, Any]], str | None]:
    out: List[Dict[str, Any]] = []
    max_updated_at: str | None = None
    with db_session() as db:
        try:
            rows = db.execute(
                text(
                    "SELECT sku, name, brand, price_cents, specs, COALESCE(updated_at, created_at) AS ts "
                    "FROM products LIMIT :lim"
                ),
                {"lim": int(limit)},
            ).fetchall()
            has_ts = True
        except Exception:
            rows = db.execute(
                text("SELECT sku, name, brand, price_cents, specs FROM products LIMIT :lim"),
                {"lim": int(limit)},
            ).fetchall()
            has_ts = False
        for r in rows or []:
            specs = {}
            if r[4]:
                try:
                    specs = json.loads(r[4]) if isinstance(r[4], str) else r[4]
                except Exception:
                    specs = {}
            if has_ts and len(r) > 5 and r[5] is not None:
                ts = str(r[5])
                if not max_updated_at or ts > max_updated_at:
                    max_updated_at = ts
            out.append(
                {
                    "sku": str(r[0] or ""),
                    "name": str(r[1] or ""),
                    "brand": str(r[2] or ""),
                    "price_cents": int(r[3] or 0),
                    "specs": specs if isinstance(specs, dict) else {},
                }
            )
    return out, max_updated_at


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


@celery_app.task(bind=True, name="src.app.tasks.model_ops_tasks.refresh_visual_search_index")
def refresh_visual_search_index(self) -> Dict[str, Any]:
    enabled = str(os.getenv("VISUAL_SEARCH_REFRESH_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        out = {"status": "disabled"}
        _record_governance_run(run_type="visual_search_index_refresh", status="disabled", metadata=out)
        return out
    try:
        from src.app.services.visual_search import build_index, status as vs_status, try_load_persisted_index

        try_load_persisted_index()
        st = vs_status()
        fresh = not bool(((st.get("freshness") or {}).get("stale")))
        if fresh and int(st.get("index_size") or 0) > 0:
            out = {"status": "skipped_fresh", "index_size": int(st.get("index_size") or 0), "freshness": st.get("freshness")}
            _record_governance_run(run_type="visual_search_index_refresh", status="skipped", metadata=out)
            return out
        products, max_ts = _fetch_visual_products(limit=50000)
        n = build_index(products, persist=True, source="celery_refresh", catalog_max_updated_at=max_ts)
        out = {"status": "ok", "indexed": n, "catalog_size": len(products), "catalog_max_updated_at": max_ts, "post_status": vs_status()}
        _record_governance_run(run_type="visual_search_index_refresh", status="ok", metadata=out)
        return out
    except Exception as exc:
        out = {"status": "failed", "error": str(exc)[:300]}
        _record_governance_run(run_type="visual_search_index_refresh", status="failed", metadata=out)
        return out


@celery_app.task(bind=True, name="src.app.tasks.model_ops_tasks.snapshot_risk_register_daily")
def snapshot_risk_register_daily(self) -> Dict[str, Any]:
    days = max(1, min(365, int(float(os.getenv("RISK_REGISTER_SNAPSHOT_WINDOW_DAYS", "30") or 30))))
    try:
        from src.app.routers.admin_grc import _take_snapshot

        rows = _take_snapshot(days=days)
        out = {"status": "ok", "days": days, "snapshot_count": len(rows)}
        _record_governance_run(run_type="risk_register_snapshot", status="ok", metadata=out)
        return out
    except Exception as exc:
        out = {"status": "failed", "days": days, "error": str(exc)[:300]}
        _record_governance_run(run_type="risk_register_snapshot", status="failed", metadata=out)
        return out
