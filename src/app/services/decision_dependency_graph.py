"""Persisted, bounded dependency graph for selective decision invalidation."""
from __future__ import annotations

import hashlib
from collections import deque
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.app.models.orm import ProcurementDecisionDependencyRecord


DependencyRelation = Literal["consumed_by", "produced_by", "depends_on", "invalidates"]


class DecisionDependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(min_length=1, max_length=240)
    run_id: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(min_length=1, max_length=320)
    target_ref: str = Field(min_length=1, max_length=320)
    relation: DependencyRelation


class DependencyTraversalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    changed_refs: tuple[str, ...]
    visited_refs: tuple[str, ...]
    traversed_edge_ids: tuple[str, ...]
    affected_stage_ids: tuple[str, ...]
    affected_artifact_refs: tuple[str, ...]
    max_depth: int
    truncated: bool
    authority: Literal["invalidation_projection_only"] = "invalidation_projection_only"


def _edge_id(run_id: str, source: str, target: str, relation: str) -> str:
    raw = f"{run_id}|{source}|{target}|{relation}".encode()
    return f"dde-{hashlib.sha256(raw).hexdigest()[:24]}"


def derive_decision_dependency_edges(
    *, run_id: str, tenant_id: str, case_id: str, stage_receipts: Iterable[Any],
) -> tuple[DecisionDependencyEdge, ...]:
    edges: dict[str, DecisionDependencyEdge] = {}
    for receipt in stage_receipts:
        stage_id = receipt.stage_id or receipt.stage
        stage_ref = f"stage:{stage_id}"
        for artifact in receipt.input_artifact_refs:
            edge = DecisionDependencyEdge(
                edge_id=_edge_id(run_id, artifact, stage_ref, "consumed_by"),
                run_id=run_id, tenant_id=tenant_id, case_id=case_id,
                source_ref=artifact, target_ref=stage_ref, relation="consumed_by",
            )
            edges[edge.edge_id] = edge
        # Declared output shape is useful in the receipt, but a failed/degraded
        # stage did not produce an authoritative artifact edge.
        completed = str(getattr(receipt.status, "value", receipt.status)) == "completed"
        for artifact in receipt.output_artifact_refs if completed else ():
            edge = DecisionDependencyEdge(
                edge_id=_edge_id(run_id, stage_ref, artifact, "produced_by"),
                run_id=run_id, tenant_id=tenant_id, case_id=case_id,
                source_ref=stage_ref, target_ref=artifact, relation="produced_by",
            )
            edges[edge.edge_id] = edge
        for dependency_id in receipt.dependency_stage_ids:
            source = f"stage:{dependency_id}"
            edge = DecisionDependencyEdge(
                edge_id=_edge_id(run_id, source, stage_ref, "depends_on"),
                run_id=run_id, tenant_id=tenant_id, case_id=case_id,
                source_ref=source, target_ref=stage_ref, relation="depends_on",
            )
            edges[edge.edge_id] = edge
    return tuple(sorted(edges.values(), key=lambda item: item.edge_id))


def persist_decision_dependency_edges(db, edges: Iterable[DecisionDependencyEdge]) -> None:
    typed = tuple(edges)
    ids = [item.edge_id for item in typed]
    existing = set(db.execute(select(ProcurementDecisionDependencyRecord.edge_id).where(
        ProcurementDecisionDependencyRecord.edge_id.in_(ids),
    )).scalars()) if ids else set()
    for edge in typed:
        if edge.edge_id in existing:
            continue
        db.add(ProcurementDecisionDependencyRecord(**edge.model_dump()))


def load_decision_dependency_edges(
    db, *, tenant_id: str, case_id: str, run_id: str | None = None,
) -> list[DecisionDependencyEdge]:
    query = select(ProcurementDecisionDependencyRecord).where(
        ProcurementDecisionDependencyRecord.tenant_id == tenant_id,
        ProcurementDecisionDependencyRecord.case_id == case_id,
    )
    if run_id:
        query = query.where(ProcurementDecisionDependencyRecord.run_id == run_id)
    rows = db.execute(query.order_by(ProcurementDecisionDependencyRecord.edge_id)).scalars().all()
    return [DecisionDependencyEdge.model_validate({
        "edge_id": row.edge_id, "run_id": row.run_id, "tenant_id": row.tenant_id,
        "case_id": row.case_id, "source_ref": row.source_ref,
        "target_ref": row.target_ref, "relation": row.relation,
    }) for row in rows]


def traverse_decision_dependencies(
    edges: Iterable[DecisionDependencyEdge], *, changed_refs: tuple[str, ...],
    max_depth: int = 8, max_nodes: int = 256,
) -> DependencyTraversalReceipt:
    depth_limit = max(1, min(int(max_depth), 32))
    node_limit = max(1, min(int(max_nodes), 4096))
    adjacency: dict[str, list[DecisionDependencyEdge]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_ref, []).append(edge)
    for rows in adjacency.values():
        rows.sort(key=lambda item: item.edge_id)
    queue = deque((item, 0) for item in dict.fromkeys(changed_refs))
    visited: list[str] = []
    seen = set()
    traversed: list[str] = []
    stages: list[str] = []
    artifacts: list[str] = []
    truncated = False
    while queue:
        current, depth = queue.popleft()
        if current in seen:
            continue
        if len(seen) >= node_limit:
            truncated = True
            break
        seen.add(current)
        visited.append(current)
        if depth >= depth_limit:
            if adjacency.get(current):
                truncated = True
            continue
        for edge in adjacency.get(current, ()):
            traversed.append(edge.edge_id)
            target = edge.target_ref
            if target.startswith("stage:"):
                stages.append(target.removeprefix("stage:"))
            else:
                artifacts.append(target)
            queue.append((target, depth + 1))
    return DependencyTraversalReceipt(
        changed_refs=tuple(dict.fromkeys(changed_refs)), visited_refs=tuple(visited),
        traversed_edge_ids=tuple(dict.fromkeys(traversed)),
        affected_stage_ids=tuple(dict.fromkeys(stages)),
        affected_artifact_refs=tuple(dict.fromkeys(artifacts)),
        max_depth=depth_limit, truncated=truncated,
    )


__all__ = [
    "DecisionDependencyEdge", "DependencyTraversalReceipt",
    "derive_decision_dependency_edges", "load_decision_dependency_edges",
    "persist_decision_dependency_edges", "traverse_decision_dependencies",
]
