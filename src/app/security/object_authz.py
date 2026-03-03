from __future__ import annotations

from typing import Dict, Any

from fastapi import HTTPException, Request

from src.app.services.decision_log import log_trace_event


def enforce_object_scope(
    *,
    request: Request,
    resource_id: str,
    tenant_id: str | None,
    owner_id: str | None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    req_tenant = (request.headers.get("x-tenant-id") or request.headers.get("X-Tenant-Id") or "").strip() or None
    req_actor = (request.headers.get("x-user-id") or request.headers.get("X-User-Id") or "").strip() or None
    if not tenant_id or not owner_id:
        raise HTTPException(status_code=403, detail="object_scope_missing")
    if req_tenant != tenant_id:
        try:
            if trace_id:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="policy_gate",
                    source_type="agent",
                    source_id="BOLA_Guard_Agent",
                    target_type="resource",
                    target_id=resource_id,
                    payload={"allow": False, "abac_reason": "tenant_mismatch", "resource_owner": owner_id},
                )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="tenant_scope_violation")
    if req_actor and req_actor != owner_id:
        try:
            if trace_id:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="policy_gate",
                    source_type="agent",
                    source_id="BOLA_Guard_Agent",
                    target_type="resource",
                    target_id=resource_id,
                    payload={"allow": False, "abac_reason": "owner_mismatch", "resource_owner": owner_id},
                )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="owner_scope_violation")
    return {
        "allow": True,
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "resource_id": resource_id,
    }

