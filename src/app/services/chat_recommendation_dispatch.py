from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

import anyio
from fastapi import HTTPException, Request


async def dispatch_chat_recommendation(
    request: Request,
    params: dict[str, Any],
    *,
    redis: Any,
    db: Any,
    role: str,
    tenant_id_resolver: Callable[[Request], str],
    cancellation: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Dispatch chat through the typed recommendation facade and V2 cutover."""
    from src.app.services.recommendation_delegation_policy import (
        compatibility_cutover_enabled,
        v2_only_unavailable_response,
    )
    from src.app.services.recommendation_facade import dispatch_recommendation_core_typed

    def invoke() -> dict[str, Any]:
        from src.app.observability.metrics import record_recommendation_dispatch

        tenant_id = tenant_id_resolver(request)
        observed_lane = str(params.get("turn_intent") or "").upper() or None
        facade = dispatch_recommendation_core_typed(
            db, redis,
            query=str(params.get("query") or ""), uid=str(params.get("uid") or ""),
            tenant_id=tenant_id,
            budget_max=params.get("budget_max"), budget_min=params.get("budget_min"),
            trace_id=str(params.get("trace_id") or uuid.uuid4()),
            image_labels=params.get("image_labels"), image_ocr=params.get("image_ocr_text"),
            image_hash=params.get("image_hash"), image_intent=params.get("image_intent"),
            image_product_identity=params.get("image_product_identity"),
            image_cv_signals=params.get("image_cv_signals"),
            external_research_consent=(
                str(params.get("external_research_consent") or "").lower() == "true"
            ),
            clarification_answer=(
                params.get("clarification_answer")
                if isinstance(params.get("clarification_answer"), dict) else None
            ),
            intent_hint=params.get("turn_intent"), role=role, request=request,
            confirmed_slots=(
                params.get("confirmed_slots")
                if isinstance(params.get("confirmed_slots"), dict) else None
            ),
            session_epoch=str(params.get("session_epoch") or "").strip() or None,
            memory_enabled=str(params.get("memory_mode") or "standard").lower() != "temporary",
            source_ip=request.client.host if request.client else None,
            cancellation=cancellation,
        )
        if facade.served:
            record_recommendation_dispatch(
                outcome="v2_served", lane=facade.lane or observed_lane, reason="served",
            )
            served = dict(facade.payload or {})
            served.setdefault("execution_mode", "v2_served")
            served.setdefault("execution_lane", facade.lane)
            return served
        if facade.status == "blocked":
            record_recommendation_dispatch(
                outcome="blocked", lane=facade.lane or observed_lane, reason=facade.reason,
            )
            status_code = 429 if str(facade.reason).startswith("quota:") else 403
            raise HTTPException(status_code=status_code, detail={
                "message": "Request blocked by recommendation guard",
                "reason": facade.reason,
                "trace_id": str(params.get("trace_id") or "") or None,
            })
        if not compatibility_cutover_enabled():
            record_recommendation_dispatch(
                outcome="v2_unavailable", lane=facade.lane or observed_lane,
                reason=facade.reason or facade.status,
            )
            return v2_only_unavailable_response(
                status=facade.status, reason=facade.reason, lane=facade.lane,
                trace_id=str(params.get("trace_id") or ""),
            )
        from src.app.services.recommendation_compatibility import serve_v2_compatibility
        try:
            delegated = serve_v2_compatibility(
                request=request, params=params, redis=redis, db=db, role=role,
            )
        except Exception:
            record_recommendation_dispatch(
                outcome="error", lane=facade.lane or observed_lane,
                reason=facade.reason or facade.status,
            )
            raise
        record_recommendation_dispatch(
            outcome="v2_compatibility", lane=facade.lane or observed_lane,
            reason=facade.reason or facade.status,
        )
        delegated = dict(delegated or {})
        delegated.setdefault("execution_mode", "v2_compatibility")
        delegated.setdefault("delegation_reason", facade.reason or facade.status)
        delegated.setdefault("execution_lane", facade.lane)
        return delegated

    try:
        data = await anyio.to_thread.run_sync(invoke, abandon_on_cancel=True)
        return 200, data if isinstance(data, dict) else {}
    except asyncio.CancelledError:
        if cancellation is not None:
            cancellation.cancel("buyer_request_cancelled")
        raise
    except HTTPException as exc:
        detail = exc.detail
        return int(exc.status_code), detail if isinstance(detail, dict) else {"detail": detail}


__all__ = ["dispatch_chat_recommendation"]
