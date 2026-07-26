"""Approved-policy answer projection with no policy execution authority."""
from __future__ import annotations

from typing import Any, Dict


def policy_answer(query: str, *, tenant_id: str) -> Dict[str, Any]:
    from src.app.services.answer_quality import policy_faq_answer

    approved = policy_faq_answer(query)
    return {
        "tenant_id": tenant_id,
        "topic": str(query or "")[:120],
        "answered": bool(approved),
        "source": "approved_store_profile",
        "message": approved or (
            "That policy detail is not in the store's approved answers yet. "
            "A teammate must confirm it; I won't invent the terms."
        ),
        "action_executed": False,
    }
