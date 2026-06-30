"""Cart-commitment materialization (agnostic CORE) — GATE 1 at the buyer's COMMITMENT, not on a query.

The recommend stage leaves the buyer's sourcing intent FLUID (a preview, no durable case) under
FULFILLMENT_DEFER_TO_CART. The single commitment boundary is the order/cart confirmation: when the buyer
CONFIRMS the order, the shortfall lines materialize into durable procurement cases — one per supplier group
— each waiting at GATE 1 (AWAITING_BUYER_COMMITMENT; no supplier is contacted).

Two safety properties this module owns:
  - IDEMPOTENCY: keyed on the order id (order_group_id = "order-<order_id>"). A double-submitted confirm
    returns the SAME cases instead of creating duplicates (the consumer-behavior "two POs" bug).
  - VERTICAL-BLIND: lines are opaque {item_ref, requested_qty, in_stock?}; shortfall is pure arithmetic;
    supplier routing/terms come from order_split (which reads the StoreProfile). No product vocabulary.

Read-only planning + case creation are delegated to order_split; this module is the commitment seam only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.services.fulfillment.order_split import (
    create_grouped_cases, emit_split_trace, plan_order_split, resolve_line_skus)

logger = logging.getLogger("shopsquire.cart_commitment")


def order_group_id_for(order_id: str) -> Optional[str]:
    """The deterministic order_group_id stamped onto every case materialized for this order — the
    idempotency key. None for a blank order id."""
    oid = str(order_id or "").strip()
    return f"order-{oid}" if oid else None


def count_amendments(db, order_id: str, tenant_id: str = "default") -> int:
    """How many times this order has been amended = the count of SUPERSEDED case versions under its group.
    The churn-brake signal (procurement_fraud_signals.assess_amendments). Best-effort; 0 on any error."""
    group_id = order_group_id_for(order_id)
    if db is None or not group_id:
        return 0
    try:
        from src.app.services.fulfillment.repository import ensure_tables
        ensure_tables(db)
        row = db.execute(text(
            "SELECT COUNT(DISTINCT case_id) FROM fulfillment_case_version "
            "WHERE tenant_id=:t AND state='SUPERSEDED' AND state_json LIKE :p"),
            {"t": str(tenant_id or "default"), "p": f'%"order_group_id"%{group_id}%'}).fetchone()
        return int((row or [0])[0] or 0)
    except Exception as exc:
        logger.debug("count_amendments failed for %s: %s", order_id, exc)
        return 0


def list_order_cases(db, order_id: str, tenant_id: str = "default") -> List[Dict[str, Any]]:
    """Every case under an order group — ACTIVE and SUPERSEDED — newest-first, with a draft summary. The
    'amendment history of this order' read model (#5): the operator sees each version that was sourced and,
    via draft_diff, what changed between drafts. Best-effort; [] on error."""
    group_id = order_group_id_for(order_id)
    if db is None or not group_id:
        return []
    try:
        from src.app.services.fulfillment.repository import ensure_tables
        ensure_tables(db)
        rows = db.execute(text(
            "SELECT case_id, state, state_json, valid_from FROM fulfillment_case_version "
            "WHERE tenant_id=:t AND valid_to IS NULL AND state_json LIKE :p ORDER BY valid_from DESC"),
            {"t": str(tenant_id or "default"), "p": f'%"order_group_id"%{group_id}%'}).fetchall()
    except Exception as exc:
        logger.debug("list_order_cases failed for %s: %s", order_id, exc)
        return []
    import json as _json
    out: List[Dict[str, Any]] = []
    for r in (rows or []):
        try:
            sj = r[2] if isinstance(r[2], dict) else _json.loads(r[2] or "{}")
        except Exception:
            sj = {}
        draft = sj.get("draft") or {}
        out.append({"case_id": r[0], "state": r[1], "valid_from": r[3],
                    "superseded": r[1] == "SUPERSEDED",
                    "draft": {"subject": draft.get("subject"), "recipient_domain": draft.get("recipient_domain"),
                              "content_hash": draft.get("content_hash")}})
    return out


def draft_diff(old_draft: Optional[Dict[str, Any]], new_draft: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What changed between two supplier drafts (amend-diff). Pure; opaque fields only — no product vocab."""
    old = old_draft if isinstance(old_draft, dict) else {}
    new = new_draft if isinstance(new_draft, dict) else {}
    fields: Dict[str, Any] = {}
    for k in ("recipient_domain", "recipient_email", "subject", "content_hash"):
        if str(old.get(k) or "") != str(new.get(k) or ""):
            fields[k] = {"from": old.get(k), "to": new.get(k)}
    body_changed = str(old.get("body") or "") != str(new.get("body") or "")
    return {"changed_fields": list(fields.keys()), "fields": fields, "body_changed": body_changed,
            "prior_content_hash": old.get("content_hash"), "new_content_hash": new.get("content_hash"),
            "changed": bool(fields) or body_changed}


def _already_materialized(db, order_group_id: str, tenant_id: str = "default") -> List[str]:
    """Idempotency probe: the case ids already materialized for this order's commitment, found by the
    order_group_id stamped into the case state_json. A re-confirm (double-submit) returns these instead of
    creating duplicates. Best-effort; [] on any error (the caller then proceeds to create)."""
    if db is None or not order_group_id:
        return []
    try:
        from src.app.services.fulfillment.domain import TERMINAL_STATES
        from src.app.services.fulfillment.repository import ensure_tables
        ensure_tables(db)
        # state_json is JSON TEXT; match the order_group_id value loosely so JSON separator spacing never
        # breaks the probe. Only the OPEN (valid_to IS NULL) and ACTIVE (non-terminal) version counts — so a
        # SUPERSEDED/declined case from a prior amendment does not block re-materialization of the new lines.
        terminal = [s.value for s in TERMINAL_STATES]
        placeholders = ", ".join(f":st{i}" for i in range(len(terminal)))
        params: Dict[str, Any] = {"t": str(tenant_id or "default"), "p": f'%"order_group_id"%{order_group_id}%'}
        params.update({f"st{i}": v for i, v in enumerate(terminal)})
        rows = db.execute(text(
            "SELECT DISTINCT case_id FROM fulfillment_case_version "
            f"WHERE tenant_id=:t AND valid_to IS NULL AND state_json LIKE :p AND state NOT IN ({placeholders})"),
            params).fetchall()
        return [str(r[0]) for r in (rows or []) if r and r[0]]
    except Exception as exc:
        logger.debug("_already_materialized probe failed for %s: %s", order_group_id, exc)
        return []


# Pre-send states from which a case may be auto-superseded (no supplier contacted yet). Past the send gate
# (QUOTE_SENT+), supersession is the operator-driven post-send protocol — never auto-fired here.
_SUPERSEDABLE_STATES = frozenset({"AVAILABILITY_ASSESSED", "AWAITING_BUYER_COMMITMENT", "COMMITTED",
                                  "QUOTE_DRAFTED", "AWAITING_APPROVAL"})


def supersede_order(db, *, order_id: str, lines: List[Dict[str, Any]], uid: Optional[str] = None,
                    uid_hash: Optional[str] = None, trace_id: Optional[str] = None,
                    tenant_id: str = "default", now_iso: Optional[str] = None,
                    requirements: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The buyer changed their mind AFTER confirming: supersede the active pre-send cases for this order and
    re-materialize from the new lines (same order_group_id; the probe ignores superseded cases). Cases past
    the send gate CANNOT be auto-superseded — that is the operator-driven post-send protocol — so if any
    active case is not in a pre-send state we STOP and report it instead of superseding around it. Returns
    {order_group_id, superseded:[case_id], operator_required:[{case_id,state}], created, status}."""
    from src.app.services.fulfillment import workflow as fwf
    from src.app.services.fulfillment.domain import Actor, ActorType
    from src.app.services.fulfillment.repository import current_version
    group_id = order_group_id_for(order_id)
    if not group_id or db is None:
        return {"order_group_id": group_id, "superseded": [], "operator_required": [], "created": None,
                "status": "noop"}

    active = _already_materialized(db, group_id, tenant_id=tenant_id)
    supersedable: List[str] = []
    operator_required: List[Dict[str, Any]] = []
    for cid in active:
        cur = current_version(db, cid, tenant_id)
        st = cur.state if cur else ""
        if st in _SUPERSEDABLE_STATES:
            supersedable.append(cid)
        else:
            operator_required.append({"case_id": cid, "state": st})
    if operator_required:
        # a supplier has likely been contacted for one of these — don't silently retire it
        return {"order_group_id": group_id, "superseded": [], "operator_required": operator_required,
                "created": None, "status": "operator_required"}

    # CARRY FORWARD requirements (deadline/use_case/ship_to): if the amend confirm did NOT restate them,
    # inherit from the superseded cases so the new RFQ keeps the CONCRETE deadline instead of regressing to
    # the vague "the stated deadline" placeholder (the live amend-path bug). Read before superseding.
    if not requirements:
        for cid in supersedable:
            cur = current_version(db, cid, tenant_id)
            _r = cur.state_json.get("requirements") if cur and isinstance(cur.state_json, dict) else None
            if isinstance(_r, dict) and _r:
                requirements = _r
                break

    actor = Actor(ActorType.BUYER, uid or "buyer")
    superseded: List[str] = []
    for cid in supersedable:
        res = fwf.transition(db, case_id=cid, event="case_superseded", actor=actor,
                             reason_code="buyer_amended_order", trace_id=trace_id, now_iso=now_iso)
        if getattr(res, "ok", False):
            superseded.append(cid)

    created = materialize_cases_for_order(db, order_id=order_id, lines=lines, uid=uid, uid_hash=uid_hash,
                                          trace_id=trace_id, tenant_id=tenant_id, now_iso=now_iso,
                                          requirements=requirements)
    return {"order_group_id": group_id, "superseded": superseded, "operator_required": [],
            "created": created, "status": "superseded"}


def operator_supersede_case(db, *, case_id: str, actor_id: str = "operator",
                            reason: str = "operator_amendment", trace_id: Optional[str] = None,
                            tenant_id: str = "default", now_iso: Optional[str] = None) -> Dict[str, Any]:
    """OPERATOR-driven supersession for a SINGLE case — including POST-SEND cases the buyer path can't touch
    (a supplier was already emailed). Records the void draft content_hash so any late quote correlated to it
    is quarantined (receive_reply), and flags cancellation_advised when a supplier was contacted (the
    operator then sends the cancellation via the normal external-comms path). Returns
    {ok, case_id, state, void_content_hash, cancellation_advised, reason}."""
    from src.app.services.fulfillment import workflow as fwf
    from src.app.services.fulfillment.domain import Actor, ActorType
    from src.app.services.fulfillment.repository import current_version
    if db is None or not case_id:
        return {"ok": False, "case_id": case_id, "reason": "not_found"}
    cur = current_version(db, case_id, tenant_id)
    if not cur:
        return {"ok": False, "case_id": case_id, "reason": "not_found"}
    state = cur.state
    void_hash = ((cur.state_json.get("draft") or {}).get("content_hash")
                 if isinstance(cur.state_json, dict) else None)
    cancellation_advised = state in ("QUOTE_SENT", "QUOTE_RECEIVED")
    res = fwf.transition(
        db, case_id=case_id, event="case_superseded", actor=Actor(ActorType.HUMAN_OPERATOR, actor_id),
        reason_code=reason, trace_id=trace_id, now_iso=now_iso,
        evidence={"void_content_hash": void_hash, "from_state": state},
        state_patch={"superseded": {"void_content_hash": void_hash, "reason": reason,
                                    "from_state": state, "cancellation_advised": cancellation_advised}})
    return {"ok": getattr(res, "ok", False), "case_id": case_id, "state": getattr(res, "state", None),
            "void_content_hash": void_hash, "cancellation_advised": cancellation_advised,
            "reason": getattr(res, "reason", None)}


def _line_signature(pairs) -> frozenset:
    """An order-independent signature of {item_ref → requested_qty} so a re-confirm can be told apart:
    identical lines = a double-submit (idempotent); different lines = a real AMENDMENT (the buyer changed
    their mind after committing) → supersession, not a silent no-op."""
    sig = set()
    for item_ref, qty in pairs:
        ir = str(item_ref or "").strip()
        if ir:
            sig.add((ir, int(qty or 0)))
    return frozenset(sig)


def _materialized_signature(db, case_ids: List[str], tenant_id: str = "default") -> frozenset:
    """The {item_ref → requested_qty} signature already on the materialized cases (read from each case's
    stored order_lines), so it can be compared against an incoming confirm."""
    from src.app.services.fulfillment.repository import current_version
    pairs = []
    for cid in case_ids:
        cur = current_version(db, cid, tenant_id)
        for ln in ((cur.state_json.get("order_lines") if cur and isinstance(cur.state_json, dict) else None) or []):
            if isinstance(ln, dict):
                pairs.append((ln.get("item_ref"), ln.get("quantity")))
    return _line_signature(pairs)


def materialize_cases_for_order(db, *, order_id: str, lines: List[Dict[str, Any]],
                                uid: Optional[str] = None, uid_hash: Optional[str] = None,
                                trace_id: Optional[str] = None, tenant_id: str = "default",
                                now_iso: Optional[str] = None,
                                requirements: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """GATE 1 at the COMMITMENT boundary: turn a confirmed order's shortfall lines into durable procurement
    cases (one per supplier group), idempotently keyed on the order id.

    ``lines`` are vertical-blind dicts {item_ref|sku, requested_qty|quantity, in_stock?}. A line needs
    sourcing only when requested_qty > in_stock; fully-in-stock lines are fulfilled from stock and never
    create a case. Re-confirming the same order returns the SAME cases (idempotent). No supplier is
    contacted. Returns {order_group_id, case_count, cases, idempotent}."""
    group_id = order_group_id_for(order_id)
    if not group_id or db is None:
        return {"order_group_id": group_id, "case_count": 0, "cases": [], "idempotent": False}

    resolved = resolve_line_skus(db, lines, tenant_id=tenant_id)
    # only the lines we cannot fill from stock need sourcing (requested > in_stock).
    sourcing = [l for l in resolved
                if int(l.get("requested_qty") or 0) > int(l.get("in_stock") or 0)]

    existing = _already_materialized(db, group_id, tenant_id=tenant_id)
    if existing:
        # this order already materialized — distinguish a double-submit from a real amendment.
        incoming_sig = _line_signature((l.get("item_ref"), l.get("requested_qty")) for l in sourcing)
        existing_sig = _materialized_signature(db, existing, tenant_id=tenant_id)
        if incoming_sig == existing_sig:
            return {"order_group_id": group_id, "case_count": len(existing),
                    "cases": [{"case_id": c} for c in existing], "idempotent": True}
        # the buyer changed their mind AFTER committing this order — the lines differ. Do NOT silently
        # return the stale cases and do NOT duplicate; signal that supersession is required (Phase 4). The
        # caller surfaces amend_required so the existing cases can be superseded under a deliberate action.
        return {"order_group_id": group_id, "case_count": len(existing),
                "cases": [{"case_id": c} for c in existing], "idempotent": False,
                "amend_required": True, "reason": "order_lines_changed"}

    if not sourcing:
        return {"order_group_id": group_id, "case_count": 0, "cases": [], "idempotent": False}

    plan = plan_order_split(db, lines=sourcing, tenant_id=tenant_id)
    if not (plan.get("groups") or []):
        return {"order_group_id": group_id, "case_count": 0, "cases": [], "idempotent": False}

    emit_split_trace(trace_id, plan=plan)
    created = create_grouped_cases(db, plan=plan, uid=uid, uid_hash=uid_hash, trace_id=trace_id,
                                   order_group_id=group_id, now_iso=now_iso, requirements=requirements)
    created["idempotent"] = False
    return created
