"""Multi-location availability + transfer feasibility (agnostic CORE).

`inventory_level` is keyed by (sku, location_id), but `assess_availability` only ever sees the SUM across
locations — so a bulk request can't tell "we have 20 at the warehouse and 5 at the buyer's preferred store"
from "we have 25 somewhere". This module surfaces the per-location breakdown and, when the buyer's
preferred location is short, proposes a TRANSFER plan from other locations before any supplier reorder.

Vertical-blind: pure sku / location_id / quantity math (works for laptops, chairs, or shirts-by-size).
Never raises. The only thing it can't cover from the network becomes the real shortfall → supplier RFQ.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

DEFAULT_TENANT = "default"


def stock_by_location(db, skus: List[str], *, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Dict[str, int]]:
    """{sku: {location_id: available_qty}} for skus that HAVE inventory_level rows. A sku/location with no
    row is omitted (not zeroed) — same honesty rule as commerce_catalog.batch_available."""
    skus = [str(s) for s in (skus or []) if str(s).strip()]
    if db is None or not skus:
        return {}
    try:
        from sqlalchemy import text
        params: Dict[str, Any] = {"t": str(tenant_id).strip() or DEFAULT_TENANT}
        placeholders = []
        for i, s in enumerate(skus):
            params[f"s{i}"] = s
            placeholders.append(f":s{i}")
        rows = db.execute(text(
            "SELECT sku, COALESCE(location_id,'default'), COALESCE(SUM(available),0) FROM inventory_level "
            f"WHERE tenant_id=:t AND sku IN ({', '.join(placeholders)}) "
            "GROUP BY sku, location_id"), params).fetchall()
    except Exception:
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        sku, loc, qty = str(r[0]), str(r[1] or "default"), int(r[2] or 0)
        if qty <= 0:
            continue
        out.setdefault(sku, {})[loc] = qty
    return out


def network_availability(sku: str, requested_qty: int, *, by_location: Dict[str, int],
                         preferred_location: Optional[str] = None) -> Dict[str, Any]:
    """Given per-location stock for ONE sku, compute the network picture + a transfer plan.

    Returns (all opaque refs/ints):
      sku, requested_qty, total_in_network, by_location, locations_with_stock,
      preferred_location, preferred_qty (None if no preferred),
      fully_in_preferred  — preferred location alone covers the order,
      fillable_from_network — the whole network covers the order (maybe via transfer),
      transfer_plan: [{from_location, qty}]  — moves to cover the preferred-location shortfall,
      shortfall — units the WHOLE network can't cover → supplier reorder (RFQ).
    """
    by_location = {str(k): int(v) for k, v in (by_location or {}).items() if int(v or 0) > 0}
    n = int(requested_qty or 0)
    total = sum(by_location.values())
    result: Dict[str, Any] = {
        "sku": str(sku),
        "requested_qty": n,
        "total_in_network": total,
        "by_location": dict(by_location),
        "locations_with_stock": len(by_location),
        "preferred_location": preferred_location,
        "preferred_qty": None,
        "fully_in_preferred": False,
        "fillable_from_network": total >= n if n > 0 else True,
        "transfer_plan": [],
        "shortfall": max(0, n - total),
    }
    if n <= 0:
        return result

    if preferred_location is not None:
        pref_qty = int(by_location.get(str(preferred_location), 0))
        result["preferred_qty"] = pref_qty
        result["fully_in_preferred"] = pref_qty >= n
        need_at_preferred = max(0, n - pref_qty)
        if need_at_preferred > 0:
            # fill the preferred-location gap from the other locations, largest-stock first (deterministic:
            # ties broken by location_id) — only up to what the network actually has.
            others = sorted(((loc, q) for loc, q in by_location.items() if loc != str(preferred_location)),
                            key=lambda kv: (-kv[1], kv[0]))
            remaining = min(need_at_preferred, max(0, total - pref_qty))
            for loc, q in others:
                if remaining <= 0:
                    break
                take = min(q, remaining)
                if take > 0:
                    result["transfer_plan"].append({"from_location": loc, "qty": take})
                    remaining -= take
    return result


def assess_network_availability(db, skus: List[str], requested_qty: int, *,
                                preferred_location: Optional[str] = None,
                                tenant_id: str = DEFAULT_TENANT,
                                stock_by_location_fn: Optional[Callable] = None) -> Dict[str, Any]:
    """Convenience: load per-location stock for the PRIMARY sku and compute network_availability.
    Returns {applicable: False} when there are no skus / non-positive qty. Never raises."""
    skus = [str(s) for s in (skus or []) if str(s).strip()]
    if not skus or int(requested_qty or 0) <= 0:
        return {"applicable": False}
    primary = skus[0]
    try:
        loader = stock_by_location_fn or stock_by_location
        by_loc_all = loader(db, [primary], tenant_id=tenant_id) or {}
    except Exception:
        by_loc_all = {}
    res = network_availability(primary, requested_qty, by_location=by_loc_all.get(primary, {}),
                               preferred_location=preferred_location)
    res["applicable"] = True
    return res
