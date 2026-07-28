from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Dict
import time

from src.app.config import load_feature_flags, get_settings
from src.app.feature_flags import get_flags as _ff_get_flags
from src.app.deps import get_redis
from src.app.services.degradation import cb_is_open, cb_record
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.policy.kill_switch import assert_autonomy_allowed
from src.app.services.inventory_reorder_execution import ReorderBoundaryError


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/health")
def health(redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    flags = _ff_get_flags()
    assert_autonomy_allowed("inventory", flags=flags, source_id="Inventory_Autonomy_Governance_Agent")
    degradation_cfg = flags.get("DEGRADATION", {"enabled": True})
    now_ts = int(time.time())
    cb_open = cb_is_open(redis, "inventory", now_ts) if degradation_cfg.get("enabled", True) else False
    degraded = bool(degradation_cfg.get("force_rules", False) or cb_open)
    try:
        cb_record(redis, "inventory", True, degradation_cfg)
    except Exception:
        cb_record(redis, "inventory", False, degradation_cfg)
        degraded = True
    return {"status": "degraded" if degraded else "ok", "degraded": degraded}


@router.get("/monitor")
def monitor_inventory(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER]))):
    """Return current low-stock alerts detected by the InventoryAgent."""
    try:
        flags = _ff_get_flags()
        assert_autonomy_allowed("inventory", flags=flags, source_id="Inventory_Autonomy_Governance_Agent")
        from src.app.services.inventory_agent import InventoryAgent, ReorderRecommendation
        from src.app.observability.metrics import decisions_events_counter
        agent = InventoryAgent()
        alerts = agent.monitor_stock_levels()
        try:
            decisions_events_counter.inc()
        except Exception:
            pass
        # Serialize dataclasses to dicts
        out = [a.__dict__ if hasattr(a, "__dict__") else a for a in alerts]
        return {"status": "ok", "alerts": out}
    except Exception:
        raise HTTPException(status_code=500, detail="monitoring failed")


@router.get("/alerts")
def alerts(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER]))):
    """Alias for monitor: returns current low-stock alerts.

    Provided for parity with planned endpoint naming.
    """
    try:
        flags = _ff_get_flags()
        assert_autonomy_allowed("inventory", flags=flags, source_id="Inventory_Autonomy_Governance_Agent")
        from src.app.services.inventory_agent import InventoryAgent
        from src.app.observability.metrics import decisions_events_counter
        agent = InventoryAgent()
        alerts = agent.monitor_stock_levels()
        try:
            decisions_events_counter.inc()
        except Exception:
            pass
        out = [a.__dict__ if hasattr(a, "__dict__") else a for a in alerts]
        return {"status": "ok", "alerts": out}
    except Exception:
        raise HTTPException(status_code=500, detail="alerts failed")


class ReorderRequest(BaseModel):
    proposal_id: str


@router.post("/reorder")
def reorder(req: ReorderRequest, request: Request, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER]))):
    """Execute one approved, immutable, server-derived reorder proposal."""
    try:
        flags = _ff_get_flags()
        assert_autonomy_allowed(
            "inventory",
            flags=flags,
            source_id="Inventory_Autonomy_Governance_Agent",
            context={"proposal_id": req.proposal_id},
        )
        from src.app.models.db import db_session
        from src.app.platform.tenant_context import current_tenant_id
        from src.app.services.inventory_reorder_execution import execute_approved_reorder
        tenant_id = str(current_tenant_id() or "").strip()
        if not tenant_id:
            raise HTTPException(status_code=403, detail="tenant_scope_missing")
        with db_session() as db:
            result = execute_approved_reorder(
                db,
                tenant_id=tenant_id,
                proposal_id=req.proposal_id,
                actor_id=role,
            )
        return {"status": "ok", "result": result}
    except ReorderBoundaryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, **exc.detail},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="reorder failed")


@router.post("/reconcile")
def reconcile_stock(counted: Dict[str, int], role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Reconcile a stocktake payload: { sku: count }"""
    try:
        from src.app.services.inventory_agent import InventoryAgent
        from src.app.observability.metrics import decisions_events_counter
        agent = InventoryAgent()
        res = agent.reconcile_stocktake(counted)
        try:
            decisions_events_counter.inc()
        except Exception:
            pass
        return {"status": "ok", "result": res}
    except Exception:
        raise HTTPException(status_code=500, detail="reconcile failed")
