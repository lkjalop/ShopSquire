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

import re
from typing import Any, Dict, List, Optional

from src.app.services.safe_stage import record_partial_failure

# Explicit "procure this from a supplier" language. A bulk request carrying this is a B2B REORDER intent — the
# buyer wants to source from a supplier regardless of current retail stock — so the sourcing preview must fire
# even when stock could cover it (a restock/replenishment is not gated on retail availability). Vertical-blind.
_SOURCING_RE = re.compile(
    r"\b(re-?order|re-?stock|procure|procurement|"
    r"source\s+(?:from|them|these|it|this)|from\s+(?:a\s+|the\s+|our\s+)?suppliers?|"
    r"wholesale|bulk\s+(?:order|buy|purchase|reorder)|place\s+an?\s+order\s+with|"
    r"order\s+(?:from|with)\s+(?:a\s+|the\s+|our\s+)?suppliers?)\b", re.IGNORECASE)


def _wants_sourcing(query: Optional[str]) -> bool:
    return bool(query and _SOURCING_RE.search(str(query)))


def _flag(flags: Optional[Dict[str, Any]], key: str) -> bool:
    v = (flags or {}).get(key) if isinstance(flags, dict) else None
    return str(v).strip().lower() in ("1", "true", "yes", "on") if v is not None else False


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None  # observable: callers treat None as "not stated"


def _emit_trace(trace_id: Optional[str], event_type: str, source_id: str, payload_obj: Dict[str, Any]) -> None:
    """Emit one decision-trace agent step (best-effort) so the bulk-procurement journey is visible in the
    Decision Trace. Dormant for non-bulk turns. Never raises into the recommend flow."""
    if not trace_id:
        return
    try:
        from src.app.services.decision_log import log_trace_event
        # durable=True so the procurement-journey / market-intel / alternatives steps PERSIST and show in
        # the Decision Trace Events tab (not just the live stream) — the blank-trace annotation.
        log_trace_event(trace_id=trace_id, event_type=event_type, source_type="agent", source_id=source_id,
                        target_type="system", target_id=None, payload=payload_obj, durable=True)
    except Exception as exc:
        record_partial_failure("trace_emit", exc, trace_id=trace_id)


