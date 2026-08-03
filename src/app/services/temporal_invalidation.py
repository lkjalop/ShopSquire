"""Tenant-scoped dependency registry for explicit temporal retraction.

This module records which derived surfaces consumed an exact source version.  It does not infer
dependencies and it does not delete evidence.  Supersession marks derived records invalid so each
owning projector can rebuild them from the replacement fact.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text


DERIVED_TYPES = frozenset({
    "hippograph_edge", "market_evidence_bundle", "procurement_proposal",
    "buyer_supply_promise", "fulfillment_route_proposal", "narration_fingerprint",
    "allocation_projection", "semantic_cache_entry",
})

CACHE_LIFECYCLE_STATUSES = frozenset({
    "fresh", "stale", "invalidated", "rebuild_queued", "rebuilding",
    "rebuilt", "degraded", "superseded", "failed",
})
SERVABLE_CACHE_STATUSES = frozenset({"fresh", "rebuilt"})
# These are mutable operational authorities. They must be read from their
# transactional read models, never reused from generated/RAG cache content.
_NON_CACHEABLE_AUTHORITY_NAMESPACES = frozenset({
    "atp", "allocation", "demand_allocation", "inventory_reservation",
    "inventory_reservations", "payment_authorization", "buyer_promise",
    "supplier_availability",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_namespace(cache_key: str, namespace: str | None = None) -> str:
    resolved = str(namespace or "").strip().lower()
    if not resolved:
        parts = str(cache_key).split(":", 4)
        resolved = parts[2].strip().lower() if len(parts) > 2 else "unclassified"
    if resolved in _NON_CACHEABLE_AUTHORITY_NAMESPACES:
        raise ValueError("operational_authority_cache_prohibited")
    return resolved


def register_cache_generation(
    db, *, tenant_id: str, cache_key: str, namespace: str | None = None,
    storage_key: str | None = None, content_hash: str | None = None,
) -> dict[str, Any]:
    """Register the first safely published generation for a cache key.

    Registration cannot resurrect an invalidated entry. A replacement must go
    through ``complete_cache_rebuild`` so its generation changes atomically.
    """
    tenant = str(tenant_id)
    key = str(cache_key or "").strip()
    if not key:
        raise ValueError("cache_dependency_key_required")
    cache_namespace = _cache_namespace(key, namespace)
    row = db.execute(text(
        "SELECT id,status,current_generation FROM temporal_cache_entry "
        "WHERE tenant_id=:t AND cache_key=:k"
    ), {"t": tenant, "k": key}).fetchone()
    if row:
        return {
            "entry_id": str(row[0]), "status": str(row[1]),
            "generation": row[2], "idempotent": True,
        }
    now = _now()
    entry_id = str(uuid.uuid4())
    generation_id = str(uuid.uuid4())
    db.execute(text(
        "INSERT INTO temporal_cache_entry "
        "(id,tenant_id,cache_key,namespace,status,current_generation,created_at,updated_at) "
        "VALUES (:id,:t,:k,:ns,'fresh',1,:now,:now)"
    ), {"id": entry_id, "t": tenant, "k": key, "ns": cache_namespace, "now": now})
    db.execute(text(
        "INSERT INTO temporal_cache_generation "
        "(id,entry_id,generation,storage_key,content_hash,status,created_at,published_at) "
        "VALUES (:id,:eid,1,:sk,:ch,'fresh',:now,:now)"
    ), {
        "id": generation_id, "eid": entry_id, "sk": str(storage_key or key),
        "ch": str(content_hash or "") or None, "now": now,
    })
    return {"entry_id": entry_id, "status": "fresh", "generation": 1, "idempotent": False}


def cache_lifecycle(db, *, tenant_id: str, cache_key: str) -> dict[str, Any]:
    row = db.execute(text(
        "SELECT e.id,e.namespace,e.status,e.current_generation,e.pending_generation,e.last_error,"
        "g.storage_key FROM temporal_cache_entry e LEFT JOIN temporal_cache_generation g "
        "ON g.entry_id=e.id AND g.generation=e.current_generation "
        "WHERE e.tenant_id=:t AND e.cache_key=:k"
    ), {"t": str(tenant_id), "k": str(cache_key)}).fetchone()
    if not row:
        return {"tenant_id": str(tenant_id), "cache_key": str(cache_key), "status": "unregistered",
                "servable": False}
    status = str(row[2])
    return {
        "tenant_id": str(tenant_id), "cache_key": str(cache_key), "entry_id": str(row[0]),
        "namespace": str(row[1]), "status": status, "current_generation": row[3],
        "pending_generation": row[4], "last_error": row[5], "storage_key": row[6],
        "servable": status in SERVABLE_CACHE_STATUSES and bool(row[6]),
    }


def tenant_cache_lifecycle_projection(
    db, *, tenant_id: str, cache_key: str | None = None, limit: int = 20,
) -> dict[str, Any]:
    """Read-only operator projection; exact-key views are trace-safe.

    Without a key the result is explicitly labelled tenant-wide so consumers
    cannot present unrelated cache state as evidence for one decision.
    """
    if "temporal_cache_entry" not in inspect(db.connection()).get_table_names():
        return {"scope": "tenant", "entries": []}
    params: dict[str, Any] = {
        "tenant": str(tenant_id), "limit": max(1, min(int(limit), 100)),
    }
    key_clause = ""
    if cache_key:
        params["cache_key"] = str(cache_key)
        key_clause = " AND e.cache_key=:cache_key"
    rows = db.execute(text(
        "SELECT e.id,e.cache_key,e.namespace,e.status,e.current_generation,"
        "e.pending_generation,e.last_error,e.updated_at,g.storage_key,g.content_hash,"
        "j.id,j.status,j.source_type,j.source_id,j.source_version,j.reason,j.created_at "
        "FROM temporal_cache_entry e LEFT JOIN temporal_cache_generation g "
        "ON g.entry_id=e.id AND g.generation=e.current_generation "
        "LEFT JOIN temporal_cache_rebuild_job j ON j.id=("
        "SELECT j2.id FROM temporal_cache_rebuild_job j2 WHERE j2.entry_id=e.id "
        "ORDER BY j2.created_at DESC LIMIT 1) "
        "WHERE e.tenant_id=:tenant" + key_clause +
        " ORDER BY e.updated_at DESC LIMIT :limit"
    ), params).fetchall()
    return {
        "scope": "exact_cache_key" if cache_key else "tenant_operator_summary",
        "case_specific": bool(cache_key),
        "stale_content_served": False,
        "entries": [
            {
                "entry_id": str(row[0]), "cache_key": str(row[1]),
                "namespace": str(row[2]), "status": str(row[3]),
                "current_generation": row[4], "pending_generation": row[5],
                "last_error": row[6], "updated_at": row[7],
                "storage_key": row[8], "content_hash": row[9],
                "rebuild_job_id": str(row[10]) if row[10] else None,
                "rebuild_status": row[11], "source_type": row[12],
                "source_id": row[13], "source_version": row[14],
                "rebuild_reason": row[15], "rebuild_created_at": row[16],
                "servable": str(row[3]) in SERVABLE_CACHE_STATUSES and bool(row[8]),
            }
            for row in rows
        ],
    }


def read_current_cache(db, *, tenant_id: str, cache_key: str, cache: Any) -> Any:
    """Fail closed unless the durable generation pointer is currently servable."""
    state = cache_lifecycle(db, tenant_id=tenant_id, cache_key=cache_key)
    if not state["servable"]:
        return None
    return cache.get(str(state["storage_key"]))


def mark_cache_stale(db, *, tenant_id: str, cache_key: str, reason: str) -> dict[str, Any]:
    """Mark an entry stale without pretending that its content disappeared."""
    now = _now()
    result = db.execute(text(
        "UPDATE temporal_cache_entry SET status='stale',last_error=:reason,updated_at=:now "
        "WHERE tenant_id=:t AND cache_key=:k AND status IN ('fresh','rebuilt')"
    ), {"reason": str(reason), "now": now, "t": str(tenant_id), "k": str(cache_key)})
    return {"tenant_id": str(tenant_id), "cache_key": str(cache_key), "status": "stale",
            "changed": bool(result.rowcount)}


def supersede_cache_entry(
    db, *, tenant_id: str, cache_key: str, reason: str, cache: Any | None = None,
) -> dict[str, Any]:
    """Terminally supersede an entry; a replacement must use a new cache key."""
    now = _now()
    row = db.execute(text(
        "SELECT id,current_generation FROM temporal_cache_entry WHERE tenant_id=:t AND cache_key=:k"
    ), {"t": str(tenant_id), "k": str(cache_key)}).fetchone()
    if not row:
        return {"tenant_id": str(tenant_id), "cache_key": str(cache_key),
                "status": "unregistered", "changed": False}
    db.execute(text(
        "UPDATE temporal_cache_entry SET status='superseded',pending_generation=NULL,"
        "last_error=:reason,updated_at=:now WHERE id=:id"
    ), {"reason": str(reason), "now": now, "id": str(row[0])})
    db.execute(text(
        "UPDATE temporal_cache_generation SET status='superseded',superseded_at=:now "
        "WHERE entry_id=:eid AND generation=:gen AND status IN ('fresh','rebuilt')"
    ), {"now": now, "eid": str(row[0]), "gen": row[1]})
    if cache is not None:
        try:
            cache.delete(str(cache_key))
        except Exception:
            pass
    return {"tenant_id": str(tenant_id), "cache_key": str(cache_key),
            "status": "superseded", "changed": True}


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
    namespace: str | None = None,
) -> dict[str, Any]:
    """Bind one exact cache key to one exact source revision."""
    key = str(cache_key or "").strip()
    if not key:
        raise ValueError("cache_dependency_key_required")
    generation = register_cache_generation(
        db, tenant_id=tenant_id, cache_key=key, namespace=namespace,
    )
    dependency = register_derived_dependency(
        db,
        tenant_id=tenant_id,
        source_type=source_type,
        source_id=source_id,
        source_version=source_version,
        derived_type="semantic_cache_entry",
        derived_id=key,
    )
    return {**dependency, "cache_status": generation["status"],
            "cache_generation": generation["generation"]}


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
    enqueue_rebuild: Any = None,
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
    eviction_failures = []
    enqueued = 0
    projector_backlog = []
    for item in result["invalidated"]:
        if item["derived_type"] != "semantic_cache_entry":
            projector_backlog.append(item)
            continue
        cache_key = str(item["derived_id"])
        # The durable pointer is invalidated before any best-effort provider
        # eviction. This prevents stale serving even when Redis is unavailable.
        entry = db.execute(text(
            "SELECT id FROM temporal_cache_entry WHERE tenant_id=:t AND cache_key=:k"
        ), {"t": str(tenant_id), "k": cache_key}).fetchone()
        if not entry:
            projector_backlog.append({**item, "reason": "cache_lifecycle_unregistered"})
            continue
        entry_id = str(entry[0])
        now = _now()
        db.execute(text(
            "UPDATE temporal_cache_entry SET status='invalidated',updated_at=:now,last_error=NULL "
            "WHERE id=:id"
        ), {"now": now, "id": entry_id})
        try:
            cache.delete(cache_key)
            evicted += 1
        except Exception as exc:
            eviction_failures.append({"cache_key": cache_key, "error": type(exc).__name__})
        idem_material = "|".join((str(tenant_id), cache_key, str(source_type), str(source_id),
                                  str(source_version), str(reason)))
        idem = hashlib.sha256(idem_material.encode("utf-8")).hexdigest()
        job = db.execute(text(
            "SELECT id,status FROM temporal_cache_rebuild_job "
            "WHERE tenant_id=:t AND idempotency_key=:idem"
        ), {"t": str(tenant_id), "idem": idem}).fetchone()
        if job:
            continue
        job_id = str(uuid.uuid4())
        db.execute(text(
            "INSERT INTO temporal_cache_rebuild_job "
            "(id,tenant_id,entry_id,cache_key,idempotency_key,status,source_type,source_id,"
            "source_version,reason,attempts,created_at) VALUES "
            "(:id,:t,:eid,:k,:idem,'queued',:st,:sid,:sv,:reason,0,:now)"
        ), {"id": job_id, "t": str(tenant_id), "eid": entry_id, "k": cache_key,
             "idem": idem, "st": str(source_type), "sid": str(source_id),
             "sv": str(source_version), "reason": str(reason), "now": now})
        db.execute(text(
            "UPDATE temporal_cache_entry SET status='rebuild_queued',updated_at=:now WHERE id=:id"
        ), {"now": now, "id": entry_id})
        payload = {
            "job_type": "rebuild_temporal_cache_entry",
            "job_id": job_id,
            "tenant_id": str(tenant_id),
            "cache_key": cache_key,
            "source_type": str(source_type),
            "source_id": str(source_id),
            "source_version": str(source_version),
            "reason": str(reason),
        }
        if enqueue_rebuild is not None:
            enqueue_rebuild(payload)
        enqueued += 1
    return {
        **result,
        "cache_entries_evicted": evicted,
        "cache_eviction_failures": eviction_failures,
        "rebuilds_enqueued": enqueued,
        "projector_backlog": projector_backlog,
    }


def claim_cache_rebuild(db, *, tenant_id: str, job_id: str) -> dict[str, Any]:
    """Idempotently claim one tenant-owned queued rebuild."""
    row = db.execute(text(
        "SELECT id,entry_id,cache_key,status,attempts FROM temporal_cache_rebuild_job "
        "WHERE id=:id AND tenant_id=:t"
    ), {"id": str(job_id), "t": str(tenant_id)}).fetchone()
    if not row:
        raise ValueError("cache_rebuild_job_not_found")
    if str(row[3]) not in {"queued", "degraded"}:
        return {"job_id": str(row[0]), "status": str(row[3]), "idempotent": True,
                "cache_key": str(row[2])}
    now = _now()
    next_generation = db.execute(text(
        "SELECT COALESCE(MAX(generation),0)+1 FROM temporal_cache_generation WHERE entry_id=:eid"
    ), {"eid": str(row[1])}).scalar()
    db.execute(text(
        "UPDATE temporal_cache_rebuild_job SET status='running',attempts=attempts+1,started_at=:now "
        "WHERE id=:id AND status IN ('queued','degraded')"
    ), {"now": now, "id": str(job_id)})
    db.execute(text(
        "UPDATE temporal_cache_entry SET status='rebuilding',pending_generation=:gen,updated_at=:now "
        "WHERE id=:eid"
    ), {"gen": int(next_generation), "now": now, "eid": str(row[1])})
    return {"job_id": str(row[0]), "entry_id": str(row[1]), "cache_key": str(row[2]),
            "status": "running", "generation": int(next_generation), "idempotent": False}


def complete_cache_rebuild(
    db, *, tenant_id: str, job_id: str, storage_key: str, content_hash: str | None = None,
) -> dict[str, Any]:
    """Atomically publish the rebuilt generation and supersede the old pointer."""
    row = db.execute(text(
        "SELECT j.entry_id,j.status,e.pending_generation,e.current_generation,j.cache_key "
        "FROM temporal_cache_rebuild_job j JOIN temporal_cache_entry e ON e.id=j.entry_id "
        "WHERE j.id=:id AND j.tenant_id=:t"
    ), {"id": str(job_id), "t": str(tenant_id)}).fetchone()
    if not row:
        raise ValueError("cache_rebuild_job_not_found")
    if str(row[1]) == "succeeded":
        return {"job_id": str(job_id), "status": "rebuilt", "generation": row[3],
                "idempotent": True}
    if str(row[1]) != "running" or row[2] is None:
        raise ValueError("cache_rebuild_not_running")
    now = _now()
    db.execute(text(
        "UPDATE temporal_cache_generation SET status='superseded',superseded_at=:now "
        "WHERE entry_id=:eid AND generation=:gen AND status IN ('fresh','rebuilt')"
    ), {"now": now, "eid": str(row[0]), "gen": row[3]})
    db.execute(text(
        "INSERT INTO temporal_cache_generation "
        "(id,entry_id,generation,storage_key,content_hash,status,created_at,published_at) "
        "VALUES (:id,:eid,:gen,:sk,:ch,'rebuilt',:now,:now)"
    ), {"id": str(uuid.uuid4()), "eid": str(row[0]), "gen": int(row[2]),
         "sk": str(storage_key), "ch": str(content_hash or "") or None, "now": now})
    db.execute(text(
        "UPDATE temporal_cache_entry SET status='rebuilt',current_generation=:gen,"
        "pending_generation=NULL,last_error=NULL,updated_at=:now WHERE id=:eid"
    ), {"gen": int(row[2]), "now": now, "eid": str(row[0])})
    db.execute(text(
        "UPDATE temporal_cache_rebuild_job SET status='succeeded',finished_at=:now,last_error=NULL "
        "WHERE id=:id"
    ), {"now": now, "id": str(job_id)})
    return {"job_id": str(job_id), "cache_key": str(row[4]), "status": "rebuilt",
            "generation": int(row[2]), "idempotent": False}


def fail_cache_rebuild(
    db, *, tenant_id: str, job_id: str, error: str, retryable: bool,
) -> dict[str, Any]:
    status = "degraded" if retryable else "failed"
    entry_status = "degraded" if retryable else "failed"
    now = _now()
    row = db.execute(text(
        "SELECT entry_id FROM temporal_cache_rebuild_job WHERE id=:id AND tenant_id=:t"
    ), {"id": str(job_id), "t": str(tenant_id)}).fetchone()
    if not row:
        raise ValueError("cache_rebuild_job_not_found")
    db.execute(text(
        "UPDATE temporal_cache_rebuild_job SET status=:status,finished_at=:now,last_error=:err "
        "WHERE id=:id"
    ), {"status": status, "now": now, "err": str(error)[:2000], "id": str(job_id)})
    db.execute(text(
        "UPDATE temporal_cache_entry SET status=:status,pending_generation=NULL,last_error=:err,"
        "updated_at=:now WHERE id=:eid"
    ), {"status": entry_status, "err": str(error)[:2000], "now": now, "eid": str(row[0])})
    return {"job_id": str(job_id), "status": status, "servable": False}


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
