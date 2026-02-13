from __future__ import annotations

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.supply_chain_monitor import get_monitor


router = APIRouter(prefix="/api/v1/admin/supply_chain", tags=["admin", "supply_chain"])


@router.post("/ingest")
def ingest_provider_event(payload: Dict[str, Any], role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Ingest provider telemetry: { provider, latency_ms, status, schema_ok }"""
    try:
        provider = str(payload.get("provider") or "unknown")
        latency_ms = float(payload.get("latency_ms") or 0.0)
        status = str(payload.get("status") or "ok")
        schema_ok = bool(payload.get("schema_ok", True))
        mon = get_monitor()
        mon.ingest_event(provider, latency_ms, status, schema_ok)
        return {"ingested": True, "provider": provider}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/anomalies/{provider}")
def provider_anomalies(provider: str, lat_threshold_ms: float = 2000.0, sigma: float = 3.0, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    mon = get_monitor()
    res = mon.detect_anomalies(provider, lat_threshold_ms=lat_threshold_ms, sigma=sigma)
    return res
