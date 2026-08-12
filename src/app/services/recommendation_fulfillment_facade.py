"""Typed, read-only fulfilment boundary for recommendation pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecommendationFulfillmentRequest:
    results: list[dict[str, Any]]
    constraints: dict[str, Any]
    uid: str
    trace_id: str | None
    tenant_id: str
    query: str
    flags: dict[str, Any]


@dataclass(frozen=True)
class RecommendationFulfillmentProjection:
    summary: str
    availability: dict[str, Any] | None
    fulfillment_options: list[dict[str, Any]]
    sourcing_intent: dict[str, Any] | None


def project_recommendation_fulfillment(
    request: RecommendationFulfillmentRequest,
) -> RecommendationFulfillmentProjection:
    """Project fulfilment without creating a case, contacting suppliers, or mutating a cart."""
    from src.app.services.recommend_fulfillment_stage import run_fulfillment_stage

    flags = dict(request.flags)
    flags["FULFILLMENT_DEFER_TO_CART"] = True
    payload: dict[str, Any] = {}
    summary = run_fulfillment_stage(
        results=request.results,
        constraints=dict(request.constraints),
        payload=payload,
        uid=request.uid,
        trace_id=request.trace_id,
        flags=flags,
        query=request.query,
        tenant_id=request.tenant_id,
        allow_query_order_split=False,
    )
    return RecommendationFulfillmentProjection(
        summary=summary,
        availability=payload.get("availability") if isinstance(payload.get("availability"), dict) else None,
        fulfillment_options=list(payload.get("fulfillment_options") or []),
        sourcing_intent=payload.get("sourcing_intent") if isinstance(payload.get("sourcing_intent"), dict) else None,
    )
