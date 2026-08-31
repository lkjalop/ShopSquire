"""Bounded response policy when a V2-only cohort cannot delegate to legacy."""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Optional

from src.app.services.research_control_loop import ControlReceipt, ExecutionStateEnvelope


def compatibility_cutover_enabled() -> bool:
    """Whether chat may retry through the V2-only compatibility transport."""
    configured = os.getenv("RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED")
    if configured is None:
        # Transitional configuration alias; it no longer enables legacy code.
        configured = os.getenv("RECOMMEND_LEGACY_DELEGATE_ENABLED", "1")
    return configured.strip().lower() in {
        "1", "true", "yes", "on",
    }


def v2_only_unavailable_response(
    *,
    status: str,
    reason: str,
    lane: Optional[str],
    trace_id: str,
    query: str = "",
    external_research_authorized: bool = False,
) -> Dict[str, Any]:
    """Return an honest no-action response; never fabricate products or execution."""
    if status == "degraded":
        message = (
            "I could not verify a recommendation from the catalog on this turn. "
            "Nothing was changed or submitted; please retry."
        )
    elif lane:
        message = (
            f"This pilot does not yet serve the {lane.lower().replace('_', ' ')} workflow. "
            "Nothing was changed or submitted."
        )
    else:
        message = (
            "This pilot could not safely complete that request. "
            "Nothing was changed or submitted."
        )
    normalized_reason = str(reason or status or "recommendation_unavailable").strip()
    lowered_reason = normalized_reason.lower()
    model_status = (
        "timeout"
        if "timeout" in lowered_reason or "deadline" in lowered_reason
        else "failed"
    )
    case_ref = str(trace_id or "unavailable-turn")[:200]
    control = ExecutionStateEnvelope(
        case_id=case_ref,
        case_revision=1,
        buyer_text_hash=hashlib.sha256(str(query or "").encode("utf-8")).hexdigest(),
        model_status=model_status,
        material_concept_status="unresolved",
        research_authority=(
            "granted" if external_research_authorized else "required"
        ),
        provider_status="not_attempted",
        evidence_status="none",
        requirement_status="blocked",
        catalog_authority="blocked",
        presentation_status="clarification_only",
        commerce_authority="none",
        receipts=(
            ControlReceipt(
                sequence=1,
                component="model",
                status=model_status,
                authority="proposes",
                reason="Recommendation interpretation did not complete within the governed turn.",
            ),
            ControlReceipt(
                sequence=2,
                component="checker",
                status="blocked",
                authority="authorizes",
                reason="No completed interpretation or accepted requirements authorize catalog fit.",
            ),
            ControlReceipt(
                sequence=3,
                component="presentation",
                status="clarification_only",
                authority="presents",
                reason="The turn fails closed without products or commerce authority.",
            ),
        ),
    )
    return {
        "assistant_message": message,
        "products": [],
        "ranked_products": [],
        "next_questions": [],
        "decision_trace_id": trace_id or None,
        "trace_id": trace_id or None,
        "execution_mode": "v2_unavailable",
        "execution_lane": lane,
        "delegation_reason": normalized_reason,
        "degraded": status in {"degraded", "error"},
        "action_executed": False,
        "semantic_resolution": {
            "outcome": "unresolved",
            "catalog_authority": "blocked",
            "reason": "recommendation_core_unavailable",
        },
        "workload_authorization": {
            "status": "blocked",
            "reason": "recommendation_core_unavailable",
            "state_prevented": [
                "catalog_qualification",
                "buyer_commitment",
                "supplier_rfq",
            ],
        },
        "execution_state_envelope": control.model_dump(mode="json"),
    }
