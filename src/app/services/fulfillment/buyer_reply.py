"""Buyer-facing bulk-order status reply (agnostic CORE) — bounded autonomy.

Unlike the supplier RFQ (which is human-gated before send), a STATUS update to the buyer is safe to generate
+ surface autonomously: it makes no commitment — no price, no delivery promise, no purchase order. This
maps the procurement case state to a claim-safe buyer message so the buyer always knows where their bulk
request stands as it progresses (received → sourcing → options → done), or what to do if it can't be met.

Vertical-blind: opaque qty/state only; no product vocabulary. Never raises.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("shopsquire.buyer_reply")

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


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return v is not None and str(v).strip().lower() in ("1", "true", "yes", "on")


def buyer_auto_reply_enabled() -> bool:
    """Bounded autonomy: auto-send the buyer status (env OR feature_flags.json). Default OFF. Safe to
    enable WITHOUT human approval because the message is claim-safe (no price/commitment)."""
    if os.getenv("FULFILLMENT_BUYER_AUTO_REPLY") is not None:
        return _truthy(os.getenv("FULFILLMENT_BUYER_AUTO_REPLY"))
    try:
        import json as _json
        from src.app.config import get_settings
        with open(get_settings().feature_flags_path, "r", encoding="utf-8") as f:
            return _truthy(_json.load(f).get("FULFILLMENT_BUYER_AUTO_REPLY"))
    except Exception:
        return False


def send_buyer_status(db, case_id: str, *, to_email: Optional[str], transport: Any = None,
                      tenant_id: str = "default", now_iso: Optional[str] = None,
                      trace_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Bounded-autonomy buyer notification: generate the claim-safe status for the case's current state and
    send it over the transport seam (SANDBOX by default; SMTP at deploy). Gated by buyer_auto_reply_enabled
    unless ``force`` (an explicit operator trigger). Idempotent per (case, state) so a buyer isn't spammed
    on re-trigger. Returns {sent, reason, state, provider_ref}. Never raises."""
    if not (force or buyer_auto_reply_enabled()):
        return {"sent": False, "reason": "disabled"}
    if not to_email:
        return {"sent": False, "reason": "no_recipient"}
    try:
        from src.app.services.fulfillment import workflow
        cur = workflow.repository.current_version(db, case_id, tenant_id)
        if cur is None:
            return {"sent": False, "reason": "no_case"}
        msg = buyer_status_message(cur.state, cur.state_json)
        if not msg:
            return {"sent": False, "reason": "no_message", "state": cur.state}
        from src.app.services.fulfillment.transport import get_transport
        tx = transport or get_transport()
        sent = tx.send(to=str(to_email), subject="Update on your bulk order", body=msg,
                       idempotency_key=f"buyer-status:{case_id}:{cur.state}")
        ok = getattr(sent, "status", "failed") == "sent"
        try:  # auditable bounded-autonomy notification (off the silent-except ratchet via record_decision)
            from src.app.services.adaptive_action_gate import record_decision
            record_decision(db, action_type="buyer_status_notify",
                            decision="allow" if ok else "deny", reason=cur.state,
                            subject=case_id, target=str(to_email), tenant_id=tenant_id)
        except Exception as exc:
            logger.debug("buyer_status_notify audit failed for %s: %s", case_id, exc)
        return {"sent": ok, "reason": getattr(sent, "detail", ""), "state": cur.state,
                "provider_ref": getattr(sent, "provider_ref", None)}
    except Exception as exc:
        return {"sent": False, "reason": f"error:{str(exc)[:80]}"}
