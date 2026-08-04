"""Gate-3 change-order / cancellation (agnostic CORE) — the irreversibility boundary.

Once a PO is committed to the supplier (PROCUREMENT_IN_PROGRESS / PARTIALLY_READY / READY_TO_SHIP), a buyer
mind-change is NOT a supersede. It is a CHANGE ORDER or CANCELLATION: the economics are surfaced (restock +
supplier penalty over the already-committed cost), the original order is preserved bitemporally, a new intent
is linked as a separate PR (`derived_from`), and a HUMAN authorises any money movement. The agent may PROPOSE
(records the request + economics); only a human EXECUTES the cancellation. Refund/restock execution is stubbed
behind FULFILLMENT_REFUND_ENABLED (default OFF) — no external money moves until payment/ERP secrets land.

Vertical-blind: cents + opaque ids/labels + states. Best-effort; never raises into a caller. See
docs/SHOPSQUIRE_PROCUREMENT_REQUEST_IDENTITY_AND_IRREVERSIBILITY_2026-06-30.md.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from src.app.services.fulfillment import workflow
from src.app.services.fulfillment.domain import Actor

logger = logging.getLogger("shopsquire.change_order")

# kinds of post-commitment change (opaque governance labels, not product vocab)
KIND_CANCEL = "cancel"
KIND_AMEND = "amend"
KIND_NEW_LINKED = "new_linked"


def _refund_enabled() -> bool:
    return str(os.getenv("FULFILLMENT_REFUND_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _profile(slot: str, default: Any) -> Any:
    try:
        from src.app.platform.store_profile import profile_slot
        v = profile_slot(slot, default=None)
        return v if v is not None else default
    except Exception:
        return default


def assess_cancellation(*, committed_cost_cents: Any, restock_fee_pct: Optional[float] = None,
                        supplier_penalty_cents: Optional[int] = None,
                        refundable_to_buyer_cents: Any = 0) -> Dict[str, Any]:
    """Pure economics of cancelling a committed order — what the HUMAN sees before authorising. The business
    eats restock + supplier penalty on the already-committed cost; the buyer's refundable amount is recorded
    separately. Fees default from the StoreProfile (agnostic policy DATA). Always requires_human."""
    try:
        committed = max(0, int(committed_cost_cents or 0))
    except (TypeError, ValueError):
        committed = 0
    pct = restock_fee_pct if restock_fee_pct is not None else _profile("cancellation_restock_fee_pct", 0.15)
    try:
        pct = max(0.0, float(pct))
    except (TypeError, ValueError):
        pct = 0.0
    penalty = supplier_penalty_cents if supplier_penalty_cents is not None else _profile("supplier_cancellation_penalty_cents", 0)
    try:
        penalty = max(0, int(penalty))
    except (TypeError, ValueError):
        penalty = 0
    restock = int(round(committed * pct))
    try:
        refundable = max(0, int(refundable_to_buyer_cents or 0))
    except (TypeError, ValueError):
        refundable = 0
    return {"committed_cost_cents": committed, "restock_fee_pct": round(pct, 4), "restock_fee_cents": restock,
            "supplier_penalty_cents": penalty, "net_cancellation_cost_cents": restock + penalty,
            "refundable_to_buyer_cents": refundable, "requires_human": True}


def assess_for_case(db, case_id: str, *, refundable_to_buyer_cents: Any = 0) -> Dict[str, Any]:
    """Convenience: the already-committed SUPPLIER cost is the PO's total amount (what we owe the supplier) —
    read it off the case's purchase_order, falling back to economics' supplier_cost_cents. Then assess."""
    committed = 0
    try:
        cur = workflow.repository.current_version(db, case_id)
        sj = cur.state_json if cur and isinstance(cur.state_json, dict) else {}
        committed = int((sj.get("purchase_order") or {}).get("total_amount_cents") or 0)
    except Exception as exc:
        logger.debug("assess_for_case PO read failed for %s: %s", case_id, exc)
    if committed <= 0:
        try:
            from src.app.services.fulfillment import economics as feco
            committed = int((feco.from_case(db, case_id) or {}).get("supplier_cost_cents") or 0)
        except Exception as exc:
            logger.debug("assess_for_case economics unavailable for %s: %s", case_id, exc)
    return assess_cancellation(committed_cost_cents=committed, refundable_to_buyer_cents=refundable_to_buyer_cents)


def propose_change(db, *, case_id: str, actor: Actor, kind: str = KIND_CANCEL, reason: str = "buyer_change",
                   assessment: Optional[Dict[str, Any]] = None, derived_pr_id: Optional[str] = None,
                   tenant_id: str = "default", trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """RECORD a post-commitment change request (Gate-3 proposal). Fires the self-loop ``change_requested`` — no
    state change, no money moves — so the request + its economics are on the bitemporal record and a human can
    act. Agent/buyer/system/operator may propose. ``derived_pr_id`` links the new intent as a separate PR."""
    if assessment is None:
        assessment = assess_for_case(db, case_id)
    return workflow.transition(
        db, case_id=case_id, event="change_requested", actor=actor, reason_code=reason,
        evidence={"kind": kind, "assessment": assessment, "derived_from_pr": derived_pr_id, "proposed_by": actor.type.value},
        state_patch={"change_request": {"kind": kind, "reason": reason, "assessment": assessment,
                                        "derived_pr_id": derived_pr_id, "status": "proposed",
                                        "requires_human": True}},
        tenant_id=tenant_id, trace_id=trace_id)


def authorize_cancellation(db, *, case_id: str, actor: Actor, assessment: Optional[Dict[str, Any]] = None,
                           reason: str = "operator_authorised_cancellation", tenant_id: str = "default",
                           trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """HUMAN authorises the cancellation of a committed order → CANCELLED. The domain guard makes this
    HUMAN_OPERATOR-only (an agent CANNOT fire it). The original order is preserved bitemporally; the economics
    are recorded. Refund/restock EXECUTION is stubbed behind FULFILLMENT_REFUND_ENABLED — until it's on (with
    payment/ERP secrets) we record the intent + amounts but move NO money."""
    if assessment is None:
        assessment = assess_for_case(db, case_id)
    refund_executed = False
    refund_note = "refund_disabled"
    if _refund_enabled():
        # Placeholder for the real payment-refund / ERP-restock call (gated on secrets). Intentionally NOT
        # wired to an external service here; flipping the flag without the integration still moves no money.
        refund_note = "refund_enabled_no_integration"
    return workflow.transition(
        db, case_id=case_id, event="order_cancelled", actor=actor, reason_code=reason,
        evidence={"assessment": assessment, "refund_executed": refund_executed, "refund_note": refund_note},
        state_patch={"cancellation": {"assessment": assessment, "refund_executed": refund_executed,
                                      "refund_note": refund_note, "authorised_by": actor.type.value,
                                      "net_cost_cents": assessment.get("net_cancellation_cost_cents")}},
        tenant_id=tenant_id, trace_id=trace_id)
