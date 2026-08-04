"""Support clarification and handoff advice; never files a complaint."""
from __future__ import annotations

from typing import Any, Dict


def prepare_support_handoff(query: str, *, tenant_id: str) -> Dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "topic": str(query or "")[:160],
        "needs_human_review": True,
        "claim_status": "pending_handoff",
        "case_id": None,
        "action_executed": False,
        "message": (
            "I'll pass this to a human to review - nothing is filed automatically yet. "
            "You'll be contacted with next steps."
        ),
    }
