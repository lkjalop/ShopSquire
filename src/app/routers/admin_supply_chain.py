from __future__ import annotations

import logging
import os
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from src.app.security.auth import require_role, get_role_from_key, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.supply_chain_monitor import get_monitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/supply_chain", tags=["admin", "supply_chain"])

_DUAL_CONTROL_ENABLED = os.getenv("SUPPLY_CHAIN_DUAL_CONTROL", "1").lower() not in ("0", "false", "no")


def _require_dual_control(
    request: Request,
    primary_role: str,
    x_api_key: Optional[str],
    x_approver_token: Optional[str],
) -> None:
    """IT-PREV-01 — Supply chain writes require a second approver with a distinct key.

    The approver must hold owner or developer role, and their key must differ
    from the primary requestor's key so a single compromised credential cannot
    approve its own changes.
    """
    if not _DUAL_CONTROL_ENABLED:
        return

    env = str(os.getenv("APP_ENV", "local") or "local").lower()
    if env in ("local", "dev", "development", "test", "testing"):
        return

    if not x_approver_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dual_control_required: supply-chain writes need X-Approver-Token from a second owner/developer",
        )

    # Keys must differ — one person cannot approve their own change.
    if x_approver_token.strip() == (x_api_key or "").strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dual_control_violation: approver token must differ from requestor token",
        )

    approver_role = get_role_from_key(x_approver_token.strip())
    if approver_role not in (ROLE_OWNER, ROLE_DEVELOPER):
        try:
            from src.app.security.insider_threat_detector import InsiderThreatSignal, _emit as _it_emit
            _it_emit(InsiderThreatSignal(
                signal_type="supply_chain_dual_control_bypass_attempt",
                actor=x_api_key or "unknown",
                resource=getattr(request.url, "path", "/admin/supply_chain"),
                severity="critical",
                context={
                    "approver_role": approver_role,
                    "required_roles": [ROLE_OWNER, ROLE_DEVELOPER],
                },
            ))
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dual_control_violation: approver must hold owner or developer role",
        )

    logger.info(
        "supply_chain dual_control_approved primary_role=%s approver_role=%s path=%s",
        primary_role, approver_role, getattr(request.url, "path", ""),
    )


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
