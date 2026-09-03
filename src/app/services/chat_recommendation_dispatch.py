from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import anyio
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class ChatRecommendationCommand:
    """Typed/coerced chat input before recommendation orchestration begins."""

    raw_params: dict[str, Any]
    query: str
    uid: str
    trace_id: str
    observed_lane: str | None
    external_research_consent: bool
    memory_enabled: bool
    session_epoch: str | None

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> "ChatRecommendationCommand":
        raw = dict(params)
        observed_lane = str(raw.get("turn_intent") or "").upper() or None
        return cls(
            raw_params=raw,
            query=str(raw.get("query") or ""),
            uid=str(raw.get("uid") or ""),
            trace_id=str(raw.get("trace_id") or uuid.uuid4()),
            observed_lane=observed_lane,
            external_research_consent=(
                str(raw.get("external_research_consent") or "").lower() == "true"
            ),
            memory_enabled=(
                str(raw.get("memory_mode") or "standard").lower() != "temporary"
            ),
            session_epoch=str(raw.get("session_epoch") or "").strip() or None,
        )


def normalize_chat_recommendation_result(
    result: Any,
    *,
    command: ChatRecommendationCommand,
) -> dict[str, Any]:
    """Project every dispatch lane into one stable, router-safe result shape."""
    normalized = dict(result) if isinstance(result, dict) else {}
    normalized.setdefault("trace_id", command.trace_id)
    normalized.setdefault("decision_trace_id", normalized.get("trace_id") or command.trace_id)
    normalized.setdefault("operation_id", f"chat:{command.trace_id}")
    normalized.setdefault("case_id", None)
    normalized.setdefault("case_revision", None)
    normalized.setdefault("research_run_id", None)
    if command.observed_lane:
        normalized.setdefault("execution_lane", command.observed_lane)
    normalized.setdefault("execution_mode", "recommendation_result")
    # ``canonical_facts`` is the one ingress-owned fact contract.  Some served
    # and degraded lanes historically flattened only a subset of it, which let
    # a correctly parsed budget survive in the facade while disappearing from
    # the terminal case/read-model projection.  Project the stable public fields
    # here once; callers must not reparse the query to recover them.
    facts = normalized.get("canonical_facts")
    if isinstance(facts, dict):
        if isinstance(facts.get("canonical_budget"), dict):
            normalized.setdefault("canonical_budget", facts["canonical_budget"])
        if isinstance(facts.get("commercial_terms"), dict):
            normalized.setdefault("commercial_terms", facts["commercial_terms"])
        if facts.get("quantity") is not None:
            normalized.setdefault("requested_quantity", facts["quantity"])
        if facts.get("budget_scope") is not None:
            normalized.setdefault("budget_scope", facts["budget_scope"])
        if facts.get("total_budget_cents") is not None:
            normalized.setdefault("total_budget_cents", facts["total_budget_cents"])
    semantic = normalized.get("semantic_status")
    if isinstance(semantic, dict) and semantic.get("subject_role"):
        normalized.setdefault("subject_role", semantic["subject_role"])
    return normalized


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
        v2_only_unavailable_response,
    )
    from src.app.services.recommendation_facade import dispatch_recommendation_core_typed
    command = ChatRecommendationCommand.from_params(params)

    def invoke() -> dict[str, Any]:
        from src.app.observability.metrics import record_recommendation_dispatch

        tenant_id = tenant_id_resolver(request)
        facade = dispatch_recommendation_core_typed(
            db, redis,
            query=command.query, uid=command.uid,
            tenant_id=tenant_id,
            budget_max=command.raw_params.get("budget_max"),
            budget_min=command.raw_params.get("budget_min"),
            trace_id=command.trace_id,
            image_labels=command.raw_params.get("image_labels"),
            image_ocr=command.raw_params.get("image_ocr_text"),
            image_hash=command.raw_params.get("image_hash"),
            image_intent=command.raw_params.get("image_intent"),
            image_product_identity=command.raw_params.get("image_product_identity"),
            image_cv_signals=command.raw_params.get("image_cv_signals"),
            external_research_consent=command.external_research_consent,
            clarification_answer=(
                command.raw_params.get("clarification_answer")
                if isinstance(command.raw_params.get("clarification_answer"), dict) else None
            ),
            intent_hint=command.raw_params.get("turn_intent"), role=role, request=request,
            confirmed_slots=(
                command.raw_params.get("confirmed_slots")
                if isinstance(command.raw_params.get("confirmed_slots"), dict) else None
            ),
            canonical_case=(
                command.raw_params.get("canonical_case")
                if isinstance(command.raw_params.get("canonical_case"), dict) else None
            ),
            case_patch_idempotency_key=str(
                command.raw_params.get("case_patch_idempotency_key") or ""
            )[:128] or None,
            session_epoch=command.session_epoch,
            memory_enabled=command.memory_enabled,
            source_ip=request.client.host if request.client else None,
            cancellation=cancellation,
        )
        if facade.served:
            record_recommendation_dispatch(
                outcome="v2_served", lane=facade.lane or command.observed_lane, reason="served",
            )
            served = dict(facade.payload or {})
            served.setdefault("execution_mode", "v2_served")
            served.setdefault("execution_lane", facade.lane)
            served["canonical_facts"] = dict(facade.facts or {})
            served["semantic_status"] = dict(
                facade.semantic_status or {"status": "not_evaluated"}
            )
            served["execution_evidence"] = dict(facade.execution_evidence or {})
            return normalize_chat_recommendation_result(served, command=command)
        if facade.status == "blocked":
            record_recommendation_dispatch(
                outcome="blocked", lane=facade.lane or command.observed_lane, reason=facade.reason,
            )
            status_code = 429 if str(facade.reason).startswith("quota:") else 403
            raise HTTPException(status_code=status_code, detail={
                "message": "Request blocked by recommendation guard",
                "reason": facade.reason,
                "trace_id": command.trace_id,
            })
        record_recommendation_dispatch(
            outcome="v2_unavailable", lane=facade.lane or command.observed_lane,
            reason=facade.reason or facade.status,
        )
        terminal = v2_only_unavailable_response(
            status=facade.status, reason=facade.reason, lane=facade.lane,
            trace_id=command.trace_id, query=command.query,
            external_research_authorized=command.external_research_consent,
            facts=facade.facts, semantic_status=facade.semantic_status,
            execution_evidence=facade.execution_evidence,
        )
        # Preserve bounded, read-only receipts from the single core invocation.
        # Products and actions are deliberately absent from this projection.
        diagnostics = facade.diagnostics if isinstance(facade.diagnostics, dict) else {}
        for key in (
            "requested_quantity", "bulk_budget", "router_outcome", "model_invocation",
        ):
            if diagnostics.get(key) is not None:
                terminal[key] = diagnostics[key]
        return normalize_chat_recommendation_result(terminal, command=command)

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


__all__ = [
    "ChatRecommendationCommand",
    "dispatch_chat_recommendation",
    "normalize_chat_recommendation_result",
]
