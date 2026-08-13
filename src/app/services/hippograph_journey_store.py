"""Durable adapter for typed Hippograph evidence edges.

Writes are idempotent and append-only. Supersession/contradiction is expressed by
new edges; historical rows are never overwritten by a newer observation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select

from src.app.models.orm import (
    HippographJourneyEdgeRecord, ProductAvailabilityObservation, ProductConfiguration,
)
from src.app.services.hippograph_journey_edges import TypedJourneyEdge


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def persist_journey_edges(
    db, edges: Iterable[TypedJourneyEdge | dict], *, tenant_id: str, case_id: str | None = None,
) -> list[str]:
    typed = [edge if isinstance(edge, TypedJourneyEdge) else TypedJourneyEdge.model_validate(edge) for edge in edges]
    if any(edge.tenant_id != tenant_id for edge in typed):
        raise ValueError("hippograph_edge_tenant_mismatch")
    ids = [edge.edge_id for edge in typed]
    existing = set(db.execute(select(HippographJourneyEdgeRecord.edge_id).where(
        HippographJourneyEdgeRecord.tenant_id == tenant_id,
        HippographJourneyEdgeRecord.edge_id.in_(ids),
    )).scalars()) if ids else set()
    stored: list[str] = []
    now = datetime.now(timezone.utc)
    for edge in typed:
        if edge.edge_id in existing:
            continue
        db.add(HippographJourneyEdgeRecord(
            edge_id=edge.edge_id, tenant_id=tenant_id, case_id=case_id,
            source_id=edge.source_id, source_kind=edge.source_kind,
            target_id=edge.target_id, target_kind=edge.target_kind,
            relation=edge.relation.value, signal_class=edge.signal_class.value,
            evidence_id=edge.evidence_id, source_authority=edge.source_authority,
            confidence_micros=round(edge.confidence * 1_000_000),
            observed_at=_datetime(edge.observed_at), effective_at=_datetime(edge.effective_at),
            valid_to=_datetime(edge.valid_to) if edge.valid_to else None,
            supersedes_edge_id=edge.supersedes_edge_id,
            contradicts_edge_ids_json=list(edge.contradicts_edge_ids),
            attributes_json=dict(edge.attributes), created_at=now,
        ))
        stored.append(edge.edge_id)
    if stored:
        db.commit()
    return stored


def load_journey_edges(
    db, *, tenant_id: str, case_id: str | None = None, limit: int = 5000,
) -> list[TypedJourneyEdge]:
    query = select(HippographJourneyEdgeRecord).where(
        HippographJourneyEdgeRecord.tenant_id == tenant_id,
    )
    if case_id is not None:
        query = query.where(HippographJourneyEdgeRecord.case_id == case_id)
    rows = db.execute(query.order_by(
        HippographJourneyEdgeRecord.observed_at.asc(), HippographJourneyEdgeRecord.edge_id.asc(),
    ).limit(max(1, int(limit)))).scalars().all()
    return [TypedJourneyEdge(
        edge_id=row.edge_id, tenant_id=row.tenant_id,
        source_id=row.source_id, source_kind=row.source_kind,
        target_id=row.target_id, target_kind=row.target_kind,
        relation=row.relation, signal_class=row.signal_class,
        evidence_id=row.evidence_id,
        observed_at=row.observed_at.isoformat(), effective_at=row.effective_at.isoformat(),
        valid_to=row.valid_to.isoformat() if row.valid_to else None,
        source_authority=row.source_authority,
        confidence=float(row.confidence_micros) / 1_000_000,
        supersedes_edge_id=row.supersedes_edge_id,
        contradicts_edge_ids=list(row.contradicts_edge_ids_json or []),
        attributes=dict(row.attributes_json or {}),
    ) for row in rows]


def load_configuration_availability_edges(
    db, *, tenant_id: str, limit: int = 5000,
) -> list[TypedJourneyEdge]:
    """Project the durable exact-configuration availability ledger into typed edges."""
    rows = db.execute(select(
        ProductAvailabilityObservation, ProductConfiguration,
    ).join(
        ProductConfiguration,
        ProductConfiguration.id == ProductAvailabilityObservation.configuration_id,
    ).where(
        ProductConfiguration.tenant_id == tenant_id,
    ).order_by(
        ProductAvailabilityObservation.observed_at.asc(),
        ProductAvailabilityObservation.id.asc(),
    ).limit(max(1, int(limit)))).all()
    return [TypedJourneyEdge(
        edge_id=f"availability-{observation.id}", tenant_id=tenant_id,
        source_id=f"configuration:{configuration.id}", source_kind="configuration",
        target_id=f"availability_observation:{observation.id}",
        target_kind="availability_observation",
        relation="has_availability_observation", signal_class="observed",
        evidence_id=observation.source_record_id,
        observed_at=observation.observed_at.isoformat(),
        effective_at=observation.observed_at.isoformat(),
        valid_to=observation.expires_at.isoformat() if observation.expires_at else None,
        source_authority="inventory_observation",
        attributes={
            "sku": configuration.sku, "location_id": observation.location_id,
            "status": observation.status, "quantity": observation.quantity,
            "lead_time_min_days": observation.lead_time_min_days,
            "lead_time_max_days": observation.lead_time_max_days,
        },
    ) for observation, configuration in rows]


__all__ = [
    "load_configuration_availability_edges", "load_journey_edges", "persist_journey_edges",
]
