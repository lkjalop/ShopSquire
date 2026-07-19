"""V2 procurement advisory projection. No execution authority lives here."""
from __future__ import annotations

from typing import Any, Dict

from src.app.services.procurement_advice import sourcing_continuity


def build_procurement_advice(envelope: Any) -> Dict[str, Any]:
    session = envelope.session if isinstance(getattr(envelope, "session", None), dict) else {}
    return {
        "procurement_intent": True,
        "execution_authority": "fulfillment_cases",
        "external_send_gate": "human_approval",
        "continuity": sourcing_continuity(session.get("last_sourcing_intent")),
        "message": (
            "This looks like a bulk/procurement request. I can prepare sourcing advice and a supplier "
            "quote-request draft for review; nothing is sent without the existing fulfillment gates."
        ),
    }