def run_fulfillment_stage(
    *,
    results: List[Dict[str, Any]],
    constraints: Dict[str, Any],
    payload: Dict[str, Any],
    uid: Optional[str] = None,
    uid_hash: Optional[str] = None,
    trace_id: Optional[str] = None,
    flags: Optional[Dict[str, Any]] = None,
    query: Optional[str] = None,
    pr_id: Optional[str] = None,
) -> str:
    """Compute bulk availability (sets payload['availability']) and, when enabled, open a procurement
    case on a real shortfall. Returns the availability summary line (or '')."""
    # FLUID-PROCUREMENT model (FULFILLMENT_DEFER_TO_CART): a buyer QUERY is a fluid intent, not a
    # commitment. Until cart-confirmation we only PREVIEW the sourcing split (no durable case, no supplier
    # contact) — the durable case materializes at order/cart confirmation (cart_commitment.py). This kills
    # the orphaned-case churn (a new case per browsing query). Default OFF preserves the legacy eager path.
    defer_to_cart = _flag(flags, "FULFILLMENT_DEFER_TO_CART")
    # Multi-line order: a MIXED buyer request ("15 laptops + 10 monitors + 5 headsets") → grouped cases
    # (one per supplier) instead of a single bulk case. Flag-gated (same as single-case creation); a
    # single-line query falls through to the normal path. Best-effort — never breaks the recommend reply.
    if query and _flag(flags, "FULFILLMENT_CASES_ENABLED"):
        try:
            line = (_fluid_multiline_intent(query=query, constraints=constraints, trace_id=trace_id,
                                            payload=payload, pr_id=pr_id)
                    if defer_to_cart else
                    _maybe_multiline_order(query=query, uid=uid, uid_hash=uid_hash, trace_id=trace_id,
                                           payload=payload))
            if line:
                return line
        except Exception as exc:
            record_partial_failure("multiline_order", exc, trace_id=trace_id)
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
    # the top pick's buyer-facing name — reused for the §5 availability line AND the sourcing preview line
    # (so the preview shows the product NAME, not a raw SKU) — DB-free, from the results already in hand.
    _primary_name = ""
    for _r in (results or [])[:1]:
        if isinstance(_r, dict):
            _primary_name = str(_r.get("name") or (_r.get("specs") or {}).get("display_name") or "").strip()
    qty = int(order_qty) if is_bulk else 1
    is_b2b_bulk = is_bulk and qty >= 5
    payload["availability"] = assess_availability(
        avail_skus, qty, constraints.get("availability_horizon_days"), draft_reorder=is_b2b_bulk)
    line = availability_summary_line(payload["availability"])
    # multi-location view: per-location stock + a transfer plan to cover the buyer's preferred-location gap
    # BEFORE any supplier reorder. Merged onto the availability payload (aggregate fields preserved).
    try:
        from src.app.models.db import db_session
        from src.app.services.multi_location_availability import assess_network_availability
        preferred = str(constraints.get("ship_to") or constraints.get("preferred_location") or "").strip() or None
        if not preferred:  # buyer didn't name a location → their default store (profile), so the transfer
            try:          # view can show "fulfil from the warehouse to your store" before sourcing externally
                from src.app.platform.store_profile import profile_slot
                preferred = str(profile_slot("default_fulfillment_location", default="") or "").strip() or None
            except Exception:
                preferred = None
        with db_session() as _db:
            net = assess_network_availability(_db, avail_skus, qty, preferred_location=preferred)
        if isinstance(net, dict) and net.get("applicable"):
            payload["availability"]["network"] = {
                "total_in_network": net.get("total_in_network"), "by_location": net.get("by_location"),
                "preferred_location": net.get("preferred_location"), "preferred_qty": net.get("preferred_qty"),
                "transfer_plan": net.get("transfer_plan"), "fillable_from_network": net.get("fillable_from_network"),
                "shortfall": net.get("shortfall"),
            }
            line = _network_adjusted_availability_line(line, payload["availability"], primary_name=_primary_name)
    except Exception as exc:
        record_partial_failure("network_availability", exc, trace_id=trace_id)
    # decision-trace: the bulk availability assessment is a visible agent step (fires for any bulk query,
    # even before procurement cases are enabled) → fixes the blank-trace "market intelligence" gap.
    if is_bulk:
        _av = payload.get("availability") or {}
        _emit_trace(trace_id, "bulk_availability_assessed", "Market_Intelligence_Agent",
                    {"sku": _av.get("sku"), "order_qty": qty, "in_stock": _av.get("in_stock"),
                     "shortfall": _av.get("shortfall"), "network": _av.get("network")})
        _attach_alternatives(payload=payload, avail=_av, qty=qty, constraints=constraints, trace_id=trace_id)
    _maybe_open_case(payload=payload, avail=payload.get("availability") or {}, order_qty=qty,
                     constraints=constraints, uid=uid, uid_hash=uid_hash, trace_id=trace_id,
                     flags=flags, single_item=single_item, defer=defer_to_cart, pr_id=pr_id,
                     force_sourcing=_wants_sourcing(query), primary_name=_primary_name)
    return line


