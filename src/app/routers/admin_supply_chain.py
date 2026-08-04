from __future__ import annotations

import logging
import os
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from src.app.security.auth import require_role, get_role_from_key, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.supply_chain_monitor import get_monitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/supply_chain", tags=["admin", "supply_chain"])

# Shared dual-control primitive (extracted to src.app.security.dual_control so the KYV control plane
# reuses the exact same two-person enforcement). Kept a thin local alias for the call sites below.
from src.app.security.dual_control import require_dual_control as _shared_require_dual_control


def _require_dual_control(
    request: Request,
    primary_role: str,
    x_api_key: Optional[str],
    x_approver_token: Optional[str],
) -> None:
    _shared_require_dual_control(request, primary_role, x_api_key, x_approver_token,
                                 action_label="supply_chain_write")


@router.post("/ingest")
def ingest_provider_event(
    payload: Dict[str, Any],
    request: Request,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
    x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
    x_approver_token: Optional[str] = Header(default=None, alias="x-approver-token"),
) -> Dict:
    """Ingest provider telemetry: { provider, latency_ms, status, schema_ok }

    IT-PREV-01: Requires X-Approver-Token from a second owner/developer in non-local envs.
    """
    _require_dual_control(request, role, x_api_key, x_approver_token)
    try:
        provider = str(payload.get("provider") or "unknown")
        latency_ms = float(payload.get("latency_ms") or 0.0)
        status_val = str(payload.get("status") or "ok")
        schema_ok = bool(payload.get("schema_ok", True))
        mon = get_monitor()
        mon.ingest_event(provider, latency_ms, status_val, schema_ok)
        return {"ingested": True, "provider": provider}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/anomalies/{provider}")
def provider_anomalies(provider: str, lat_threshold_ms: float = 2000.0, sigma: float = 3.0, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    mon = get_monitor()
    res = mon.detect_anomalies(provider, lat_threshold_ms=lat_threshold_ms, sigma=sigma)
    return res
