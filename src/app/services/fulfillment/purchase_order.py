"""Purchase-order proposal and dispatch through the durable fulfillment workflow.

A dispatch intent is committed before contacting the configured provider. A
confirmed provider receipt advances the case; ambiguous outcomes and process loss
leave the intent blocked for reconciliation. Sandbox is the default transport.

Legacy execute still combines role-based approval and dispatch. It does not yet
establish independent-person approval, and complete is not proof of delivery.
Do not enable real commerce on the strength of these workflow checks alone.
"""
from __future__ import annotations

import uuid
from datetime import datetime,timezone
from typing import Any, Dict, Optional

from src.app.services.fulfillment import workflow
from src.app.services.fulfillment.domain import Actor, ActorType
from src.app.services.fulfillment.po_transport import get_po_transport, HttpErpTransport


def propose(db, *, case_id: str, actor: Actor, tenant_id: str = "default",
            now_iso: Optional[str] = None, trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """AGENT proposes a PO from the selected option + validated quote (SELECTED → APPROVAL_REQUIRED)."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    st = cur.state_json if cur else {}
    selection = st.get("selection") or {}
    vq = st.get("validated_quote") or {}
    draft = st.get("draft") or {}
    # the PO procures only the SUPPLIER/substitute-sourced units — local stock isn't purchased.
    alloc = selection.get("allocation") or []
    supplier_units = sum(int(a.get("quantity") or 0) for a in alloc
                         if a.get("source") in ("supplier", "substitute"))
    units = supplier_units if alloc else int(vq.get("quoted_quantity") or 0)
    po = {
        "supplier_ref": draft.get("recipient_ref") or draft.get("recipient_domain"),
        "item_ref": (draft.get("commercial_scope") or {}).get("item_ref"),
        "option_type": selection.get("option_type"),
        "quantity": units,
        "unit_amount_cents": vq.get("unit_amount_cents"),      # wholesale — internal only
        "total_amount_cents": int((vq.get("unit_amount_cents") or 0) * int(units or 0)),
        "quote_expires_at": vq.get("quote_expires_at"),
        "status": "proposed",
    }
    return workflow.transition(db, case_id=case_id, event="purchase_order_proposed", actor=actor,
                               reason_code="po_drafted_from_selection",
                               evidence={"total_amount_cents": po["total_amount_cents"], "quantity": po["quantity"]},
                               state_patch={"purchase_order": po}, tenant_id=tenant_id, now_iso=now_iso,
                               trace_id=trace_id)


def execute(db, *, case_id: str, actor: Actor, idempotency_key: Optional[str] = None,
            today: Optional[str] = None, po_transport: Optional[Any] = None, tenant_id: str = "default",
            now_iso: Optional[str] = None, trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """Validate scope, commit dispatch intent, then require a provider receipt.

    Uncertain or failed attempts stay blocked for operator reconciliation.
    Authenticated distinct-person approval is still required for live commerce.
    """
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    po = (cur.state_json.get("purchase_order") if cur else None) or {}
    scope = (cur.state_json.get("draft", {}).get("commercial_scope") if cur else None) or {}
    if po.get('status') == 'dispatching':
        return workflow.TransitionResult(False,case_id,cur.state,'po_reconciliation_required',http_status=409)

    # guard: quote not expired
    expiry = po.get("quote_expires_at")
    day = today or (now_iso or datetime.now(timezone.utc).isoformat())[:10]
    if expiry and day and str(expiry) < str(day):
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "quote_expired", http_status=409)
    # guard: within approved scope (quantity not above what was approved)
    approved_qty = int(scope.get("quantity") or 0)
    if approved_qty and int(po.get("quantity") or 0) > approved_qty:
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "out_of_scope", http_status=409)

    tx = po_transport or get_po_transport()
    if isinstance(tx,HttpErpTransport):
        # This legacy command has no authenticated requester/approver grant.
        # Transport configuration and an operator role cannot supply one.
        return workflow.TransitionResult(False,case_id,cur.state if cur else None,
            'independent_po_approval_unavailable',http_status=403)

    key = idempotency_key or f"po-{case_id}"
    r1 = workflow.transition(db, case_id=case_id, event="purchase_order_approved", actor=actor,
                             reason_code="human_approved_po", idempotency_key=f"{key}-approve",
                             tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    if not r1.ok and r1.reason != "idempotent_replay":
        return r1
    # idempotent-replay guard BEFORE the transport call — a re-executed PO must NOT create a second ERP PO.
    already = workflow.repository.find_idempotent_version(db, case_id, "purchase_order_created",
                                                          f"{key}-create", tenant_id)
    if already:
        st = workflow.current_state(db, case_id, tenant_id)
        return workflow.TransitionResult(True, case_id, st.value if st else None, "idempotent_replay",
                                         version_id=already)

    dispatch=workflow.transition(db,case_id=case_id,event='purchase_order_dispatch_started',actor=actor,
        reason_code='durable_po_dispatch_intent',idempotency_key=f'{key}-dispatch',
        evidence={'provider_idempotency_key':f'{key}-create'},
        state_patch={'purchase_order':{**po,'status':'dispatching'}},tenant_id=tenant_id,now_iso=now_iso,trace_id=trace_id)
    if not dispatch.ok or dispatch.reason=='idempotent_replay':
        return workflow.TransitionResult(False,case_id,cur.state,'po_reconciliation_required',http_status=409)
    made = tx.create(supplier_ref=str(po.get("supplier_ref") or ""), item_ref=str(po.get("item_ref") or ""),
                     quantity=po.get("quantity"), unit_amount_cents=po.get("unit_amount_cents"),
                     total_amount_cents=po.get("total_amount_cents"), idempotency_key=f"{key}-create")
    if getattr(made, "status", "failed") != "created":
        # A missing confirmation is not proof that the provider performed no effect.
        return workflow.TransitionResult(False, case_id, workflow.current_state(db, case_id, tenant_id).value
                                         if workflow.current_state(db, case_id, tenant_id) else None,
                                         "po_create_failed" if made.status=='failed' else 'po_outcome_unknown', http_status=502)
    sandbox = getattr(made, "detail", "") == "sandbox"
    return workflow.transition(
        db, case_id=case_id, event="purchase_order_created", actor=actor,
        reason_code="po_created_sandbox" if sandbox else "po_created_erp",
        idempotency_key=f"{key}-create",
        evidence={"po_ref": made.po_ref, "sandbox": sandbox, "transport": getattr(made, "detail", "")},
        state_patch={"purchase_order": {**po, "status": "created", "po_ref": made.po_ref, "sandbox": sandbox,
                                        "transport": getattr(made, "detail", "")}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


def complete(db, *, case_id: str, actor: Optional[Actor] = None, tenant_id: str = "default",
             now_iso: Optional[str] = None, trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """Mark the order COMPLETED (READY_TO_SHIP → COMPLETED)."""
    return workflow.transition(db, case_id=case_id, event="completed",
                               actor=actor or Actor(ActorType.SYSTEM, "fulfilment"),
                               reason_code="order_completed", tenant_id=tenant_id, now_iso=now_iso,
                               trace_id=trace_id)