def _network_adjusted_availability_line(line: str, avail: Dict[str, Any], primary_name: Optional[str] = None) -> str:
    """Prefer location-aware wording when network stock requires a transfer to satisfy the buyer quantity.

    The availability is assessed against the TOP pick's SKU (results[0]) — for a generic browse the buyer
    hasn't chosen a product yet, so we NAME that pick ("For the top match, <name>: …") rather than implying
    "we have N of the thing you want". Keeps the copy honest without hiding availability from a bulk buyer.
    """
    net = (avail or {}).get("network") if isinstance(avail, dict) else {}
    if not isinstance(net, dict) or not net.get("transfer_plan"):
        return line
    try:
        n = int((avail or {}).get("requested_qty") or 0)
        preferred = int(net.get("preferred_qty") or 0)
        moved = sum(int(t.get("qty") or 0) for t in (net.get("transfer_plan") or []) if isinstance(t, dict))
        network_shortfall = int(net.get("shortfall") or 0)
    except Exception:
        return line
    if n <= 0 or moved <= 0:
        return line
    name = str(primary_name or "").strip()
    if name:  # buyer's top pick is known → name it (honest for a generic browse)
        if bool(net.get("fillable_from_network")):
            return (f"For the top match, {name}: {n} units are available across the network — {preferred} at "
                    f"your preferred location now and {moved} can transfer from other locations.")
        return (f"For the top match, {name}: {preferred} at your preferred location now; {moved} can transfer "
                f"from other locations, leaving {network_shortfall} to source.")
    # no product to name → neutral wording (unchanged; preserves existing parity)
    if bool(net.get("fillable_from_network")):
        return (f"On availability: {n} are available across the network; {preferred} at your preferred "
                f"location now and {moved} can transfer from other locations.")
    return (f"On availability: {preferred} at your preferred location now; {moved} can transfer from other "
            f"locations, leaving {network_shortfall} to source.")


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


def _maybe_multiline_order(*, query, uid, uid_hash, trace_id, payload) -> str:
    """Detect a MIXED order in the buyer message and, if ≥2 resolvable lines, create grouped cases (one per
    supplier). Returns a buyer-safe summary line, or '' when it's not a multi-line order. Buyer payload is
    supplier-blind (the recipient is resolved server-side, never shown to the buyer)."""
    from src.app.models.db import db_session
    from src.app.services.fulfillment.order_split import (
        create_grouped_cases, emit_split_trace, parse_order_lines, plan_order_split, resolve_line_skus)
    parsed = parse_order_lines(query)
    if len(parsed) < 2:
        return ""  # not a mixed order → normal single-line path
    with db_session() as db:
        lines = resolve_line_skus(db, parsed)
        if len(lines) < 2:
            return ""
        plan = plan_order_split(db, lines=lines)
        emit_split_trace(trace_id, plan=plan)
        created = create_grouped_cases(db, plan=plan, uid=uid, uid_hash=uid_hash, trace_id=trace_id)
    # buyer-safe summary (no supplier identity): how the mixed order was split + the line items.
    payload["order_group"] = {
        "order_group_id": created.get("order_group_id"), "case_count": created.get("case_count"),
        "lines": [{"item_ref": l["item_ref"], "quantity": l["requested_qty"]} for l in lines],
        "cases": [{"case_id": c["case_id"], "item_count": len(c["lines"]),
                   "total_quantity": c["total_quantity"]} for c in created.get("cases", [])],
    }
    n_units = sum(int(l["requested_qty"]) for l in lines)
    return (f"Your mixed order ({len(lines)} item lines, {n_units} units) was split into "
            f"{created.get('case_count')} sourcing request(s) — each is awaiting your confirmation before "
            f"any supplier is contacted.")


