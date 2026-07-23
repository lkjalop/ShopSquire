"""Bounded response policy when a V2-only cohort cannot delegate to legacy."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def legacy_delegate_enabled() -> bool:
    return os.getenv("RECOMMEND_LEGACY_DELEGATE_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }


def v2_only_unavailable_response(
    *, status: str, reason: str, lane: Optional[str], trace_id: str,
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
    return {
        "assistant_message": message,
        "products": [],
        "ranked_products": [],
        "next_questions": [],
        "decision_trace_id": trace_id or None,
        "trace_id": trace_id or None,
        "execution_mode": "v2_unavailable",
        "execution_lane": lane,
        "delegation_reason": reason or status,
        "degraded": status in {"degraded", "error"},
        "action_executed": False,
    }
