"""Purpose-specific, bounded views over canonical Hippograph journey edges."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.hippograph_journey_edges import JourneyRelation, TypedJourneyEdge


class MemoryQueryPurpose(StrEnum):
    WHAT_CHANGED = "what_changed"
    HISTORICAL_KNOWLEDGE = "historical_knowledge"
    SUPPLIER_FULFILMENT = "supplier_fulfilment"
    PRODUCT_FIT = "product_fit"
    COMMERCIAL_OUTCOME = "commercial_outcome"


class BoundedTraversalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: MemoryQueryPurpose
    allowed_relations: tuple[JourneyRelation, ...]
    max_depth: int = Field(ge=1, le=8)
    max_edges: int = Field(ge=1, le=512)
    include_inactive_history: bool = False


class GraphTraversalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: MemoryQueryPurpose
    start_node_ids: tuple[str, ...]
    selected_edge_ids: tuple[str, ...]
    visited_node_ids: tuple[str, ...]
    max_depth: int
    truncated: bool
    known_future_edge_ids: tuple[str, ...] = ()
    not_yet_known_edge_ids: tuple[str, ...] = ()
    authority: Literal["evidence_recall_only"] = "evidence_recall_only"


_PURPOSE_RELATIONS = {
    MemoryQueryPurpose.WHAT_CHANGED: (
        JourneyRelation.CONTRADICTS, JourneyRelation.SUPERSEDES,
        JourneyRelation.HAS_AVAILABILITY_OBSERVATION,
        JourneyRelation.HAS_SUPPLIER_OFFER,
    ),
    MemoryQueryPurpose.HISTORICAL_KNOWLEDGE: tuple(JourneyRelation),
    MemoryQueryPurpose.SUPPLIER_FULFILMENT: (
        JourneyRelation.HAS_SUPPLIER_OFFER,
        JourneyRelation.OFFERS_FULFILLMENT_OPTION,
        JourneyRelation.SELECTED_BY_BUYER,
    ),
    MemoryQueryPurpose.PRODUCT_FIT: (
        JourneyRelation.REQUIRES_CAPABILITY,
        JourneyRelation.HAS_AVAILABILITY_OBSERVATION,
    ),
    MemoryQueryPurpose.COMMERCIAL_OUTCOME: (
        JourneyRelation.SELECTED_BY_BUYER,
        JourneyRelation.PRODUCED_ORDER_OUTCOME,
        JourneyRelation.HAS_POST_ORDER_OUTCOME,
    ),
}


def _aware_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def select_graph_view(
    purpose: MemoryQueryPurpose, *, max_depth: int = 4, max_edges: int = 128,
) -> BoundedTraversalPlan:
    return BoundedTraversalPlan(
        purpose=purpose, allowed_relations=_PURPOSE_RELATIONS[purpose],
        max_depth=max_depth, max_edges=max_edges,
        include_inactive_history=purpose in {
            MemoryQueryPurpose.WHAT_CHANGED, MemoryQueryPurpose.HISTORICAL_KNOWLEDGE,
        },
    )


def traverse_journey_view(
    raw_edges: Iterable[TypedJourneyEdge | dict], *, start_node_ids: tuple[str, ...],
    plan: BoundedTraversalPlan,
    knowledge_cutoff: datetime | None = None,
    evaluation_time: datetime | None = None,
) -> GraphTraversalReceipt:
    edges = tuple(
        row if isinstance(row, TypedJourneyEdge) else TypedJourneyEdge.model_validate(row)
        for row in raw_edges
    )
    known = knowledge_cutoff or datetime.now(timezone.utc)
    evaluated = evaluation_time or known
    if known.tzinfo is None or evaluated.tzinfo is None:
        raise ValueError("graph_view_cutoff_requires_timezone")
    allowed = set(plan.allowed_relations)
    adjacency: dict[str, list[TypedJourneyEdge]] = {}
    known_future: list[str] = []
    not_yet_known: list[str] = []
    for edge in edges:
        observed = _aware_time(edge.observed_at)
        effective = _aware_time(edge.effective_at)
        valid_to = (
            _aware_time(edge.valid_to)
            if edge.valid_to else None
        )
        if observed > known:
            not_yet_known.append(edge.edge_id)
            continue
        if effective > evaluated:
            known_future.append(edge.edge_id)
            continue
        if valid_to and valid_to <= evaluated and not plan.include_inactive_history:
            continue
        if edge.relation in allowed:
            adjacency.setdefault(edge.source_id, []).append(edge)
    for rows in adjacency.values():
        rows.sort(key=lambda row: row.edge_id)
    queue = deque((node, 0) for node in dict.fromkeys(start_node_ids))
    seen: set[str] = set()
    visited: list[str] = []
    selected: list[str] = []
    truncated = False
    while queue:
        node, depth = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        visited.append(node)
        if depth >= plan.max_depth:
            if adjacency.get(node):
                truncated = True
            continue
        for edge in adjacency.get(node, ()):
            if len(selected) >= plan.max_edges:
                truncated = True
                break
            selected.append(edge.edge_id)
            queue.append((edge.target_id, depth + 1))
        if truncated and len(selected) >= plan.max_edges:
            break
    return GraphTraversalReceipt(
        purpose=plan.purpose, start_node_ids=tuple(dict.fromkeys(start_node_ids)),
        selected_edge_ids=tuple(selected), visited_node_ids=tuple(visited),
        max_depth=plan.max_depth, truncated=truncated,
        known_future_edge_ids=tuple(sorted(known_future)),
        not_yet_known_edge_ids=tuple(sorted(not_yet_known)),
    )


__all__ = [
    "BoundedTraversalPlan", "GraphTraversalReceipt", "MemoryQueryPurpose",
    "select_graph_view", "traverse_journey_view",
]
