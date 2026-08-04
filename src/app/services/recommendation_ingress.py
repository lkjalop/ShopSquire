"""Universal recommendation ingress controls shared by HTTP and chat callers."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import HTTPException
from opentelemetry import trace

from src.app.security.model_theft import (
    detect_systematic_probing,
    enforce_model_theft_policy_gate,
    enforce_model_theft_rate_limit,
)
from src.app.services.tenant_quota import TenantQuotaGuard


@dataclass(frozen=True)
class RecommendationIngress:
    trace_id: str
    tenant_id: str
    source_ip: Optional[str]
    probe_result: Dict[str, Any]


def _trace_id() -> str:
    try:
        context = trace.get_current_span().get_span_context()
        if context and context.trace_id:
            return f"{context.trace_id:032x}"
    except Exception:
        pass
    return str(uuid.uuid4())


def _request_key(*, tenant_id: str, uid: str, query: str) -> str:
    raw = f"{tenant_id}\0{uid}\0{query}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def authorize_recommendation_ingress(
    *, request: Any, redis: Any, query: str, uid: str,
    tenant_id: Optional[str], benign_shopping_query: bool = False,
) -> RecommendationIngress:
    """Authorize once per request/query and return the shared trace/tenant identity."""
    tenant = str(tenant_id or "default")
    key = _request_key(tenant_id=tenant, uid=str(uid or ""), query=str(query or ""))
    cached = getattr(getattr(request, "state", None), "recommendation_ingress", None)
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == key:
        return cached[1]

    source_ip = request.client.host if request is not None and request.client else None
    api_key_id = request.headers.get("x-api-key") if request is not None else None
    policy_ok, policy_reason = enforce_model_theft_policy_gate(
        query=query, uid=uid, source_ip=source_ip, api_key_id=api_key_id)
    if not policy_ok:
        raise HTTPException(status_code=429, detail={
            "message": "model_theft_policy_gate", "reason": policy_reason})

    allowed, reason = enforce_model_theft_rate_limit(
        redis_client=redis, uid=uid, source_ip=source_ip,
        api_key_id=api_key_id, query=query)
    if not allowed and not benign_shopping_query:
        raise HTTPException(status_code=429, detail={
            "message": "model_theft_guard", "reason": reason})

    probe = detect_systematic_probing(
        redis_client=redis, uid=uid, source_ip=source_ip, queries=[query])
    if bool(probe.get("detected")):
        import os
        if str(os.getenv("MODEL_THEFT_BLOCK_SYSTEMATIC_PROBING", "1")).lower() in (
                "1", "true", "yes"):
            raise HTTPException(status_code=429, detail={
                "message": "systematic_probing", "reason": probe.get("reason"),
                "score": probe.get("score")})

    try:
        quota = TenantQuotaGuard(redis)
        quota_allowed, meta = quota.check_and_consume(tenant, "recommend_calls", amount=1)
        if not quota_allowed:
            raise HTTPException(status_code=429, detail={
                "error": "tenant_quota_exceeded", **meta})
    except HTTPException:
        raise
    except Exception:
        # Preserve the existing availability policy for quota infrastructure failures.
        pass

    outcome = RecommendationIngress(
        trace_id=_trace_id(), tenant_id=tenant, source_ip=source_ip,
        probe_result=dict(probe or {}))
    if request is not None and getattr(request, "state", None) is not None:
        request.state.recommendation_ingress = (key, outcome)
    return outcome