def _fluid_multiline_intent(*, query, constraints, trace_id, payload, pr_id=None) -> str:
    """FLUID-mode counterpart to _maybe_multiline_order: PREVIEW the mixed-order split (read-only) WITHOUT
    materializing any durable case. The buyer's intent stays fluid until cart-confirmation — nothing is
    persisted, nothing is contacted. Sets payload['sourcing_intent'] (buyer-safe, no supplier identity) —
    INCLUDING the buyer's requirements (deadline/use_case/ship_to) so they survive to cart-confirmation and
    land on the case (the supplier RFQ then carries a concrete deadline, not a vague placeholder). Returns a
    summary line, or '' when it is not a mixed order. Cases are created at cart-confirmation."""
    from src.app.models.db import db_session
    from src.app.services.fulfillment.order_split import (
        emit_split_trace, parse_order_lines, plan_order_split, product_names, resolve_line_skus_detailed)
    parsed = parse_order_lines(query)
    if len(parsed) < 2:
        return ""  # genuinely single-line → normal single-line path
    _names: Dict[str, str] = {}
    with db_session() as db:
        detailed = resolve_line_skus_detailed(db, parsed)
        lines = detailed["resolved"]
        unresolved = detailed["unresolved"]
        if not lines and not unresolved:
            return ""  # nothing recognisable as an order line
        # NOTE: we proceed even when only ONE line resolved — collapsing a ≥2-phrase order to the single-line
        # path lost the other resolved line(s). The buyer's full intent is surfaced here (resolved + unresolved).
        plan = plan_order_split(db, lines=lines) if lines else {"group_count": 0}
        _names = product_names(db, [l["item_ref"] for l in lines])  # buyer-facing names, not raw SKUs
    emit_split_trace(trace_id, plan=plan)  # the split is a visible (read-only) preview step
    payload["sourcing_intent"] = {
        "mode": "deferred_to_cart",
        "pr_id": pr_id,  # the STABLE order identity — amendments re-confirm onto the same PR (no duplicate cases)
        "lines": [{"item_ref": l["item_ref"], "name": _names.get(l["item_ref"]), "quantity": l["requested_qty"]} for l in lines],
        "planned_case_count": int(plan.get("group_count") or 0),
    }
    if unresolved:
        # SURFACE phrases we couldn't match instead of dropping them — the buyer clarifies before confirming.
        payload["sourcing_intent"]["unresolved_phrases"] = unresolved
    _reqs = _buyer_requirements(constraints or {})
    if _reqs:
        payload["sourcing_intent"]["requirements"] = _reqs  # carried to confirm-cart → onto the case
    n_units = sum(int(l["requested_qty"]) for l in lines)
    unresolved_note = (f" We couldn't match {len(unresolved)} item(s) you asked for — tell us which products "
                       f"you mean so nothing is missed." if unresolved else "")
    if not lines:
        return (f"We couldn't match {len(unresolved)} of the items you asked for — tell us which products you "
                f"mean and we'll source them.")
    return (f"Your mixed order ({len(lines)} item line(s), {n_units} units) would be split into "
            f"{plan.get('group_count')} sourcing request(s) when you confirm your cart — "
            f"nothing is ordered or sent to a supplier yet.{unresolved_note}")


def _attach_alternatives(*, payload, avail, qty, constraints, trace_id) -> None:
    """Build the buyer-facing alternatives (partial / transfer / substitute / source-shortfall / reduce)
    for an unmet bulk request and attach to payload['fulfillment_options'] for the 5173 right panel.
    Best-effort; only gathers substitutes (a DB read) when there's actually a gap to fill."""
    try:
        net = (avail or {}).get("network") or {}
        shortfall = int((avail or {}).get("shortfall") or 0)
        if shortfall <= 0 and not net.get("transfer_plan"):
            return  # fulfillable as-is at the preferred location → no alternatives needed
        primary = str((avail or {}).get("sku") or "")
        subs: List[Dict[str, Any]] = []
        if primary:
            from src.app.models.db import db_session
            from src.app.services.substitute_generator import find_substitutes
            with db_session() as _db:
                subs = find_substitutes(_db, primary, use_case=(constraints or {}).get("use_case"),
                                        budget_min=(constraints or {}).get("budget_min"),
                                        budget_max=(constraints or {}).get("budget_max"), limit=3) or []
        from src.app.services.bulk_alternatives import build_alternatives
        alts = build_alternatives(sku=primary, requested_qty=qty,
                                  in_stock=int((avail or {}).get("in_stock") or 0), shortfall=shortfall,
                                  network=net, substitutes=subs,
                                  horizon_days=_safe_int((constraints or {}).get("availability_horizon_days")))
        if alts:
            payload["fulfillment_options"] = alts
            _emit_trace(trace_id, "alternatives_generated", "Alternatives_Agent",
                        {"sku": primary, "count": len(alts), "types": [a["type"] for a in alts]})
    except Exception as exc:
        record_partial_failure("bulk_alternatives", exc, trace_id=trace_id)


