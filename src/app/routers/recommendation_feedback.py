"""Recommendation interaction and correction endpoints.

These endpoints own outcome evidence. They do not rank products or invoke the
legacy recommendation implementation.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from src.app.deps import get_redis, hash_uid, security_sanitize
from src.app.models.db import get_db
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import (
    ROLE_DEVELOPER,
    ROLE_MERCHANT,
    ROLE_OWNER,
    require_role,
)
from src.app.services.checkout_upsell import ensure_recommend_interactions_table
from src.app.services.decision_log import log_trace_event
from src.app.services.memory import Memory
from src.app.services.recommendation_bandit import (
    ensure_recommend_bandit_tables,
    record_bandit_reward,
)
from src.app.services.recommendation_identity_graph import (
    ensure_identity_graph_tables,
    register_identity_observations,
)


router = APIRouter(prefix="/api/v1/recommend", tags=["recommendation-feedback"])


class RecommendInteractionPayload(BaseModel):
    uid: str
    sku: str
    action: str
    surface: str = "checkout_upsell"
    trace_id: str | None = None
    context: Dict[str, Any] | None = None


class RecommendFeedbackPayload(BaseModel):
    uid: str
    trace_id: str | None = None
    sku: str | None = None
    outcome: str
    correction_text: str | None = None
    context: Dict[str, Any] | None = None


@router.post("/interaction")
def log_recommend_interaction(
    payload: RecommendInteractionPayload,
    db=Depends(get_db),
    role: str = Depends(
        require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])
    ),
) -> Dict[str, Any]:
    del role
    action = str(payload.action or "").strip().lower()
    allowed = {
        "hover", "click", "view", "add_to_cart", "atc", "cart_add",
        "reject", "dismiss", "dislike", "purchase",
    }
    if action not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                "action must be one of: hover, click, view, add_to_cart, "
                "reject, dismiss, dislike, purchase"
            ),
        )
    sku = str(payload.sku or "").strip()
    if not sku:
        raise HTTPException(status_code=400, detail="sku required")

    ensure_recommend_interactions_table(db)
    ensure_identity_graph_tables(db)
    ensure_recommend_bandit_tables(db)
    event_id = str(uuid.uuid4())
    uid_hash = hash_uid(payload.uid)
    safe_context = security_sanitize(payload.context or {})
    trace_id = str(payload.trace_id or "")
    tenant_id = current_tenant_id()
    try:
        db.execute(
            text(
                """
                INSERT INTO recommend_interactions (
                    id, tenant_id, consent_state, uid_hash, sku, action, surface,
                    trace_id, context_json
                ) VALUES (
                    :id, :tenant_id, :consent_state, :uid_hash, :sku, :action,
                    :surface, :trace_id, :context_json
                )
                """
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "consent_state": str(
                    safe_context.get("consent_state") or "unknown"
                ),
                "uid_hash": uid_hash,
                "sku": sku,
                "action": action,
                "surface": str(payload.surface or "checkout_upsell"),
                "trace_id": trace_id,
                "context_json": json.dumps(safe_context, ensure_ascii=False),
            },
        )
        try:
            register_identity_observations(
                db,
                uid_hash=uid_hash,
                context=safe_context,
                source="recommend_interaction",
            )
        except Exception:
            pass
        try:
            from src.app.services.attribution import arm_for_trace

            reward_map = {
                "hover": 0.1,
                "view": 0.2,
                "click": 0.7,
                "add_to_cart": 1.0,
                "atc": 1.0,
                "cart_add": 1.0,
                "purchase": 1.5,
                "reject": -0.6,
                "dismiss": -0.4,
                "dislike": -0.5,
            }
            arm = (
                str(safe_context.get("bandit_arm") or "").strip()
                or arm_for_trace(
                    db, trace_id, tenant_id=current_tenant_id(),
                )
            )
            bandit_context = (
                safe_context.get("bandit_context")
                if isinstance(safe_context.get("bandit_context"), dict)
                else safe_context
            )
            record_bandit_reward(
                db,
                uid_hash=uid_hash,
                sku=sku,
                arm=arm,
                reward=float(reward_map.get(action, 0.0)),
                context=bandit_context,
            )
        except Exception:
            pass
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"interaction_log_failed: {exc}"
        ) from exc
    return {"status": "ok", "event_id": event_id}


@router.post("/feedback")
def recommend_feedback(
    payload: RecommendFeedbackPayload,
    db=Depends(get_db),
    redis=Depends(get_redis),
    role: str = Depends(
        require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])
    ),
) -> Dict[str, Any]:
    del role
    outcome = str(payload.outcome or "").strip().lower()
    if outcome not in {
        "accepted", "rejected", "corrected", "purchased", "dismissed",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "outcome must be one of: accepted, rejected, corrected, "
                "purchased, dismissed"
            ),
        )

    ensure_recommend_interactions_table(db)
    ensure_recommend_bandit_tables(db)
    ensure_identity_graph_tables(db)

    uid_hash = hash_uid(payload.uid)
    safe_context = security_sanitize(payload.context or {})
    sku = str(payload.sku or "").strip()
    trace_id = str(payload.trace_id or "").strip()
    action = {
        "accepted": "click",
        "purchased": "purchase",
        "rejected": "reject",
        "dismissed": "dismiss",
        "corrected": "dislike",
    }.get(outcome, "view")
    event_id = str(uuid.uuid4())

    try:
        db.execute(
            text(
                """
                INSERT INTO recommend_interactions (
                    id, tenant_id, consent_state, uid_hash, sku, action, surface,
                    trace_id, context_json
                ) VALUES (
                    :id, :tenant_id, :consent_state, :uid_hash, :sku, :action,
                    :surface, :trace_id, :context_json
                )
                """
            ),
            {
                "id": event_id,
                "tenant_id": current_tenant_id(),
                "consent_state": str(
                    safe_context.get("consent_state") or "unknown"
                ),
                "uid_hash": uid_hash,
                "sku": sku,
                "action": action,
                "surface": "user_feedback",
                "trace_id": trace_id,
                "context_json": json.dumps(
                    {**safe_context, "outcome": outcome}, ensure_ascii=False
                ),
            },
        )
        if sku:
            from src.app.services.attribution import arm_for_trace

            record_bandit_reward(
                db,
                uid_hash=uid_hash,
                sku=sku,
                arm=(
                    str(safe_context.get("bandit_arm") or "").strip()
                    or arm_for_trace(
                        db, trace_id, tenant_id=current_tenant_id(),
                    )
                ),
                reward=float({
                    "accepted": 1.0,
                    "purchased": 1.5,
                    "rejected": -0.6,
                    "dismissed": -0.4,
                    "corrected": -0.7,
                }.get(outcome, 0.0)),
                context=safe_context,
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"feedback_record_failed: {exc}"
        ) from exc

    correction = str(payload.correction_text or "").strip()
    if correction:
        try:
            memory = Memory(redis)
            state = memory.get_kv(payload.uid) or {}
            corrections = (
                state.get("user_corrections")
                if isinstance(state.get("user_corrections"), list)
                else []
            )
            corrections.append({
                "ts": int(time.time()),
                "trace_id": trace_id,
                "text": correction[:500],
            })
            state["user_corrections"] = corrections[-20:]
            memory.set_kv(payload.uid, state)
        except Exception:
            pass

    if trace_id:
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="user_feedback",
                source_type="user",
                source_id=payload.uid,
                target_type="stage",
                target_id="recommendation_feedback",
                payload={
                    "outcome": outcome,
                    "sku": sku or None,
                    "has_correction_text": bool(correction),
                },
            )
        except Exception:
            pass

    return {"status": "ok", "event_id": event_id, "outcome": outcome}
