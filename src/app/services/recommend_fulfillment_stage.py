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


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None  # observable: callers treat None as "not stated"


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
    is_bulk = bool(order_qty and int(order_qty) > 1)
    # single-item availability ("do you have X?"): assess qty 1 so a fully out-of-stock item can route to
    # procurement (flag-gated default-OFF). Distinct from bulk — never drafts a reorder, only a case.
    single_item = (not is_bulk) and _flag(flags, "FULFILLMENT_SINGLE_ITEM_OOS") \
        and bool(constraints.get("availability_intent"))
    if not (is_bulk or single_item):
        return ""
    from src.app.services.availability_agent import assess_availability, availability_summary_line
    avail_skus = [str(r.get("sku")) for r in (results or [])[:5] if isinstance(r, dict) and r.get("sku")]
    if not avail_skus:
        return ""
    qty = int(order_qty) if is_bulk else 1
    is_b2b_bulk = is_bulk and qty >= 5
    payload["availability"] = assess_availability(
        avail_skus, qty, constraints.get("availability_horizon_days"), draft_reorder=is_b2b_bulk)
    line = availability_summary_line(payload["availability"])
    _maybe_open_case(payload=payload, avail=payload.get("availability") or {}, order_qty=qty,
                     constraints=constraints, uid=uid, uid_hash=uid_hash, trace_id=trace_id,
                     flags=flags, single_item=single_item)
    return line


def _buyer_requirements(constraints: Dict[str, Any]) -> Dict[str, Any]:
    """The buyer's stated requirements, captured on the case so the supplier RFQ can cite them (way-1).
    Budget is kept INTERNAL (operator-only) — it is persisted for the operator but the RFQ renderer never
    puts it in the supplier body (no price anchoring). Vertical-blind: opaque use_case/spec tokens only."""
    reqs: Dict[str, Any] = {}
    uc = str(constraints.get("use_case") or "").strip()
    if uc:
        reqs["use_case"] = uc
    specs = constraints.get("specs")
    if isinstance(specs, list) and specs:
        reqs["specs"] = [str(s) for s in specs if str(s).strip()][:6]
    horizon = _safe_int(constraints.get("availability_horizon_days"))
    if horizon is not None:
        reqs["needed_within_days"] = horizon
    # concrete deadline DATE for the RFQ (today + horizon, or an explicit needed_by) — replaces the vague
    # "the stated deadline" placeholder so the supplier draft is complete and actionable.
    needed_by = str(constraints.get("needed_by") or "").strip()
    if not needed_by and horizon is not None:
        try:
            from datetime import date, timedelta
            needed_by = (date.today() + timedelta(days=int(horizon))).isoformat()
        except Exception:
            needed_by = ""
    if needed_by:
        reqs["needed_by"] = needed_by
    ship_to = str(constraints.get("ship_to") or constraints.get("region") or "").strip()
    if ship_to:
        reqs["ship_to"] = ship_to  # else the RFQ falls back to the profile's configured ship-to region
    bmin, bmax = constraints.get("budget_min"), constraints.get("budget_max")
    if bmin is not None or bmax is not None:
        reqs["budget"] = {"min": bmin, "max": bmax}  # INTERNAL ONLY — never rendered into the supplier RFQ
    return reqs


def _maybe_open_case(*, payload, avail, order_qty, constraints=None, uid, uid_hash, trace_id, flags, single_item=False) -> None:
    """Open a fulfilment_case at GATE 1 on a real shortfall (flag-gated, best-effort). Two entry points:
    a BULK order at/above the threshold, or a SINGLE fully out-of-stock item (single_item=True)."""
    if not _flag(flags, "FULFILLMENT_CASES_ENABLED"):
        return
    try:
        threshold = int((flags or {}).get("FULFILLMENT_BULK_THRESHOLD") or 5)
    except Exception:
        threshold = 5
    shortfall = int((avail or {}).get("shortfall") or 0)
    if shortfall <= 0:
        return  # no shortfall → nothing to procure
    in_stock = int((avail or {}).get("in_stock") or 0)
    bulk_ok = order_qty >= threshold
    single_ok = single_item and in_stock == 0  # a single item we have NONE of → offer to source it
    if not (bulk_ok or single_ok):
        return
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
            _patch = {"availability": {"requested_qty": order_qty,
                                       "in_stock": int((avail or {}).get("in_stock") or 0),
                                       "shortfall": shortfall, "item_ref": item_ref}}
            _reqs = _buyer_requirements(constraints or {})
            if _reqs:
                _patch["requirements"] = _reqs  # way-1: buyer constraints → cited in the supplier RFQ
            fwf.transition(db, case_id=cid, event="availability_assessed", actor=agent,
                           reason_code="bulk_shortfall", trace_id=trace_id, state_patch=_patch)
            fwf.transition(db, case_id=cid, event="request_buyer_commitment", actor=agent, trace_id=trace_id)
            # no db.commit() here — workflow.transition is the single transaction owner (it commits each
            # applied transition, incl. the case row created in the same session). A trailing commit here
            # was redundant and blurred ownership.
        # buyer-safe summary only (no supplier-private data ever in the recommend payload)
        payload["fulfillment_case"] = {"case_id": cid, "status": "awaiting_buyer_commitment",
                                       "item_ref": item_ref, "shortfall": shortfall}
    except Exception as exc:
        record_partial_failure("fulfillment_case_open", exc, trace_id=trace_id)