def _maybe_open_case(*, payload, avail, order_qty, constraints=None, uid, uid_hash, trace_id, flags, single_item=False, defer=False, pr_id=None, force_sourcing=False, primary_name=None) -> None:
    """Open a fulfilment_case at GATE 1 on a real shortfall (flag-gated, best-effort). Two entry points:
    a BULK order at/above the threshold, or a SINGLE fully out-of-stock item (single_item=True).
    When ``defer`` (FULFILLMENT_DEFER_TO_CART), the intent stays FLUID: set payload['sourcing_intent']
    (a buyer-safe preview) and emit a read-only trace, but DO NOT materialize a durable case — the case is
    created at cart-confirmation (cart_commitment.materialize_cases_for_order)."""
    if not _flag(flags, "FULFILLMENT_CASES_ENABLED"):
        return
    try:
        threshold = int((flags or {}).get("FULFILLMENT_BULK_THRESHOLD") or 5)
    except Exception:
        threshold = 5
    shortfall = int((avail or {}).get("shortfall") or 0)
    in_stock = int((avail or {}).get("in_stock") or 0)
    bulk_ok = order_qty >= threshold
    # EXPLICIT reorder/source intent on a bulk request → source the FULL requested qty even if it's in stock
    # (a B2B replenishment is a procurement decision, not gated on current retail availability). This is the
    # fix for "buyer says 'reorder 50 from a supplier' but the item is in stock → no sourcing preview".
    if force_sourcing and bulk_ok and shortfall < order_qty:
        shortfall = order_qty
    if shortfall <= 0:
        return  # no shortfall and no explicit reorder → nothing to procure
    single_ok = single_item and in_stock == 0  # a single item we have NONE of → offer to source it
    if not (bulk_ok or single_ok):
        return
    item_ref = str((avail or {}).get("sku") or "")
    _line = {"item_ref": item_ref, "quantity": order_qty, "shortfall": shortfall}
    if primary_name:  # buyer-facing name (from results[0]) so the preview shows the product, not a raw SKU
        _line["name"] = primary_name
    if defer:
        # FLUID: preview the sourcing intent; the durable case is created at cart-confirmation, not here.
        payload["sourcing_intent"] = {"mode": "deferred_to_cart", "pr_id": pr_id,
                                      "lines": [dict(_line)],
                                      "planned_case_count": 1 if item_ref else 0}
        _reqs = _buyer_requirements(constraints or {})
        if _reqs:
            payload["sourcing_intent"]["requirements"] = _reqs  # deadline/use_case/ship_to → onto the case at confirm
        _emit_trace(trace_id, "sourcing_previewed", "Procurement_Agent",
                    {"item_ref": item_ref, "order_qty": order_qty, "shortfall": shortfall,
                     "mode": "deferred_to_cart"})
        return
    try:
        from src.app.models.db import db_session
        from src.app.services.fulfillment import workflow as fwf
        from src.app.services.fulfillment.domain import Actor, ActorType
        agent = Actor(ActorType.AGENT, "Procurement_Agent")
        with db_session() as db:
            cid = fwf.open_case(db, buyer_uid_hash=(uid_hash or uid), source_trace_id=trace_id,
                                requested_by="recommend")
            if not cid:
                return
            _avail_patch = {"requested_qty": order_qty,
                            "in_stock": int((avail or {}).get("in_stock") or 0),
                            "shortfall": shortfall, "item_ref": item_ref}
            if isinstance((avail or {}).get("network"), dict):
                _avail_patch["network"] = avail["network"]  # per-location + transfer plan → on the case
            _patch = {"availability": _avail_patch}
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
        # decision-trace: the procurement journey has begun (GATE 1 — buyer commitment pending).
        _net = (avail or {}).get("network") or {}
        _emit_trace(trace_id, "procurement_case_opened", "Procurement_Agent",
                    {"case_id": cid, "item_ref": item_ref, "order_qty": order_qty, "shortfall": shortfall,
                     "status": "awaiting_buyer_commitment", "transfer_plan": _net.get("transfer_plan")})
    except Exception as exc:
        record_partial_failure("fulfillment_case_open", exc, trace_id=trace_id)
