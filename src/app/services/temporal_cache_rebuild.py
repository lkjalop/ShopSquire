"""Bounded worker orchestration for durable temporal cache rebuilds."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy import inspect
import json

from src.app.services.temporal_invalidation import (
    claim_cache_rebuild,
    complete_cache_rebuild,
    fail_cache_rebuild,
)


RebuildHandler = Callable[[dict[str, Any]], dict[str, Any]]
_HANDLERS: dict[str, RebuildHandler] = {}


def register_rebuild_handler(namespace: str, handler: RebuildHandler) -> None:
    key = str(namespace or "").strip().lower()
    if not key:
        raise ValueError("cache_namespace_required")
    _HANDLERS[key] = handler


def unregister_rebuild_handler(namespace: str) -> None:
    _HANDLERS.pop(str(namespace or "").strip().lower(), None)


def dispatch_queued_rebuilds(
    db, *, dispatch: Callable[[str, str], None], tenant_id: str | None = None, limit: int = 50,
) -> dict[str, Any]:
    """Dispatch committed durable jobs with at-least-once, idempotent semantics."""
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 200))}
    tenant_clause = ""
    if tenant_id is not None:
        tenant_clause = " AND tenant_id=:tenant_id"
        params["tenant_id"] = str(tenant_id)
    rows = db.execute(text(
        "SELECT id,tenant_id FROM temporal_cache_rebuild_job WHERE status='queued' "
        f"AND dispatched_at IS NULL{tenant_clause} ORDER BY created_at,id LIMIT :limit"
    ), params).fetchall()
    dispatched = []
    failed = []
    for row in rows:
        job_id, owner_tenant = str(row[0]), str(row[1])
        try:
            dispatch(owner_tenant, job_id)
            db.execute(text(
                "UPDATE temporal_cache_rebuild_job SET dispatched_at=CURRENT_TIMESTAMP,"
                "dispatch_attempts=dispatch_attempts+1 WHERE id=:id AND tenant_id=:t "
                "AND status='queued'"
            ), {"id": job_id, "t": owner_tenant})
            dispatched.append(job_id)
        except Exception as exc:
            db.execute(text(
                "UPDATE temporal_cache_rebuild_job SET dispatch_attempts=dispatch_attempts+1,"
                "last_error=:err WHERE id=:id AND tenant_id=:t AND status='queued'"
            ), {"err": f"dispatch:{type(exc).__name__}"[:2000], "id": job_id,
                 "t": owner_tenant})
            failed.append(job_id)
    return {"examined": len(rows), "dispatched": dispatched, "failed": failed}


def execute_cache_rebuild(db, *, tenant_id: str, job_id: str) -> dict[str, Any]:
    """Claim and run a rebuild without ever falling back to stale content."""
    claimed = claim_cache_rebuild(db, tenant_id=tenant_id, job_id=job_id)
    if claimed.get("idempotent"):
        return claimed
    has_binding = "temporal_cache_binding" in inspect(db.connection()).get_table_names()
    binding_select = (
        ",b.rebuild_payload_json FROM temporal_cache_rebuild_job j "
        "JOIN temporal_cache_entry e ON e.id=j.entry_id LEFT JOIN temporal_cache_binding b "
        "ON b.tenant_id=j.tenant_id AND b.cache_key=j.cache_key "
        if has_binding else
        ",NULL FROM temporal_cache_rebuild_job j "
        "JOIN temporal_cache_entry e ON e.id=j.entry_id "
    )
    row = db.execute(text(
        "SELECT e.namespace,j.source_type,j.source_id,j.source_version,j.reason" +
        binding_select + "WHERE j.id=:id AND j.tenant_id=:t"
    ), {"id": str(job_id), "t": str(tenant_id)}).fetchone()
    namespace = str(row[0]).lower()
    handler = _HANDLERS.get(namespace)
    if handler is None:
        from src.app.services.temporal_cache_producers import default_rebuild_handler

        handler = default_rebuild_handler(namespace)
    if handler is None:
        return fail_cache_rebuild(
            db, tenant_id=tenant_id, job_id=job_id,
            error=f"rebuild_handler_unavailable:{namespace}", retryable=True,
        )
    try:
        rebuild_payload = json.loads(str(row[5] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        rebuild_payload = {}
    request = {
        **claimed, "tenant_id": str(tenant_id), "namespace": namespace,
        "cache_key": str(claimed.get("cache_key") or ""),
        "source_type": str(row[1]), "source_id": str(row[2]),
        "source_version": str(row[3]), "reason": str(row[4]),
        "rebuild_payload": rebuild_payload,
    }
    try:
        result = handler(request)
        storage_key = str((result or {}).get("storage_key") or "").strip()
        if not storage_key:
            raise ValueError("rebuilt_storage_key_required")
        return complete_cache_rebuild(
            db, tenant_id=tenant_id, job_id=job_id, storage_key=storage_key,
            content_hash=str((result or {}).get("content_hash") or "") or None,
        )
    except Exception as exc:
        fail_cache_rebuild(
            db, tenant_id=tenant_id, job_id=job_id,
            error=f"{type(exc).__name__}: {exc}", retryable=True,
        )
        raise
