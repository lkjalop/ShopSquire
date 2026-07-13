"""Bulk-order economics (V2 Phase 1f) — the ÷units viability + tradeoff menu for a bulk/procurement
ask ('N units for <use-case>, $T total'). PURE: given quantity, total budget, the per-unit
capability floor, and optionally a cheaper bundle floor, it computes whether the order fits and, if
not, the honest options — increase budget, reduce units, the bundle-makes-it-fit path, a payment
plan. No I/O; the core stage feeds it the retrieved floors. This is the bridge between the smart
single-item core and the buy-side."""
from __future__ import annotations

from typing import Any, Dict, Optional


def assess_bulk(quantity: Optional[int], total_cents: Optional[int], floor_cents: Optional[int],
                *, bundle_floor_cents: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """quantity × per-unit floor vs total budget → viability + tradeoffs. None when there's no
    quantity or no floor (nothing to size). total_cents None → 'here's the total, tell me budget'.
    All money in CENTS."""
    if not quantity or quantity < 1 or not floor_cents:
        return None
    needed = quantity * floor_cents
    per_unit = (total_cents // quantity) if total_cents else None
    units_affordable = (total_cents // floor_cents) if total_cents else None
    fits = bool(total_cents) and needed <= total_cents
    out: Dict[str, Any] = {
        "quantity": quantity, "total_cents": total_cents, "per_unit_cents": per_unit,
        "floor_cents": floor_cents, "needed_cents": needed,
        "units_affordable": units_affordable,
        "verdict": ("fits" if fits else ("unsized" if not total_cents else "over_budget")),
        "tradeoffs": [],
    }
    if fits or not total_cents:
        return out
    t = out["tradeoffs"]
    t.append({"id": "increase_budget", "delta_cents": needed - total_cents,
              "label": f"Increase budget to ~${needed / 100:,.0f} for all {quantity}"})
    if units_affordable:
        t.append({"id": "reduce_units", "units": units_affordable,
                  "label": f"Keep ${total_cents / 100:,.0f} → about {units_affordable} units"})
    if bundle_floor_cents and bundle_floor_cents < floor_cents:
        b_needed = quantity * bundle_floor_cents
        b_fits = b_needed <= total_cents
        out["bundle"] = {"floor_cents": bundle_floor_cents, "needed_cents": b_needed,
                         "fits": b_fits, "units_affordable": total_cents // bundle_floor_cents}
        t.append({"id": "bundle", "fits": b_fits, "needed_cents": b_needed,
                  "label": (f"Bundle path (cheaper laptop + tablet) fits all {quantity}: "
                            f"~${b_needed / 100:,.0f}") if b_fits else
                           (f"Bundle path: {total_cents // bundle_floor_cents} units in "
                            f"${total_cents / 100:,.0f}, or ~${b_needed / 100:,.0f} for all {quantity}")})
    # review-10: don't ASSERT a payment plan exists (no tenant financing policy) — offer to check.
    t.append({"id": "financing_review",
              "label": f"Request a financing review for the ~${needed / 100:,.0f}"})
    return out
