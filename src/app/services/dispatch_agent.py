"""Dispatch_Agent (agnostic CORE) — governed buyer-facing dispatch in the procurement mold.

P0-C wired paid→dispatch, but BLINDLY: fixed carrier, no cost/SLA reasoning, no human gate. This
agent gives dispatch the same bounded-autonomy treatment as supplier RFQs:

  propose → (auto-execute under the threshold | HOLD for human approval above it) → execute

* carrier + service level come from the shipping-provider readiness ladder and the active
  profile's ``delivery_policy`` (fees/thresholds are profile DATA; the decision MECHANISM here);
* every proposal/execution appends to the payment ledger and the decision log (auditable);
* high-value orders (DISPATCH_APPROVAL_THRESHOLD_CENTS, default $2,000) require a human owner
  to approve before anything is queued — the same human-only invariant as GATE 2.

Vertical-blind: order ids / cents / carrier labels only. Best-effort side effects; never raises
into the webhook path.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.dispatch_agent")

DEFAULT_APPROVAL_THRESHOLD_CENTS = 200_000  # $2,000 — above this, a human approves dispatch


def _approval_threshold_cents() -> int:
    try:
        v = int(os.getenv("DISPATCH_APPROVAL_THRESHOLD_CENTS", str(DEFAULT_APPROVAL_THRESHOLD_CENTS)))
        return v if v >= 0 else DEFAULT_APPROVAL_THRESHOLD_CENTS
    except (TypeError, ValueError):
        return DEFAULT_APPROVAL_THRESHOLD_CENTS


def _delivery_policy() -> Dict[str, Any]:
    try:
        from src.app.platform.store_profile import profile_slot
        raw = profile_slot("delivery_policy", default={}) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _pick_carrier() -> Dict[str, Any]:
    """Ready real provider first (ANZ-first ladder in shipping_providers), else the sandbox
    transport — honestly labelled, never a fabricated integration."""
    try:
        from src.app.services.shipping_providers import get_default_shipping_provider, shipping_readiness
        ready = shipping_readiness()
        if ready.get("ready"):
            prov = get_default_shipping_provider()
            name = str(getattr(prov, "name", "") or ready.get("provider") or "").strip()
            if name:
                return {"carrier": name, "channel": "api", "real": True}
    except Exception:
        pass
    return {"carrier": os.getenv("DISPATCH_DEFAULT_CARRIER", "sandbox"), "channel": "sandbox", "real": False}


def propose_dispatch(*, order_id: str, total_cents: int) -> Dict[str, Any]:
    """Pure-ish proposal: carrier + service level + fee from profile policy, approval verdict from
    the threshold. No side effects."""
    policy = _delivery_policy()
    carrier = _pick_carrier()
    free_threshold = int(policy.get("free_shipping_threshold_cents") or 0)
    base_fee = int(policy.get("base_fee_cents") or 0)
    fee_cents = 0 if (free_threshold and total_cents >= free_threshold) else base_fee
    service_level = "standard"
    requires_approval = int(total_cents or 0) >= _approval_threshold_cents()
    return {
        "order_id": str(order_id),
        "carrier": carrier["carrier"],
        "channel": carrier["channel"],
        "real_integration": carrier["real"],
        "service_level": service_level,
        "shipping_fee_cents": fee_cents,
        "requires_approval": requires_approval,
        "approval_threshold_cents": _approval_threshold_cents(),
        "reason": ("order total meets the human-approval threshold" if requires_approval
                   else "under threshold — bounded auto-dispatch"),
    }


def log_dispatch_decision(proposal: Dict[str, Any], *, status: str, actor: str = "system") -> None:
    # Deliberately a TRACE event, not log_decision: the full decision-log pipeline runs the
    # verifier cascade (fact-verifier, review routing → tickets/escalations) — measured 21.9s on
    # a dispatch approval and it spammed ticketing for a legitimate human action. The ledger rows
    # + this trace event are the audit record; the heavy verifiers stay for LLM-proposed actions.
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(
            trace_id=f"dispatch-{proposal.get('order_id')}",
            event_type="dispatch_decision",
            source_type="agent",
            source_id="Dispatch_Agent",
            target_type="order",
            target_id=str(proposal.get("order_id") or ""),
            payload={"status": status, "actor": actor, "carrier": proposal.get("carrier"),
                     "service_level": proposal.get("service_level"),
                     "requires_approval": proposal.get("requires_approval"),
                     "shipping_fee_cents": proposal.get("shipping_fee_cents"),
                     "reason": proposal.get("reason")},
        )
    except Exception as exc:
        logger.debug("dispatch decision trace failed for %s: %s", proposal.get("order_id"), exc)


def execute_dispatch(db, *, order_id: str, intent_id: Optional[str], proposal: Dict[str, Any],
                     actor: str = "system") -> Dict[str, Any]:
    """Assign the tracking ref, queue the dispatch through the durable outbound queue, append the
    ledger event, log the decision. Idempotent per order (queue key + tracking only when absent)."""
    row = db.execute(text("SELECT tracking_number FROM orders WHERE id = :oid LIMIT 1"),
                     {"oid": order_id}).fetchone()
    if row is None:
        return {"dispatched": False, "reason": "order_not_found"}
    tracking = str(row[0] or "") or f"TRK-{secrets.token_hex(6).upper()}"
    carrier = str(proposal.get("carrier") or "sandbox")
    if not row[0]:
        db.execute(text("UPDATE orders SET tracking_number = :tn, carrier = :c, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = :oid"),
                   {"tn": tracking, "c": carrier, "oid": order_id})
    from src.app.services.fulfillment.outbound_queue import enqueue
    enqueue(
        db,
        case_id=f"order:{order_id}",
        recipient=f"dispatch:{carrier}",
        subject=f"Dispatch order {order_id}",
        body=json.dumps({"order_id": order_id, "tracking_number": tracking, "carrier": carrier,
                         "service_level": proposal.get("service_level"),
                         "shipping_fee_cents": proposal.get("shipping_fee_cents")}),
        idempotency_key=f"dispatch:{order_id}",
        transition_event="shipment_plan_created",
        actor_type="agent" if actor == "system" else "human",
        actor_id="Dispatch_Agent" if actor == "system" else actor,
    )
    try:
        from src.app.services.payment_ledger import KIND_DISPATCH_QUEUED, record_txn
        record_txn(db, order_id=order_id, kind=KIND_DISPATCH_QUEUED, intent_id=intent_id,
                   provider=carrier, actor_type="agent" if actor == "system" else "role",
                   actor_id="Dispatch_Agent" if actor == "system" else actor,
                   reason=f"tracking={tracking};service={proposal.get('service_level')}")
    except Exception as exc:
        logger.warning("dispatch ledger write failed for %s: %s", order_id, exc)
    # NOTE: the dispatch_decision trace event is written by the CALLER after db.commit() —
    # writing it here (second connection, same-process open transaction) self-deadlocked on
    # SQLite's lock for the full 30s busy timeout, measured live.
    return {"dispatched": True, "tracking_number": tracking, "carrier": carrier}


def dispatch_for_paid_order(db, *, order_id: str, intent_id: Optional[str],
                            total_cents: int) -> Dict[str, Any]:
    """The paid-order entry point: propose, then auto-execute under the threshold or HOLD above
    it (ledger 'dispatch_pending_approval' + decision-log 'pending' — the human approves via the
    payments router). Returns the proposal + outcome."""
    proposal = propose_dispatch(order_id=order_id, total_cents=total_cents)
    if proposal["requires_approval"]:
        try:
            from src.app.services.payment_ledger import record_txn
            record_txn(db, order_id=order_id, kind="dispatch_pending_approval", intent_id=intent_id,
                       provider=proposal["carrier"], actor_type="agent", actor_id="Dispatch_Agent",
                       reason=proposal["reason"])
        except Exception as exc:
            logger.warning("dispatch hold ledger write failed for %s: %s", order_id, exc)
        logger.info("dispatch HELD for human approval: order %s (total %s cents)", order_id, total_cents)
        return {**proposal, "outcome": "held_for_approval"}
    out = execute_dispatch(db, order_id=order_id, intent_id=intent_id, proposal=proposal)
    return {**proposal, "outcome": "auto_dispatched", **out}


def pending_dispatch(db, order_id: str) -> Optional[Dict[str, Any]]:
    """The open hold for an order (a dispatch_pending_approval with no later dispatch_queued)."""
    try:
        from src.app.services.payment_ledger import ledger_for_order
        events = ledger_for_order(db, order_id)
    except Exception:
        return None
    held = [e for e in events if e.get("kind") == "dispatch_pending_approval"]
    done = [e for e in events if e.get("kind") == "dispatch_queued"]
    return held[-1] if held and not done else None
