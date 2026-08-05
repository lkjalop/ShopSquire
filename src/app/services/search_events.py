from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.deps import redact_for_trace, security_sanitize, hash_uid, scrub_pii

logger = logging.getLogger("shopsquire.search_events")


def ensure_search_events_table() -> None:
    """Compatibility no-op: Alembic owns the production schema."""
    return None


def log_search_event(
    *,
    uid: str,
    query: str,
    filters: Dict[str, Any] | None,
    result_skus: List[str] | None,
    view_mode: str | None,
    trace_id: str | None,
    session_id: str | None = None,
    tenant_id: str = "default",
    case_id: str | None = None,
    session_epoch: str | None = None,
    requirement: Dict[str, Any] | None = None,
    requested_quantity: int | None = None,
    qualification_outcome: str = "unresolved",
    lifecycle_stage: str = "search_interest",
    unresolved_concept: str | None = None,
    resolved_sku: str | None = None,
    evidence_refs: List[str] | None = None,
    source_policy_status: str = "not_evaluated",
    actor_dedup_class: str = "distinct_actor",
    abuse_status: str = "not_evaluated",
    inventory_snapshot: Dict[str, Any] | None = None,
    simulation_only: bool = False,
) -> Optional[str]:
    event_id = str(uuid.uuid4())
    safe_query = scrub_pii(query or "")
    safe_filters = redact_for_trace(security_sanitize(filters or {}))
    safe_skus = [str(s) for s in (result_skus or []) if s]
    payload = {
        "id": event_id,
        "uid_hash": hash_uid(uid),
        "query": safe_query,
        "filters_json": json.dumps(safe_filters, ensure_ascii=False),
        "result_skus_json": json.dumps(safe_skus, ensure_ascii=False),
        "result_count": len(safe_skus),
        "view_mode": view_mode or "",
        "trace_id": trace_id or "",
        "session_id": session_id or "",
    }
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO search_events (
                        id, uid_hash, query, filters_json, result_skus_json,
                        result_count, view_mode, trace_id, session_id
                    ) VALUES (
                        :id, :uid_hash, :query, :filters_json, :result_skus_json,
                        :result_count, :view_mode, :trace_id, :session_id
                    )
                    """
                ),
                payload,
            )
            db.commit()
    except Exception as exc:
        logger.warning("legacy search event persistence failed: %s", exc)
        return None

    try:
        from src.app.services.search_demand_authority import append_search_observation

        canonical_sku = str(resolved_sku or "").strip() or (safe_skus[0] if len(safe_skus) == 1 else None)
        with db_session() as db:
            append_search_observation(
                db,
                tenant_id=str(tenant_id or "default"),
                trace_id=str(trace_id or event_id),
                case_id=case_id,
                session_epoch=str(session_epoch or session_id or trace_id or event_id),
                actor_hash=payload["uid_hash"],
                query=safe_query,
                requirement=dict(requirement or {"filters": safe_filters}),
                requested_quantity=requested_quantity,
                resolved_sku=canonical_sku,
                unresolved_concept=unresolved_concept,
                qualification_outcome=qualification_outcome,
                lifecycle_stage=lifecycle_stage,
                evidence_refs=evidence_refs or [],
                source_policy_status=source_policy_status,
                actor_dedup_class=actor_dedup_class,
                abuse_status=abuse_status,
                inventory_snapshot=inventory_snapshot,
                simulation_only=simulation_only,
            )
            db.commit()
    except Exception as exc:
        # Search analytics must not break the buyer path, but failure is observable.
        logger.warning("canonical search observation persistence failed: %s", exc)
    return event_id
