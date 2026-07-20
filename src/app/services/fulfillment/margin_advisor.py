"""Margin advisor (agnostic CORE) — the sell engine's rung-A brain: COMPUTE + PROPOSE, never commit.

Before a human approves sending a supplier reorder, they should see whether the deal is worth it: the margin
at list, whether it clears the floor, the historical supplier price, and how much discount we could give the
buyer to close the sale while still clearing the floor. This module computes all of that (pure analysis,
$0 at risk, reversible) and proposes a discount — it NEVER applies a price or sends anything (that stays the
human GATE 2 / rung C).

verdict:
  • healthy     — margin comfortably above the floor (room to discount to win)
  • thin        — above the floor but within the buffer (discount cautiously)
  • below_floor — the list deal does not clear the floor → flag before sending (the "not worth it" warning)

Vertical-blind: cents + ratios only; no product vocabulary.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("shopsquire.margin_advisor")

# margin above the floor we try to KEEP when proposing a buyer discount (so a discount never lands the deal
# exactly on the floor — leave a safety buffer). Tunable; governance vocabulary, not product flavour.
_DISCOUNT_BUFFER_PCT = 0.05


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def assess(db, case_id: str, *, retail_unit_cents: Optional[int] = None,
           floor_margin_pct: float = 0.10, tenant_id: str = "default") -> Dict[str, Any]:
    """Margin verdict + a proposed buyer discount for a case (operator-only, rung A). Returns
    {available, verdict, economics, max_buyer_discount_cents, recommended_buyer_discount_cents,
    supplier_last_invoice_cents, rationale}. available=False when the inputs aren't present yet."""
    from src.app.services.fulfillment import economics as feco
    econ = feco.from_case(db, case_id, retail_unit_cents=retail_unit_cents,
                          floor_margin_pct=floor_margin_pct, tenant_id=tenant_id)
    if not econ or not econ.get("retail_cents"):
        return {"available": False, "reason": "insufficient_data", "verdict": None,
                "economics": econ or {}, "rationale": ["Margin can't be computed yet — no retail/wholesale on the case."]}

    floor = float(econ.get("floor_margin_pct") or floor_margin_pct)
    margin = float(econ.get("margin_pct") or 0.0)
    clears = bool(econ.get("clears_floor"))
    retail = int(econ.get("retail_cents") or 0)
    cost = int(econ.get("supplier_cost_cents") or 0)
    max_discount = int(econ.get("max_buyer_discount_cents") or 0)
    discount_authorized = bool(econ.get("discount_headroom_authorized"))

    if not clears:
        verdict = "below_floor"
    elif margin < (floor + _DISCOUNT_BUFFER_PCT):
        verdict = "thin"
    else:
        verdict = "healthy"

    # propose a discount that LEAVES a buffer above the floor (never lands exactly on it). The smallest retail
    # that still keeps margin at floor+buffer is cost/(1-(floor+buffer)); the discount is retail minus that.
    target = min(0.95, floor + _DISCOUNT_BUFFER_PCT)
    min_retail_for_target = (cost / (1.0 - target)) if (1.0 - target) > 0 else retail
    recommended = max(0, int(round(retail - min_retail_for_target))) if clears and discount_authorized else 0
    recommended = min(recommended, max_discount)

    rationale = [
        f"List margin {margin * 100:.1f}% vs floor {floor * 100:.0f}% — "
        + ("clears the floor." if clears else "BELOW the floor: this reorder may not be worth it."),
    ]
    if not discount_authorized:
        rationale.append("Discount headroom is locked until a validated supplier response includes landed unit cost.")
        max_discount = 0
    elif clears and recommended > 0:
        rationale.append(f"You can offer up to {recommended / 100:.0f} discount and still keep a "
                         f"{target * 100:.0f}% margin (hard ceiling {max_discount / 100:.0f}).")
    last_inv = _supplier_last_invoice_cents(db, case_id, tenant_id)
    if last_inv is not None:
        rationale.append(f"Last invoiced from this supplier ~{last_inv / 100:.0f}.")

    return {
        "available": True,
        "verdict": verdict,
        "economics": econ,
        "max_buyer_discount_cents": max_discount,
        "recommended_buyer_discount_cents": recommended,
        "discount_headroom_authorized": discount_authorized,
        "supplier_last_invoice_cents": last_inv,
        "rationale": rationale,
    }


def _supplier_last_invoice_cents(db, case_id: str, tenant_id: str) -> Optional[int]:
    """The historical supplier price (last invoice ~ last quote proxy) for the case's resolved supplier
    domain — surfaced so the operator can sanity-check the deal. None when unknown. Best-effort."""
    try:
        from src.app.services.fulfillment import workflow
        from src.app.services.supplier_inbox_reader import recent_supplier_context
        cur = workflow.repository.current_version(db, case_id, tenant_id)
        st = cur.state_json if cur and isinstance(cur.state_json, dict) else {}
        domain = str(st.get("recipient_domain")
                     or (st.get("draft") or {}).get("recipient_domain") or "").strip()
        if not domain:
            return None
        ctx = recent_supplier_context(domain=domain, tenant_id=tenant_id)
        return ctx.last_invoice_cents if ctx else None
    except Exception as exc:
        logger.debug("supplier last invoice lookup failed for %s: %s", case_id, exc)
        return None
