"""Typed IMAGE fallback outcomes. Never creates an independent recommendation slate."""
from __future__ import annotations

from typing import Any, Dict


def image_fallback(*, analysis_state: str, reason: str = "") -> Dict[str, Any]:
    state = str(analysis_state or "pending").lower()
    if state == "degraded":
        status, message = "degraded", "Image analysis was limited. Add a model name or clearer image."
    elif state == "complete":
        status, message = "clarify", "I could not identify the product reliably. Add its model name."
    else:
        status, message = "pending", "Image analysis is still pending."
    return {
        "status": status, "reason": str(reason or "")[:160], "products": [],
        "canonical_slate": True, "action_executed": False, "message": message,
    }
