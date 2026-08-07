"""Owned recommendation explanation endpoint."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from opentelemetry import trace

from src.app.config import get_settings, load_feature_flags
from src.app.deps import get_redis
from src.app.models.db import get_db
from src.app.security.auth import (
    ROLE_DEVELOPER,
    ROLE_MERCHANT,
    ROLE_OWNER,
    require_role,
)
from src.app.services.decision_log import get_cached_trace_events, log_trace_event
from src.app.services.catalog_read_model import get_variant
from src.app.services.memory import Memory
from src.app.services.recommendations import RecommendationService


router = APIRouter(prefix="/api/v1/recommend", tags=["recommendation-explain"])


def _current_trace_id() -> str | None:
    try:
        context = trace.get_current_span().get_span_context()
        if context and context.trace_id:
            return f"{context.trace_id:032x}"
    except Exception:
        return None
    return None


def _trace_metadata(*, policy_version: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "bitemporal": {
            "valid_from": now,
            "valid_to": "infinity",
            "system_from": now,
            "system_to": "infinity",
        },
        "recorded_at": now,
        "context_ids": ["constraints", "factors", "ranking"],
        "policy_version": policy_version,
    }


def build_sku_explanation(
    *,
    row: Dict[str, Any],
    constraints: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    factors = row.get("factors") if isinstance(row.get("factors"), dict) else {}
    positive = [str(value) for value in factors.get("positive") or []][:8]
    negative = [str(value) for value in factors.get("negative") or []][:8]
    checks = [str(value) for value in factors.get("checks") or []][:8]
    matched: list[str] = []
    if constraints.get("budget_max") is not None or constraints.get("budget_min") is not None:
        if any("within_budget" in value for value in positive):
            matched.append("budget")
    if constraints.get("brands") and any("brand_match" in value for value in positive):
        matched.append("brand")
    if constraints.get("specs") and any(
        str(spec).lower().strip("+") in " ".join(positive).lower()
        for spec in constraints.get("specs") or []
    ):
        matched.append("specs")
    if constraints.get("use_case") and any(
        "use_case_match" in value for value in positive
    ):
        matched.append("use_case")

    reasons: list[str] = []
    evidence_status = str(row.get("_explanation_scope") or "rank_factors")
    if evidence_status == "catalog_only":
        reasons.append(
            "This product is verified in the tenant catalog, but detailed ranking "
            "factors were not retained for this explanation request."
        )
    elif positive:
        reasons.append(f"Selected because it matched: {', '.join(positive[:4])}.")
    if checks:
        reasons.append(f"Additional checks considered: {', '.join(checks[:3])}.")
    if negative:
        reasons.append(f"Tradeoffs noted: {', '.join(negative[:3])}.")
    if not reasons:
        reasons.append(
            "Selected based on overall rank score and inventory availability."
        )
    return {
        "sku": str(row.get("sku") or ""),
        "name": row.get("name"),
        "score": row.get("score"),
        "confidence": row.get("confidence"),
        "matched_constraints": matched,
        "disqualifiers": negative,
        "positive_factors": positive,
        "checks": checks,
        "reason_summary": " ".join(reasons),
        "evidence_status": evidence_status,
        "query": str(query or ""),
    }


def _canonical_fit_explanation(
    structured_state: Dict[str, Any],
    target_sku: str,
) -> Dict[str, Any] | None:
    explanation = structured_state.get("last_product_explanation")
    if not isinstance(explanation, dict):
        return None
    if str(explanation.get("sku") or "").strip() != str(target_sku or "").strip():
        return None
    if not isinstance(explanation.get("fit_ledger"), list):
        return None
    return dict(explanation)


def _canonical_fit_explanation_from_trace(
    trace_id: str | None,
    target_sku: str,
) -> Dict[str, Any] | None:
    if not trace_id:
        return None
    for event in reversed(get_cached_trace_events(str(trace_id))):
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict):
            continue
        right_panel = payload.get("right_panel_contract")
        candidates = [
            payload.get("explanation"),
            right_panel.get("explanation") if isinstance(right_panel, dict) else None,
        ]
        for explanation in candidates:
            canonical = _canonical_fit_explanation(
                {"last_product_explanation": explanation},
                target_sku,
            )
            if canonical is not None:
                return canonical
    return None


@router.get("/why_product")
def explain_why_product(
    request: Request,
    uid: str,
    sku: str,
    query: str | None = None,
    trace_id: str | None = None,
    redis=Depends(get_redis),
    role: str = Depends(
        require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])
    ),
    db=Depends(get_db),
) -> Dict[str, Any]:
    del role
    target_sku = str(sku or "").strip()
    if not target_sku:
        raise HTTPException(status_code=400, detail="sku required")

    tenant_id = str(
        request.headers.get("X-Tenant-Id")
        or request.headers.get("x-tenant-id")
        or "default"
    ).strip()
    canonical = _canonical_fit_explanation_from_trace(trace_id, target_sku)
    if canonical is not None:
        decision_trace_id = str(trace_id or _current_trace_id() or uuid.uuid4())
        return {
            "decision_trace_id": decision_trace_id,
            "trace_id": decision_trace_id,
            "explanation": canonical,
        }

    scoped_memory = Memory(redis, tenant_id=tenant_id)
    structured_state = scoped_memory.get_structured_state(uid) or {}
    canonical = _canonical_fit_explanation(structured_state, target_sku)
    if canonical is not None:
        decision_trace_id = str(trace_id or _current_trace_id() or uuid.uuid4())
        return {
            "decision_trace_id": decision_trace_id,
            "trace_id": decision_trace_id,
            "explanation": canonical,
        }

    state = scoped_memory.get_kv(uid) or {}
    snapshot = (
        state.get("last_constraints_snapshot")
        if isinstance(state.get("last_constraints_snapshot"), dict)
        else {}
    )
    preferences = (
        state.get("prefs_meta")
        if isinstance(state.get("prefs_meta"), dict)
        else {}
    )
    constraints: Dict[str, Any] = {
        "budget_min": snapshot.get("budget_min"),
        "budget_max": snapshot.get("budget_max"),
        "brands": list(snapshot.get("brands") or []),
        "specs": list(snapshot.get("specs") or []),
        "use_case": None,
    }
    for key in ("budget_min", "budget_max", "brands", "specs", "use_case"):
        preference = (
            preferences.get(key)
            if isinstance(preferences.get(key), dict)
            else None
        )
        if preference and preference.get("value") is not None:
            constraints[key] = preference["value"]
    if not isinstance(constraints.get("brands"), list):
        constraints["brands"] = []
    if not isinstance(constraints.get("specs"), list):
        constraints["specs"] = []

    effective_query = str(
        query or state.get("last_query") or "explain this selected product"
    ).strip()
    service = RecommendationService(redis)
    candidates = service.retrieve_candidates(effective_query, limit=60)
    ranked = service.rerank_candidates_with_factors(
        candidates, {**constraints, "query": effective_query}
    )
    row = next(
        (
            item
            for item in ranked or []
            if str((item or {}).get("sku") or "") == target_sku
        ),
        None,
    )
    if not row:
        candidate = next(
            (
                item
                for item in candidates or []
                if str((item or {}).get("sku") or "") == target_sku
            ),
            None,
        )
        if candidate:
            row = {
                **candidate,
                "factors": {"positive": [], "negative": [], "checks": []},
            }
    if not row:
        variant = get_variant(db, target_sku, tenant_id=tenant_id)
        if variant:
            row = {
                "sku": variant.sku,
                "name": variant.title,
                "score": None,
                "confidence": None,
                "factors": {
                    "positive": [],
                    "negative": [],
                    "checks": ["catalog_record_verified"],
                },
                "_explanation_scope": "catalog_only",
            }
    if not row:
        raise HTTPException(status_code=404, detail="sku not found in tenant catalog")

    explanation = build_sku_explanation(
        row=row, constraints=constraints, query=effective_query
    )
    decision_trace_id = str(trace_id or _current_trace_id() or uuid.uuid4())
    flags = load_feature_flags(
        os.getenv("FEATURE_FLAGS_PATH") or get_settings().feature_flags_path
    )
    try:
        log_trace_event(
            trace_id=decision_trace_id,
            event_type="selection_explanation_generated",
            source_type="stage",
            source_id="recommendation_explanation",
            target_type="user",
            target_id=uid,
            payload={
                "sku": target_sku,
                "matched_constraints": explanation["matched_constraints"],
                "disqualifiers": explanation["disqualifiers"],
                "reason_summary": explanation["reason_summary"],
                **_trace_metadata(
                    policy_version=str(flags.get("POLICY_VERSION") or "v1")
                ),
            },
        )
    except Exception:
        pass
    return {
        "decision_trace_id": decision_trace_id,
        "trace_id": decision_trace_id,
        "explanation": explanation,
    }
