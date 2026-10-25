"""HTTP identity, transition errors and safe buyer trace for fulfillment routes."""
from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import HTTPException
from src.app.security.auth import OperatorSubject
from src.app.services.fulfillment import workflow as fwf
from src.app.services.fulfillment.domain import Actor, ActorType


def _operator_actor(role: str, subj: "OperatorSubject") -> Actor:
    """Resolve human authority while retaining the authenticated audit identity."""
    uid = (getattr(subj, "user_id", "") or "").strip() or f"key:{role}"
    return Actor(ActorType.HUMAN_OPERATOR, role, user_id=uid)



def _agent() -> Actor:
    return Actor(ActorType.AGENT, "Procurement_Agent")



def _raise_if_failed(res: "fwf.TransitionResult") -> None:
    if not res.ok:
        raise HTTPException(status_code=res.http_status, detail=res.reason)



def _operator_case_tenant(db, case_id: str) -> str:
    """Role dependency verifies membership; bind the service call to that scope."""
    from src.app.platform.tenant_context import current_tenant_id
    tenant_id = str(current_tenant_id() or 'default')
    if fwf.repository.current_version(db, case_id, tenant_id) is None:
        raise HTTPException(status_code=404, detail='not_found')
    return tenant_id



def _buyer_procurement_trace(draft: Any) -> Optional[Dict[str, Any]]:
    """Expose workflow proof without leaking supplier-private message content or economics."""
    if not isinstance(draft, dict):
        return None
    scope = draft.get("commercial_scope") if isinstance(draft.get("commercial_scope"), dict) else {}
    channel = draft.get("channel_plan") if isinstance(draft.get("channel_plan"), dict) else {}
    gate = draft.get("send_gate") or draft.get("gate")
    gate = gate if isinstance(gate, dict) else {}
    reasons = gate.get("blocking") or gate.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [reasons]
    return {
        "drafted": True,
        "status": "human_gated_not_sent",
        "item_ref": scope.get("item_ref"),
        "quantity": scope.get("quantity"),
        "currency": scope.get("currency"),
        "channel": channel.get("channel"),
        "requires_human": bool(channel.get("requires_human")),
        "integration_kind": channel.get("integration_kind"),
        "gate_decision": gate.get("decision"),
        "gate_reasons": [str(reason) for reason in reasons if reason],
        "content_hash": draft.get("content_hash"),
    }
