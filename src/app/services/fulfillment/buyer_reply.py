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
    temporal = (case_state or {}).get("supplier_response_expectation") or {}
    quote_sent = "We've requested a quote from an approved supplier."
    if temporal.get("calendar_state") == "closed":
        quote_sent += (
            " Their response clock is paused outside their operating hours; "
            "we'll reassess after their next operating window."
        )
    elif temporal.get("calendar_state") == "unknown":
        quote_sent += " Their response timing is not yet verified, so no reply date is promised."
    else:
        quote_sent += " We'll share your options once they respond."
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
        "QUOTE_SENT": quote_sent,
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
                      trace_id: Optional[str] = None, force: bool = False,
                      party_ref: Optional[str] = None) -> Dict[str, Any]:
    """Bounded-autonomy buyer notification: generate the claim-safe status for the case's current state and
    send it over the transport seam (SANDBOX by default; SMTP at deploy). Gated by buyer_auto_reply_enabled
    unless ``force`` (an explicit operator trigger). Idempotent per (case, state) so a buyer isn't spammed
    on re-trigger. Returns {sent, reason, state, provider_ref}. Never raises."""
    if not (force or buyer_auto_reply_enabled()):
        return {"sent": False, "reason": "disabled"}
    if not to_email:
        return {"sent": False, "reason": "no_recipient"}
    if party_ref:
        try:
            from sqlalchemy import text
            bound = db.execute(
                text(
                    "SELECT 1 FROM party_external_identity "
                    "WHERE tenant_id=:tenant AND party_id=:party "
                    "AND authority!='legacy_unverified' LIMIT 1"
                ),
                {"tenant": tenant_id, "party": party_ref},
            ).fetchone()
        except Exception:
            bound = None
        if not bound:
            return {"sent": False, "reason": "buyer_party_binding_unverified"}
    elif str(os.getenv("APP_ENV") or "").strip().lower() in {
        "prod", "production", "staging",
    }:
        return {"sent": False, "reason": "buyer_party_binding_required"}
    try:
        from src.app.services.fulfillment import workflow
        cur = workflow.repository.current_version(db, case_id, tenant_id)
        if cur is None:
            return {"sent": False, "reason": "no_case"}
        msg = buyer_status_message(cur.state, cur.state_json)
        if not msg:
            return {"sent": False, "reason": "no_message", "state": cur.state}
        observation_id = None
        grounding_ref = None
        message_key = f"buyer-status:{case_id}:{cur.state}"
        try:
            from src.app.services.communication_lifecycle import (
                append_transition,
                register_approved_grounding,
            )
            from src.app.services.communication_observations import record_message_observation
            grounding_ref = register_approved_grounding(
                db, tenant_id=tenant_id, grounding_type="template",
                source_ref=f"buyer_status:{cur.state}", source_version="v1",
                content=msg, approved_by="system:versioned_template_registry",
            )
            observation = record_message_observation(
                db=db, tenant_id=tenant_id, party_type="buyer", direction="outbound",
                channel="buyer_status", provider_message_id=message_key,
                purpose="procurement_status", consent_status="granted",
                security_status="accepted",
                sanitized_payload={
                    "recipient": str(to_email), "subject": "Update on your bulk order",
                    "body": msg,
                    "material_claims": [{"text": msg, "grounding_ref": grounding_ref}],
                },
                case_ref=case_id,
                party_ref=party_ref,
            )
            observation_id = str(observation["id"])
            append_transition(
                db, tenant_id=tenant_id, observation_id=observation_id,
                state="approved", idempotency_key=f"{message_key}:approved",
                actor_type="system", actor_id="versioned_template_registry",
                grounding_refs=[grounding_ref],
            )
            append_transition(
                db, tenant_id=tenant_id, observation_id=observation_id,
                state="queued", idempotency_key=f"{message_key}:queued",
                actor_type="operator" if force else "bounded_agent",
                actor_id="buyer_status_notifier", grounding_refs=[grounding_ref],
            )
        except Exception as exc:
            logger.warning("buyer communication grounding failed for %s: %s", case_id, exc)
            if str(os.getenv("APP_ENV") or "").strip().lower() in {"prod", "production", "staging"}:
                return {"sent": False, "reason": "communication_grounding_required", "state": cur.state}
        from src.app.services.fulfillment.transport import get_transport
        tx = transport or get_transport()
        sent = tx.send(to=str(to_email), subject="Update on your bulk order", body=msg,
                       idempotency_key=message_key)
        ok = getattr(sent, "status", "failed") == "sent"
        if observation_id:
            try:
                append_transition(
                    db, tenant_id=tenant_id, observation_id=observation_id,
                    state="delivered" if ok else "failed",
                    idempotency_key=f"{message_key}:{'delivered' if ok else 'failed'}",
                    actor_type="transport", actor_id="buyer_status_transport",
                    grounding_refs=[grounding_ref] if grounding_ref else [],
                    reason=str(getattr(sent, "detail", "") or ""),
                )
            except Exception as exc:
                logger.warning("buyer delivery projection failed for %s: %s", case_id, exc)
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
