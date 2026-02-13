from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import Any, Dict
import os

from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.drift_daily_metrics import recompute_daily_metrics, query_daily_metrics, recompute_calibration_snapshots
from src.app.observability.metrics import get_recommendation_snapshot


router = APIRouter(prefix="/api/v1/admin/drift", tags=["admin-drift"])


@router.post("/daily/recompute")
def recompute(days: int = 30, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Recompute + persist drift daily metrics (MVP)."""
    return recompute_daily_metrics(days=days)


@router.get("/daily")
def query(domain: str | None = None, days: int = 30, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Query drift daily metrics (MVP)."""
    return query_daily_metrics(domain=domain, days=days)


@router.get("/recommendation/ltr_snapshot")
def recommendation_ltr_snapshot(role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Admin snapshot for LTR rollout KPIs: nDCG proxy, recall proxy, latency, counts."""
    rows = get_recommendation_snapshot()
    return {"status": "ok", "items": rows}


@router.post("/calibration/recompute")
def recompute_calibration(days: int = 30, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Recompute calibration ECE snapshots for intent/CV/anomaly/recommendation."""
    return recompute_calibration_snapshots(days=days)


@router.get("/calibration/alerts")
def calibration_alerts(days: int = 30, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Alert-oriented view for calibration drift thresholds."""
    rows = query_daily_metrics(days=days)
    ece_map: Dict[str, float] = {}
    for item in rows.get("items") or []:
        if item.get("metric_key") != "calibration_ece":
            continue
        dom = str(item.get("domain") or "unknown")
        ece_map[dom] = max(ece_map.get(dom, 0.0), float(item.get("metric_value") or 0.0))
    threshold = float(os.environ.get("CALIBRATION_ECE_ALERT_THRESHOLD", "0.12") or 0.12)
    alerts = {k: (float(v) >= threshold) for k, v in ece_map.items()}
    return {"status": "ok", "threshold_ece": threshold, "ece": ece_map, "alerts": alerts}
