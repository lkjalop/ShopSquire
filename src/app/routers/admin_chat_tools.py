from fastapi import APIRouter, HTTPException
from typing import Dict, Any

router = APIRouter(prefix="/api/v1/admin/tools", tags=["admin_tools"])


@router.post("/rules/evaluate")
def evaluate_rules(body: Dict[str, Any]):
    """Evaluate central rules against a query."""
    try:
        from src.app.rules.engine import RuleEngine
        engine = RuleEngine()
        q = body.get("query", "")
        ctx = body.get("context") or {}
        out = engine.evaluate(ctx if isinstance(ctx, dict) else {})
        return {"query": q, "result": out}
    except Exception:
        raise HTTPException(status_code=500, detail="rule engine unavailable")


@router.post("/policy/check")
def policy_check(body: Dict[str, Any]):
    """Run policy gate for a proposed action."""
    try:
        from src.app.services.policy_gate import PolicyGate
        gate = PolicyGate(flags={})
        out = gate.evaluate({"proposal": body}, context={})
        return out
    except Exception:
        raise HTTPException(status_code=500, detail="policy gate unavailable")


@router.post("/tickets/create")
def tickets_create(body: Dict[str, Any]):
    """Create a ticket for escalation with minimal fields."""
    try:
        from src.app.services.ticketing import TicketingAgent
        ta = TicketingAgent()
        ticket = ta.create_ticket(title=body.get("title") or "Admin Ticket", description=body.get("description") or "", severity=body.get("severity") or "medium")
        return {"id": getattr(ticket, "id", None), "status": getattr(ticket, "status", None)}
    except Exception:
        raise HTTPException(status_code=500, detail="ticketing unavailable")
