"""Typed evidence edges for Hippograph's buyer-to-outcome journey.

The graph preserves evidence history and relations. Only evidence active at the
requested replay cutoff contributes source-to-target recall adjacency; prior
observations remain reachable through explicit supersession/contradiction links.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.services.hippograph import HippoGraph, HippoNode


class GraphSignalClass(StrEnum):
    ATTESTED = "attested"
    OBSERVED = "observed"
    DERIVED = "derived"
    INFERRED = "inferred"
    ACCEPTED = "accepted"
    OUTCOME = "outcome"


class JourneyRelation(StrEnum):
    REQUIRES_CAPABILITY = "requires_capability"
    HAS_AVAILABILITY_OBSERVATION = "has_availability_observation"
    HAS_SUPPLIER_OFFER = "has_supplier_offer"
    OFFERS_FULFILLMENT_OPTION = "offers_fulfillment_option"
    SELECTED_BY_BUYER = "selected_by_buyer"
    PRODUCED_ORDER_OUTCOME = "produced_order_outcome"
    HAS_POST_ORDER_OUTCOME = "has_post_order_outcome"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"


_ALLOWED_KIND_PAIRS: dict[JourneyRelation, set[tuple[str, str]]] = {
    JourneyRelation.REQUIRES_CAPABILITY: {("requirement", "capability")},
    JourneyRelation.HAS_AVAILABILITY_OBSERVATION: {
        ("configuration", "availability_observation"),
    },
    JourneyRelation.HAS_SUPPLIER_OFFER: {("configuration", "supplier_offer")},
    JourneyRelation.OFFERS_FULFILLMENT_OPTION: {
        ("supplier_offer", "fulfillment_option"),
    },
    JourneyRelation.SELECTED_BY_BUYER: {
        ("fulfillment_option", "buyer_decision"),
    },
    JourneyRelation.PRODUCED_ORDER_OUTCOME: {
        ("buyer_decision", "order_outcome"),
    },
    JourneyRelation.HAS_POST_ORDER_OUTCOME: {
        ("order_outcome", "return"),
        ("order_outcome", "cancellation"),
        ("order_outcome", "satisfaction"),
    },
}


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class TypedJourneyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(min_length=1, max_length=240)
    tenant_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=300)
    source_kind: str = Field(min_length=1, max_length=80)
    target_id: str = Field(min_length=1, max_length=300)
    target_kind: str = Field(min_length=1, max_length=80)
    relation: JourneyRelation
    signal_class: GraphSignalClass
    evidence_id: str = Field(min_length=1, max_length=240)
    observed_at: str
    effective_at: str
    valid_to: str | None = None
    source_authority: str = "unspecified"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    supersedes_edge_id: str | None = None
    contradicts_edge_ids: list[str] = Field(default_factory=list, max_length=32)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_relation(self) -> "TypedJourneyEdge":
        allowed = _ALLOWED_KIND_PAIRS.get(self.relation)
        pair = (self.source_kind, self.target_kind)
        if allowed is not None and pair not in allowed:
            raise ValueError(f"invalid_kind_pair:{self.relation}:{pair[0]}:{pair[1]}")
        if _time(self.observed_at) is None or _time(self.effective_at) is None:
            raise ValueError("edge_times_required")
        return self


class TypedJourneyProjectionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["hippograph-typed-edges-v1"] = "hippograph-typed-edges-v1"
    as_of: str
    projected_edge_ids: list[str]
    inactive_edge_ids: list[str]
    known_future_edge_ids: list[str] = Field(default_factory=list)
    not_yet_known_edge_ids: list[str] = Field(default_factory=list)
    # Compatibility alias for callers that previously had only one time axis.
    future_edge_ids: list[str]
    contradiction_links: int
    supersession_links: int
    authority: Literal["evidence_only"] = "evidence_only"


def _ensure(graph: HippoGraph, node_id: str, kind: str, label: str | None = None) -> None:
    graph.nodes.setdefault(node_id, HippoNode(node_id, kind, label or node_id, 0.0))


def _connect(
    graph: HippoGraph, source: str, target: str, *, relation: str,
    weight: float, evidence: dict[str, Any], reverse: bool = True,
) -> None:
    key = (source, target)
    graph.edges[key] = graph.edges.get(key, 0.0) + weight
    graph.edge_kinds.setdefault(key, {})[relation] = (
        graph.edge_kinds.setdefault(key, {}).get(relation, 0.0) + weight
    )
    graph.adjacency.setdefault(source, {})[target] = (
        graph.adjacency.setdefault(source, {}).get(target, 0.0) + weight
    )
    if reverse:
        graph.adjacency.setdefault(target, {})[source] = (
            graph.adjacency.setdefault(target, {}).get(source, 0.0) + weight * 0.5
        )
    graph.edge_evidence.setdefault(key, []).append(evidence)


def project_typed_journey_edges(
    graph: HippoGraph,
    raw_edges: Iterable[TypedJourneyEdge | dict[str, Any]],
    *,
    tenant_id: str,
    as_of: str | None = None,
    knowledge_cutoff: str | None = None,
    evaluation_time: str | None = None,
) -> TypedJourneyProjectionReceipt:
    """Add typed edges using separate knowledge and operational-time cutoffs.

    ``as_of`` remains a compatibility shorthand for setting both cutoffs. A
    known supplier change that becomes effective later is therefore preserved
    as ``known_future`` instead of being confused with evidence not yet known.
    """

    default_cutoff = _time(as_of) or datetime.now(timezone.utc)
    known_at = _time(knowledge_cutoff) or default_cutoff
    effective_at = _time(evaluation_time) or default_cutoff
    edges = [
        edge if isinstance(edge, TypedJourneyEdge) else TypedJourneyEdge.model_validate(edge)
        for edge in raw_edges
    ]
    scoped = [edge for edge in edges if edge.tenant_id == tenant_id]
    by_id = {edge.edge_id: edge for edge in scoped}
    superseded_at_cutoff = {
        edge.supersedes_edge_id
        for edge in scoped
        if edge.supersedes_edge_id
        and _time(edge.observed_at) <= known_at
        and _time(edge.effective_at) <= effective_at
    }
    projected: list[str] = []
    inactive: list[str] = []
    known_future: list[str] = []
    not_yet_known: list[str] = []

    for edge in scoped:
        observed = _time(edge.observed_at)
        effective = _time(edge.effective_at)
        valid_to = _time(edge.valid_to)
        evidence_node = f"evidence:{edge.edge_id}"
        _ensure(graph, evidence_node, "evidence", edge.evidence_id)
        if observed > known_at:
            not_yet_known.append(edge.edge_id)
            continue
        if effective > effective_at:
            known_future.append(edge.edge_id)
            continue
        active = edge.edge_id not in superseded_at_cutoff and not (
            valid_to and valid_to <= effective_at
        )
        evidence = {
            "edge_id": edge.edge_id,
            "evidence_id": edge.evidence_id,
            "signal_class": edge.signal_class.value,
            "source_authority": edge.source_authority,
            "observed_at": edge.observed_at,
            "effective_at": edge.effective_at,
            "valid_to": edge.valid_to,
            "confidence": edge.confidence,
            "status": "active" if active else "inactive",
            "authority": "evidence_only",
            "attributes": edge.attributes,
        }
        if active:
            _ensure(graph, edge.source_id, edge.source_kind)
            _ensure(graph, edge.target_id, edge.target_kind)
            weight = max(0.05, edge.confidence)
            _connect(
                graph, edge.source_id, evidence_node,
                relation=edge.relation.value, weight=weight, evidence=evidence,
            )
            _connect(
                graph, evidence_node, edge.target_id,
                relation=edge.relation.value, weight=weight, evidence=evidence,
            )
            projected.append(edge.edge_id)
        else:
            inactive.append(edge.edge_id)

    contradiction_links = 0
    supersession_links = 0
    for edge in scoped:
        if _time(edge.observed_at) > known_at:
            continue
        current = f"evidence:{edge.edge_id}"
        if edge.supersedes_edge_id and edge.supersedes_edge_id in by_id:
            prior = f"evidence:{edge.supersedes_edge_id}"
            _ensure(graph, prior, "evidence", by_id[edge.supersedes_edge_id].evidence_id)
            _connect(graph, current, prior, relation="supersedes", weight=0.1, evidence={
                "edge_id": edge.edge_id, "supersedes_edge_id": edge.supersedes_edge_id,
                "authority": "evidence_only",
            })
            supersession_links += 1
        for contradicted_id in edge.contradicts_edge_ids:
            if contradicted_id not in by_id:
                continue
            other = f"evidence:{contradicted_id}"
            _ensure(graph, other, "evidence", by_id[contradicted_id].evidence_id)
            _connect(graph, current, other, relation="contradicts", weight=0.1, evidence={
                "edge_id": edge.edge_id, "contradicts_edge_id": contradicted_id,
                "authority": "evidence_only",
            })
            contradiction_links += 1

    return TypedJourneyProjectionReceipt(
        as_of=known_at.isoformat(),
        projected_edge_ids=sorted(projected),
        inactive_edge_ids=sorted(inactive),
        known_future_edge_ids=sorted(known_future),
        not_yet_known_edge_ids=sorted(not_yet_known),
        future_edge_ids=sorted(set(known_future + not_yet_known)),
        contradiction_links=contradiction_links,
        supersession_links=supersession_links,
    )


__all__ = [
    "GraphSignalClass", "JourneyRelation", "TypedJourneyEdge",
    "TypedJourneyProjectionReceipt", "project_typed_journey_edges",
]
