"""Tenant-scoped dependency registry for explicit temporal retraction.

This module records which derived surfaces consumed an exact source version.  It does not infer
dependencies and it does not delete evidence.  Supersession marks derived records invalid so each
owning projector can rebuild them from the replacement fact.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text


DERIVED_TYPES = frozenset({
    "hippograph_edge", "market_evidence_bundle", "procurement_proposal",
    "buyer_supply_promise", "fulfillment_route_proposal", "narration_fingerprint",
    "allocation_projection", "semantic_cache_entry",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_derived_dependency(
    db, *, tenant_id: str, source_type: str, source_id: str, source_version: str,
    derived_type: str, derived_id: str,
) -> dict[str, Any]:
    if derived_type not in DERIVED_TYPES:
        raise ValueError("unsupported_derived_type")
    params = {
        "t": str(tenant_id), "st": str(source_type), "sid": str(source_id),
        "sv": str(source_version), "dt": derived_type, "did": str(derived_id),
    }
    existing = db.execute(text(
        "SELECT id,status FROM temporal_dependency WHERE tenant_id=:t AND source_type=:st "
        "AND source_id=:sid AND source_version=:sv AND derived_type=:dt AND derived_id=:did"
    ), params).fetchone()
    if existing:
        return {"dependency_id": str(existing[0]), "status": str(existing[1]), "idempotent": True}
    dependency_id = str(uuid.uuid4())
    db.execute(text(
        "INSERT INTO temporal_dependency "
        "(id,tenant_id,source_type,source_id,source_version,derived_type,derived_id,status,created_at) "
        "VALUES (:id,:t,:st,:sid,:sv,:dt,:did,'active',:now)"
    ), {**params, "id": dependency_id, "now": _now()})
    return {"dependency_id": dependency_id, "status": "active", "idempotent": False}


def register_cache_dependency(
    db,
    *,
    tenant_id: str,
    cache_key: str,
    source_type: str,
    source_id: str,
    source_version: str,
) -> dict[str, Any]:
    """Bind one exact cache key to one exact source revision."""
    key = str(cache_key or "").strip()
    if not key:
        raise ValueError("cache_dependency_key_required")
    return register_derived_dependency(
        db,
        tenant_id=tenant_id,
        source_type=source_type,
        source_id=source_id,
        source_version=source_version,
        derived_type="semantic_cache_entry",
        derived_id=key,
    )


def invalidate_source_dependencies(
    db, *, tenant_id: str, source_type: str, source_id: str, source_version: str,
    reason: str,
) -> dict[str, Any]:
    params = {
        "t": str(tenant_id), "st": str(source_type), "sid": str(source_id),
        "sv": str(source_version),
    }
    rows = db.execute(text(
        "SELECT id,derived_type,derived_id FROM temporal_dependency WHERE tenant_id=:t "
        "AND source_type=:st AND source_id=:sid AND source_version=:sv AND status='active' "
        "ORDER BY derived_type,derived_id"
    ), params).fetchall()
    now = _now()
    invalidated = []
    for row in rows:
        db.execute(text(
            "UPDATE temporal_dependency SET status='invalidated',invalidated_at=:now,"
            "invalidation_reason=:reason WHERE id=:id AND status='active'"
        ), {"now": now, "reason": str(reason), "id": row[0]})
        invalidated.append({"dependency_id": str(row[0]), "derived_type": str(row[1]),
                            "derived_id": str(row[2])})
    return {**params, "invalidated_count": len(invalidated), "invalidated": invalidated,
            "reason": str(reason), "rebuild_required": bool(invalidated)}


def invalidate_source_and_schedule_rebuild(
    db,
    *,
    tenant_id: str,
    source_type: str,
    source_id: str,
    source_version: str,
    reason: str,
    cache: Any,
    enqueue_rebuild: Any,
) -> dict[str, Any]:
    """Invalidate dependencies, evict cache entries, and enqueue idempotent rebuild work.

    Non-cache derived records remain in the returned projector backlog. The function performs no
    provider-specific queue or cache work; deployments inject those adapters.
    """
    result = invalidate_source_dependencies(
        db,
        tenant_id=tenant_id,
        source_type=source_type,
        source_id=source_id,
        source_version=source_version,
        reason=reason,
    )
    evicted = 0
    enqueued = 0
    projector_backlog = []
    for item in result["invalidated"]:
        if item["derived_type"] != "semantic_cache_entry":
            projector_backlog.append(item)
            continue
        cache_key = str(item["derived_id"])
        cache.delete(cache_key)
        evicted += 1
        enqueue_rebuild({
            "job_type": "rebuild_temporal_cache_entry",
            "tenant_id": str(tenant_id),
            "cache_key": cache_key,
            "source_type": str(source_type),
            "source_id": str(source_id),
            "source_version": str(source_version),
            "reason": str(reason),
        })
        enqueued += 1
    return {
        **result,
        "cache_entries_evicted": evicted,
        "rebuilds_enqueued": enqueued,
        "projector_backlog": projector_backlog,
    }


def invalidate_derived_dependencies(
    db, *, tenant_id: str, derived_type: str, derived_id: str, reason: str,
) -> dict[str, Any]:
    """Invalidate every active dependency for one rebuilt/superseded derived surface."""
    if derived_type not in DERIVED_TYPES:
        raise ValueError("unsupported_derived_type")
    rows = db.execute(text(
        "SELECT id,source_type,source_id,source_version FROM temporal_dependency "
        "WHERE tenant_id=:t AND derived_type=:dt AND derived_id=:did AND status='active' "
        "ORDER BY source_type,source_id,source_version"
    ), {"t": str(tenant_id), "dt": derived_type, "did": str(derived_id)}).fetchall()
    now = _now()
    for row in rows:
        db.execute(text(
            "UPDATE temporal_dependency SET status='invalidated',invalidated_at=:now,"
            "invalidation_reason=:reason WHERE id=:id AND status='active'"
        ), {"now": now, "reason": str(reason), "id": row[0]})
    return {"tenant_id": str(tenant_id), "derived_type": derived_type,
            "derived_id": str(derived_id), "invalidated_count": len(rows),
            "reason": str(reason), "rebuild_required": bool(rows)}


def register_evidence_payload_dependencies(
    db, *, tenant_id: str, derived_type: str, derived_id: str,
    evidence_items: list[dict[str, Any]], default_source_type: str,
) -> dict[str, Any]:
    """Register only evidence carrying an exact identity and version/timestamp."""
    registered = []
    skipped = []
    for index, item in enumerate(evidence_items or []):
        if not isinstance(item, dict):
            skipped.append({"index": index, "reason": "not_structured"})
            continue
        source_id = str(
            item.get("evidence_id") or item.get("edge_id")
            or item.get("source_record_id") or ""
        ).strip()
        source_version = str(
            item.get("source_version") or item.get("revision")
            or item.get("observed_at") or item.get("effective_at") or ""
        ).strip()
        if not source_id or not source_version:
            skipped.append({"index": index, "reason": "unversioned_evidence"})
            continue
        registered.append(register_derived_dependency(
            db, tenant_id=tenant_id,
            source_type=str(item.get("source_type") or default_source_type),
            source_id=source_id, source_version=source_version,
            derived_type=derived_type, derived_id=derived_id,
        ))
    return {"registered_count": len(registered), "skipped_count": len(skipped),
            "registered": registered, "skipped": skipped}
