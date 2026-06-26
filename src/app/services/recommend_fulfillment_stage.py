"""Recommend fulfilment stage (agnostic CORE) — the bulk-availability block, extracted from suggest().

Two responsibilities, cleanly separated so recommend.py only gains a stage call:
  1. AVAILABILITY (behaviour-preserving): for a bulk order_quantity, assess "can we fulfil N of the
     primary pick by the horizon?" — sets payload['availability'] + returns the summary line, exactly
     as the inline block did.
  2. PROCUREMENT CASE TRIGGER (new, flag-gated default-OFF): when a real bulk shortfall exists, open a
     durable fulfilment_case and advance it to AWAITING_BUYER_COMMITMENT (GATE 1 — no supplier is
     contacted; the case waits for the buyer to commit). Attaches a buyer-safe {case_id, status,
     shortfall} to payload['fulfillment_case']. Best-effort — a case-open failure never breaks the
     recommend response.

NO procurement workflow logic lives in recommend.py — only this stage call. Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.services.safe_stage import record_partial_failure


def _flag(flags: Optional[Dict[str, Any]], key: str) -> bool:
    v = (flags or {}).get(key) if isinstance(flags, dict) else None
    return str(v).strip().lower() in ("1", "true", "yes", "on") if v is not None else False


def run_fulfillment_stage(
    *,
    results: List[Dict[str, Any]],
    constraints: Dict[str, Any],
    payload: Dict[str, Any],
    uid: Optional[str] = None,
    uid_hash: Optional[str] = None,
    trace_id: Optional[str] = None,
    flags: Optional[Dict[str, Any]] = None,
) -> str:
    """Compute bulk availability (sets payload['availability']) and, when enabled, open a procurement
    case on a real shortfall. Returns the availability summary line (or '')."""
    order_qty = constraints.get("order_quantity")
    if not (order_qty and int(order_qty) > 1):
        return ""
    from src.app.services.availability_agent import assess_availability, availability_summary_line
    avail_skus = [str(r.get("sku")) for r in (results or [])[:5] if isinstance(r, dict) and r.get("sku")]
    if not avail_skus:
        return ""
    is_b2b_bulk = int(order_qty) >= 5
    payload["availability"] = assess_availability(
        avail_skus, int(order_qty), constraints.get("availability_horizon_days"), draft_reorder=is_b2b_bulk)
    line = availability_summary_line(payload["availability"])
    _maybe_open_case(payload=payload, avail=payload.get("availability") or {}, order_qty=int(order_qty),
                     uid=uid, uid_hash=uid_hash, trace_id=trace_id, flags=flags)
    return line


def _maybe_open_case(*, payload, avail, order_qty, uid, uid_hash, trace_id, flags) -> None:
    """Open a fulfilment_case at GATE 1 on a real bulk shortfall (flag-gated, best-effort)."""
    if not _flag(flags, "FULFILLMENT_CASES_ENABLED"):
        return
    try:
        threshold = int((flags or {}).get("FULFILLMENT_BULK_THRESHOLD") or 5)
    except Exception:
        threshold = 5
    if order_qty < threshold:
        return
    shortfall = int((avail or {}).get("shortfall") or 0)
    if shortfall <= 0:
        return  # no shortfall → nothing to procure
    try:
        from src.app.models.db import db_session
        from src.app.services.fulfillment import workflow as fwf
        from src.app.services.fulfillment.domain import Actor, ActorType
        item_ref = str((avail or {}).get("sku") or "")
        agent = Actor(ActorType.AGENT, "Procurement_Agent")
        with db_session() as db:
            cid = fwf.open_case(db, buyer_uid_hash=(uid_hash or uid), source_trace_id=trace_id,
                                requested_by="recommend")
            if not cid:
                return
            fwf.transition(db, case_id=cid, event="availability_assessed", actor=agent,
                           reason_code="bulk_shortfall", trace_id=trace_id,
                           state_patch={"availability": {"requested_qty": order_qty,
                                        "in_stock": int((avail or {}).get("in_stock") or 0),
                                        "shortfall": shortfall, "item_ref": item_ref}})
            fwf.transition(db, case_id=cid, event="request_buyer_commitment", actor=agent, trace_id=trace_id)
            # no db.commit() here — workflow.transition is the single transaction owner (it commits each
            # applied transition, incl. the case row created in the same session). A trailing commit here
            # was redundant and blurred ownership.
        # buyer-safe summary only (no supplier-private data ever in the recommend payload)
        payload["fulfillment_case"] = {"case_id": cid, "status": "awaiting_buyer_commitment",
                                       "item_ref": item_ref, "shortfall": shortfall}
    except Exception as exc:
        record_partial_failure("fulfillment_case_open", exc, trace_id=trace_id)
