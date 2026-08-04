"""Bulk-order alternatives assembler (agnostic CORE).

When a bulk request can't be fully met from the buyer's preferred location, this turns the gathered facts
(local stock, network/transfer, substitutes, shortfall) into the ORDERED set of real choices a buyer can
act on — BEFORE any supplier is contacted. Pure function (no I/O): the caller gathers the inputs
(availability + multi_location_availability + substitute_generator); this just shapes + orders them.

Vertical-blind: opaque sku / location_id / quantity only; the buyer-facing strings are generic ("your
preferred location", "switch to"). Works for laptops, chairs, or shirts-by-size unchanged. Never raises.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

OPT_IN_STOCK = "in_stock_now"
OPT_TRANSFER = "transfer_from_network"
OPT_SUBSTITUTE = "substitute"
OPT_SOURCE_SHORTFALL = "source_shortfall"
OPT_REDUCE = "reduce_to_available"


def build_alternatives(*, sku: str, requested_qty: int, in_stock: int, shortfall: int,
                       network: Optional[Dict[str, Any]] = None,
                       substitutes: Optional[List[Dict[str, Any]]] = None,
                       horizon_days: Optional[int] = None,
                       max_substitutes: int = 3) -> List[Dict[str, Any]]:
    """Ordered, buyer-actionable choices for an unmet bulk request. Empty when fully fulfillable as-is
    (shortfall<=0 and no transfer needed). Each option: {option_id, type, title, detail, ...}."""
    n = int(requested_qty or 0)
    in_stock = int(in_stock or 0)
    shortfall = int(shortfall or 0)
    network = network if isinstance(network, dict) else {}
    transfer_plan = [t for t in (network.get("transfer_plan") or []) if isinstance(t, dict)]
    fully_in_preferred = bool(network.get("fully_in_preferred"))
    fillable_from_network = bool(network.get("fillable_from_network"))

    if n <= 0 or (shortfall <= 0 and (fully_in_preferred or not transfer_plan)):
        return []  # nothing to choose — it's fulfillable as-is at the preferred location

    opts: List[Dict[str, Any]] = []

    # 1. partial available now (preferred location)
    if 0 < in_stock < n:
        opts.append({"option_id": OPT_IN_STOCK, "type": OPT_IN_STOCK,
                     "title": f"{in_stock} of {n} available now",
                     "detail": f"{in_stock} units are in stock at your preferred location right now.",
                     "available_now": in_stock, "requested_qty": n})

    # 2. transfer from other locations → full quantity at the preferred location
    if transfer_plan:
        moved = sum(int(t.get("qty") or 0) for t in transfer_plan)
        locs = ", ".join(str(t.get("from_location")) for t in transfer_plan)
        opts.append({"option_id": OPT_TRANSFER, "type": OPT_TRANSFER,
                     "title": f"Transfer {moved} from other locations",
                     "detail": (f"Move {moved} units from {locs} to your preferred location to reach "
                                f"{'all ' + str(n) if fillable_from_network else str(in_stock + moved)} units."),
                     "transfer_plan": transfer_plan, "covers_full_order": fillable_from_network})

    # 3. substitutes (nearest catalog items by the profile's attributes)
    for sub in (substitutes or [])[: max(0, int(max_substitutes))]:
        if not isinstance(sub, dict) or not sub.get("sku"):
            continue
        opts.append({"option_id": f"{OPT_SUBSTITUTE}:{sub['sku']}", "type": OPT_SUBSTITUTE,
                     "title": f"Switch to {sub.get('name') or sub['sku']}",
                     "detail": str(sub.get("tradeoff") or "a comparable alternative"),
                     "sku": sub["sku"], "price_cents": sub.get("price_cents"),
                     "spec_match": sub.get("spec_match"), "spec_total": sub.get("spec_total")})

    # 4. source the shortfall from a supplier (the procurement path)
    if shortfall > 0:
        horizon_txt = f" (within your {int(horizon_days)}-day window)" if horizon_days else ""
        opts.append({"option_id": OPT_SOURCE_SHORTFALL, "type": OPT_SOURCE_SHORTFALL,
                     "title": f"Source the remaining {shortfall} from a supplier",
                     "detail": (f"Request a supplier quote for the {shortfall}-unit shortfall{horizon_txt}. "
                                f"This drafts an RFQ for review — no order is placed."),
                     "shortfall": shortfall})

    # 5. reduce to what's available now
    if 0 < in_stock < n:
        opts.append({"option_id": OPT_REDUCE, "type": OPT_REDUCE,
                     "title": f"Take the {in_stock} available now",
                     "detail": f"Proceed with {in_stock} units now and skip the rest.",
                     "available_now": in_stock})
    return opts
