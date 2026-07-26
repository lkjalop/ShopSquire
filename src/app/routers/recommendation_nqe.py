"""Owned next-question-evaluation endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text

from src.app.deps import get_redis
from src.app.models.db import get_db
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import (
    ROLE_DEVELOPER,
    ROLE_MERCHANT,
    ROLE_OWNER,
    require_role,
)
from src.app.services.bulk_intent import extract_quantity_span
from src.app.services.decision_log import log_trace_event
from src.app.services.memory import Memory
from src.app.services.recommendations import RecommendationService


router = APIRouter(prefix="/api/v1/recommend", tags=["recommendation-nqe"])


@router.get("/nqe_slots")
def nqe_slots(
    uid: str,
    query: str,
    redis=Depends(get_redis),
) -> Dict[str, Any]:
    context = Memory(redis).get_context(uid) or {}
    state = context.get("kv") or {}
    service = RecommendationService(session=None)
    try:
        parsed = service.parse_constraints(query) or {}
    except Exception:
        parsed = {}

    preferences = state.get("prefs_meta") or {}
    slots: list[Dict[str, Any]] = []
    if not (
        parsed.get("budget_min") is not None
        or parsed.get("budget_max") is not None
        or preferences.get("budget_max")
    ):
        slots.append({
            "name": "budget",
            "confidence": 0.9,
            "reason": "no_budget_in_query_or_prefs",
        })
    if not (parsed.get("specs") or preferences.get("specs")):
        slots.append({"name": "specs", "confidence": 0.85, "reason": "no_specs"})
    if not (parsed.get("use_case") or preferences.get("use_case")):
        slots.append({
            "name": "use_case",
            "confidence": 0.7,
            "reason": "no_use_case",
        })
    if extract_quantity_span(query) is None:
        slots.append({
            "name": "quantity",
            "confidence": 0.6,
            "reason": "no_quantity",
        })
    if not parsed.get("availability"):
        slots.append({
            "name": "availability",
            "confidence": 0.5,
            "reason": "no_availability",
        })
    if not parsed.get("brands"):
        slots.append({"name": "brand", "confidence": 0.4, "reason": "no_brand"})
    slots.sort(key=lambda item: item["confidence"], reverse=True)
    return {
        "slots": slots,
        "context": {
            "prefs_meta": preferences,
            "last_query": state.get("last_query"),
            "session_id": state.get("session_id"),
        },
    }


@router.post("/nqe_feedback")
def nqe_feedback(
    payload: Dict[str, Any] = Body(default_factory=dict),
    db=Depends(get_db),
    role: str = Depends(
        require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])
    ),
) -> Dict[str, Any]:
    del role
    trace_id = str(payload.get("trace_id") or "").strip()
    question_id = str(payload.get("question_id") or "").strip()
    if not trace_id or not question_id:
        raise HTTPException(
            status_code=400, detail="trace_id and question_id required"
        )
    tenant_id = current_tenant_id()
    requested_tenant = str(payload.get("tenant_id") or tenant_id).strip()
    if requested_tenant != tenant_id:
        raise HTTPException(status_code=403, detail="cross_tenant_nqe_feedback")

    variant = str(payload.get("variant") or "control")
    converted = bool(payload.get("converted", False))
    latency_ms = max(0, int(payload.get("latency_ms") or 0))
    answer_value = str(payload.get("answer_value") or "")[:255]
    helpful = payload.get("helpful")
    helpful_value = None if helpful is None else bool(helpful)
    event_id = str(uuid.uuid4())
    try:
        db.execute(
            text(
                """
                INSERT INTO nqe_feedback_events (
                    id, tenant_id, trace_id, question_id, variant, converted,
                    latency_ms, answer_value, helpful
                ) VALUES (
                    :id, :tenant_id, :trace_id, :question_id, :variant,
                    :converted, :latency_ms, :answer_value, :helpful
                )
                """
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "trace_id": trace_id,
                "question_id": question_id,
                "variant": variant,
                "converted": converted,
                "latency_ms": latency_ms,
                "answer_value": answer_value,
                "helpful": helpful_value,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=f"nqe_feedback_store_unavailable: {exc}",
        ) from exc

    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="nqe_user_answer_bound",
            source_type="stage",
            source_id="next_question_evaluation",
            target_type="template",
            target_id=question_id,
            payload={
                "variant": variant,
                "converted": converted,
                "latency_ms": latency_ms,
                "tenant_id": tenant_id,
                "answer_value": answer_value,
                "helpful": helpful_value,
            },
        )
    except Exception:
        pass
    return {"status": "ok", "trace_id": trace_id, "question_id": question_id}


@router.get("/admin/nqe_feedback_summary")
def nqe_feedback_summary(
    tenant_id: str | None = None,
    days: int = 30,
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    del role
    active_tenant = current_tenant_id()
    if tenant_id and str(tenant_id).strip() != active_tenant:
        raise HTTPException(status_code=403, detail="cross_tenant_nqe_summary")
    days = max(1, min(int(days or 30), 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        rows = db.execute(
            text(
                """
                SELECT variant,
                       COUNT(*) AS n,
                       SUM(CASE WHEN converted = true THEN 1 ELSE 0 END) AS conv
                FROM nqe_feedback_events
                WHERE tenant_id = :tenant_id AND created_at >= :cutoff
                GROUP BY variant
                """
            ),
            {"tenant_id": active_tenant, "cutoff": cutoff},
        ).fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"nqe_feedback_summary_unavailable: {exc}",
        ) from exc
    items = []
    for row in rows or []:
        samples = int(row[1] or 0)
        converted = int(row[2] or 0)
        items.append({
            "variant": str(row[0] or "control"),
            "samples": samples,
            "conversion_rate": float(converted) / float(max(1, samples)),
        })
    return {
        "status": "ok",
        "tenant_id": active_tenant,
        "days": days,
        "items": items,
    }
