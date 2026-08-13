"""Typed, read-only Hippograph projection across the buyer-to-market journey.

Hippograph is evidence memory, not a workflow engine.  This module turns its
recalled nodes and provenance paths into stable lanes for UI and downstream
advisory consumers without granting product-fit, procurement, or commerce
authority.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.hippograph import HippoGraph, explain_path, recall


JourneyLane = Literal[
    "buyer_case",
    "research_evidence",
    "catalog_and_fit",
    "inventory_and_procurement",
    "sales_and_market",
    "outcome_and_governance",
]


class JourneyEvidencePath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[str]
    edges: list[dict[str, Any]]
    hops: int | None
    authority: Literal["evidence_only"] = "evidence_only"


class JourneyEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    kind: str
    label: str
    lane: JourneyLane
    relatedness_score: float
    outcome_prior: float
    evidence_path: JourneyEvidencePath


class JourneyLaneView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane: JourneyLane
    label: str
    entities: list[JourneyEntity] = Field(default_factory=list)


class HippographJourneyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["hippograph-journey-v1"] = "hippograph-journey-v1"
    seed_ids: list[str]
    authority: Literal["evidence_only"] = "evidence_only"
    ranking_authority: Literal["none"] = "none"
    commerce_authority: Literal["none"] = "none"
    lanes: list[JourneyLaneView]
    node_kind_counts: dict[str, int]
    degraded_sources: list[dict[str, Any]]
    guardrails: list[str]


_LANE_ORDER: tuple[JourneyLane, ...] = (
    "buyer_case",
    "research_evidence",
    "catalog_and_fit",
    "inventory_and_procurement",
    "sales_and_market",
    "outcome_and_governance",
)
_LANE_LABELS: dict[JourneyLane, str] = {
    "buyer_case": "Buyer purpose and shopping case",
    "research_evidence": "Research, publisher and requirement evidence",
    "catalog_and_fit": "Exact products and capability context",
    "inventory_and_procurement": "Inventory, suppliers and procurement",
    "sales_and_market": "Sales and market intelligence",
    "outcome_and_governance": "Observed outcomes and governance",
}


def _lane_for_kind(kind: str) -> JourneyLane:
    normalized = str(kind or "node").strip().lower()
    if normalized in {"user", "shopping_case", "buyer", "intent", "purpose"}:
        return "buyer_case"
    if normalized in {"publisher", "requirement", "attribute", "claim", "source"}:
        return "research_evidence"
    if normalized in {"product", "brand", "configuration", "capability", "fit"}:
        return "catalog_and_fit"
    if normalized in {
        "supplier", "procurement", "procurement_case", "rfq", "inventory",
        "availability", "fulfillment", "shipment", "quote",
    }:
        return "inventory_and_procurement"
    if normalized in {"finding", "segment", "campaign", "market", "sales", "price"}:
        return "sales_and_market"
    return "outcome_and_governance"


def project_hippograph_journey(
    graph: HippoGraph,
    seed_ids: Iterable[str],
    *,
    top_k: int = 30,
    max_hops: int = 3,
) -> HippographJourneyProjection:
    """Project bounded graph recall into stable journey lanes.

    Relatedness and historical outcome priors are deliberately separate.  A
    high prior is not a workload-fit verdict, and every entity retains the
    evidence path that explains why it was recalled.
    """

    seeds = list(dict.fromkeys(str(seed) for seed in seed_ids if str(seed).strip()))
    lane_entities: dict[JourneyLane, list[JourneyEntity]] = {
        lane: [] for lane in _LANE_ORDER
    }
    kind_counts: Counter[str] = Counter()
    for entity_id, score in recall(
        graph, seeds, top_k=max(0, int(top_k)), hops=max(1, int(max_hops)),
    ):
        node = graph.nodes.get(entity_id)
        if node is None:
            continue
        lane = _lane_for_kind(node.kind)
        kind_counts[node.kind] += 1
        lane_entities[lane].append(JourneyEntity(
            entity_id=entity_id,
            kind=node.kind,
            label=node.label,
            lane=lane,
            relatedness_score=round(float(score), 4),
            outcome_prior=round(float(node.weight), 4),
            evidence_path=JourneyEvidencePath.model_validate(
                explain_path(graph, seeds, entity_id, max_hops=max_hops)
            ),
        ))

    return HippographJourneyProjection(
        seed_ids=seeds,
        lanes=[
            JourneyLaneView(
                lane=lane,
                label=_LANE_LABELS[lane],
                entities=lane_entities[lane],
            )
            for lane in _LANE_ORDER
        ],
        node_kind_counts=dict(sorted(kind_counts.items())),
        degraded_sources=list(graph.degraded_sources),
        guardrails=[
            "Recall is relatedness evidence, not workload-fit authority.",
            "Historical sales or conversion cannot override verified requirements.",
            "Supplier, RFQ, cart, payment and shipment actions require their own policy gates.",
            "Tenant scope and bitemporal provenance are preserved by the graph projection.",
        ],
    )


__all__ = [
    "HippographJourneyProjection",
    "JourneyEntity",
    "JourneyEvidencePath",
    "JourneyLaneView",
    "project_hippograph_journey",
]
