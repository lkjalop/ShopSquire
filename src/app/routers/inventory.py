from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Dict
import time

from src.app.config import load_feature_flags, get_settings
from src.app.deps import get_redis
from src.app.services.degradation import cb_is_open, cb_record
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.policy.kill_switch import assert_autonomy_allowed


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/health")
def health(redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    flags = load_feature_flags(get_settings().feature_flags_path)
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
        flags = load_feature_flags(get_settings().feature_flags_path)
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
        flags = load_feature_flags(get_settings().feature_flags_path)
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
    sku: str
    supplier_id: str | None = None
    quantity: int = 0
    approval: str | None = None
    po_invoice_confirmed: bool = False
    carrier_asn_ack: bool = False
    erp_ack: bool = False
    tenant_id: str | None = None
    owner_id: str | None = None
    supplier_trust_score: float | None = None
    supplier_trust_band: str | None = None
    anomaly_score: float | None = None


@router.post("/reorder")
def reorder(req: ReorderRequest, request: Request, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER]))):
    """Execute a reorder recommendation (may require approval)."""
    try:
        flags = load_feature_flags(get_settings().feature_flags_path)
        assert_autonomy_allowed(
            "inventory",
            flags=flags,
            source_id="Inventory_Autonomy_Governance_Agent",
            context={"sku": req.sku, "quantity": int(req.quantity or 0)},
        )
        from src.app.services.inventory_agent import InventoryAgent, ReorderRecommendation
        from src.app.services.decision_log import log_trace_event
        from src.app.observability.metrics import decisions_events_counter
        from src.app.services.ticketing import TicketingAgent
        from src.app.security.object_authz import enforce_object_scope
        agent = InventoryAgent()
        # BOLA/BFLA guard: enforce tenant + owner scoped access when object scope is supplied.
        if req.tenant_id and req.owner_id:
            enforce_object_scope(
                request=request,
                resource_id=req.sku,
                tenant_id=req.tenant_id,
                owner_id=req.owner_id,
                trace_id=None,
            )
        # Build a simple recommendation object for execution
        rec = None
        try:
            rec = ReorderRecommendation(
                sku=req.sku,
                supplier_id=req.supplier_id,
                quantity=int(req.quantity or 0),
                estimated_cost=0.0,
                lead_time_days=7,
                urgency="normal",
                supplier_trust_score=float(req.supplier_trust_score or 0.7),
                supplier_trust_band=str(req.supplier_trust_band or "medium"),
                anomaly_score=float(req.anomaly_score or 0.0),
                source_confirmations={
                    "po_invoice": bool(req.po_invoice_confirmed),
                    "carrier_asn": bool(req.carrier_asn_ack),
                    "erp_ack": bool(req.erp_ack),
                },
            )
        except Exception:
            # fallback lightweight dict-based
            rec = type("R", (), {"sku": req.sku, "supplier_id": req.supplier_id, "quantity": int(req.quantity or 0), "estimated_cost": 0.0, "lead_time_days": 7, "urgency": "normal"})()
        result = agent.execute_reorder(rec, approval=req.approval)
        try:
            decisions_events_counter.inc()
        except Exception:
            pass
        try:
            # attach a trace event for traceability (best-effort)
            log_trace_event(trace_id=result.get("po_number") or None, event_type="reorder_executed", source_type="agent", source_id="inventory_api", target_type="supplier", target_id=str(req.supplier_id), payload={"result": result})
        except Exception:
            pass
        # If approval is required and no ticket was created earlier, create one here and return its id
        try:
            if result.get("status") == "approval_required":
                tagent = TicketingAgent()
                title = f"Approval request: reorder {req.sku} qty={req.quantity}"
                desc = f"API-created approval for reorder. reason={result.get('reason')} cost={result.get('cost')}"
                sev = "high" if (result.get("cost") or 0) > 10000 else "medium"
                ticket = tagent.create_ticket(title=title, description=desc, severity=sev, trace_id=None, approval_required=True)
                try:
                    # return ticket id for client to approve
                    return {"status": "approval_required", "ticket_id": ticket.id, "reason": result.get("reason"), "threshold": result.get("threshold"), "cost": result.get("cost")}
                except Exception:
                    return {"status": "approval_required", "reason": result.get("reason")}
        except Exception:
            pass
        return {"status": "ok", "result": result}
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
