"""Buyer-facing bulk-order status reply (agnostic CORE) — bounded autonomy.

Unlike the supplier RFQ (which is human-gated before send), a STATUS update to the buyer is safe to generate
+ surface autonomously: it makes no commitment — no price, no delivery promise, no purchase order. This
maps the procurement case state to a claim-safe buyer message so the buyer always knows where their bulk
request stands as it progresses (received → sourcing → options → done), or what to do if it can't be met.

Vertical-blind: opaque qty/state only; no product vocabulary. Never raises.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Phrases that would be a commitment/claim a status update must never contain (defense-in-depth check).
_FORBIDDEN = ("$", "€", "£", "guarantee", "guaranteed", "we promise", "purchase order", "confirmed order")


def _qty(case_state: Optional[Dict[str, Any]]) -> Optional[int]:
    av = (case_state or {}).get("availability") if isinstance(case_state, dict) else None
    try:
        return int((av or {}).get("requested_qty")) if av and (av or {}).get("requested_qty") is not None else None
    except (TypeError, ValueError):
        return None


def buyer_status_message(state: Optional[str], case_state: Optional[Dict[str, Any]] = None) -> str:
    """A claim-safe, commitment-free buyer status line for the case's current state. Empty for unknown."""
    s = str(state or "").upper()
    n = _qty(case_state)
    qtxt = f"{n} units" if n else "your bulk request"
    msgs = {
        "AWAITING_BUYER_COMMITMENT": (
            f"We found a shortfall for {qtxt}. Confirm sourcing to proceed — no supplier is contacted and "
            "nothing is ordered until you confirm."),
        "COMMITTED": (
            "Thanks for confirming. We're preparing to source the shortfall — no order has been placed yet."),
        "QUOTE_DRAFTED": (
            "Your sourcing request is with our team for review before we contact an approved supplier."),
        "AWAITING_APPROVAL": (
            "Your sourcing request is awaiting a final internal check before we reach out to a supplier."),
        "AWAITING_SUPPLIER_INFO": (
            "We've asked the supplier a clarifying question and are waiting on their reply."),
        "QUOTE_SENT": (
            "We've requested a quote from an approved supplier. We'll share your options once they respond."),
        "QUOTE_RECEIVED": ("A supplier has responded — we're reviewing their reply now."),
        "QUOTE_VALIDATED": ("We've validated the supplier's response and are preparing your options."),
        "OPTIONS_READY": ("Your fulfilment options are ready — please review and choose how to proceed."),
        "SELECTED": ("Your choice is recorded; it now goes through a final approval step."),
        "COMPLETED": ("Your bulk request is complete."),
        "NO_APPROVED_SUPPLIER": (
            "We don't have an approved supplier for this exact item yet — see the alternatives below "
            "(a comparable item, or taking the units we have in stock now)."),
        "BUYER_DECLINED": ("This request has been closed. Start a new one any time."),
    }
    msg = msgs.get(s, "")
    # defense-in-depth: a status update must never carry a commitment/price (it would be unbounded).
    if msg and any(tok in msg.lower() for tok in _FORBIDDEN):
        return ""
    return msg
