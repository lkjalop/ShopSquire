"""Deal economics (agnostic CORE) — the operator-only margin/profit math on a procurement case.

Given what the SUPPLIER charges the platform (wholesale) and our RETAIL price to the buyer, it computes
the gross margin, the headroom for a buyer discount that still clears a floor margin, and the resulting
profit. Pure + deterministic; speaks only cents + ratios (no product vocabulary).

NEVER buyer-facing: wholesale cost, margin, and discount headroom are operator/redacted fields — the
API's buyer projection already strips unit_amount_cents/supplier identity, and this is exposed only on
the operator endpoint. The point is to tell the OPERATOR, in <4s, "this deal makes $X; we can hand the
buyer up to a Y% discount and still clear our floor."
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class DealEconomics:
    quantity: int
    supplier_unit_cost_cents: int       # what the supplier charges the platform, per unit (wholesale)
    retail_unit_cents: int              # our list price to the buyer, per unit
    supplier_cost_cents: int            # total wholesale (unit × qty)
    retail_cents: int                   # total retail at list
    gross_profit_cents: int             # retail − wholesale at list
    margin_pct: float                   # gross_profit / retail (0..1)
    floor_margin_pct: float             # the minimum margin the platform will accept
    max_buyer_discount_cents: int       # largest total discount that still clears the floor margin
    max_buyer_discount_pct: float       # that discount as a fraction of retail
    profit_after_max_discount_cents: int  # profit if we hand the buyer the full headroom
    clears_floor: bool                  # is the list deal already above the floor?

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute(*, supplier_unit_cost_cents: Any, retail_unit_cents: Any, quantity: Any = 1,
            floor_margin_pct: float = 0.10) -> Optional[DealEconomics]:
    """Compute the deal economics. Returns None when an input is missing/non-positive (no fake numbers).

    Discount headroom: a discounted retail R' clears the floor when (R' − cost)/R' ≥ floor, i.e.
    R' ≥ cost/(1 − floor). The max discount is retail − that minimum, clamped at 0 (never negative)."""
    su = _int(supplier_unit_cost_cents)
    ru = _int(retail_unit_cents)
    q = _int(quantity)
    if su is None or ru is None or q is None or su <= 0 or ru <= 0 or q <= 0:
        return None
    floor = max(0.0, min(0.95, float(floor_margin_pct)))  # cap so 1−floor never hits 0
    supplier_cost = su * q
    retail = ru * q
    gross = retail - supplier_cost
    margin = (gross / retail) if retail > 0 else 0.0
    min_retail = supplier_cost / (1.0 - floor)           # smallest retail that still clears the floor
    max_discount = max(0, int(round(retail - min_retail)))
    return DealEconomics(
        quantity=q, supplier_unit_cost_cents=su, retail_unit_cents=ru,
        supplier_cost_cents=supplier_cost, retail_cents=retail, gross_profit_cents=gross,
        margin_pct=round(margin, 4), floor_margin_pct=round(floor, 4),
        max_buyer_discount_cents=max_discount,
        max_buyer_discount_pct=round((max_discount / retail) if retail > 0 else 0.0, 4),
        profit_after_max_discount_cents=(retail - max_discount) - supplier_cost,
        clears_floor=margin >= floor,
    )


def from_case(db, case_id: str, *, retail_unit_cents: Optional[int] = None,
              floor_margin_pct: float = 0.10, tenant_id: str = "default") -> Dict[str, Any]:
    """Derive the economics from a fulfilment case (operator-only). Inputs read off the case:
      • supplier wholesale  = validated_quote.unit_amount_cents
      • quantity            = purchase_order.quantity, else the selection's supplier-sourced units
      • retail per unit      = ``retail_unit_cents`` override > the canonical price_book (when
                              COMMERCE_CATALOG_ENABLED, keyed by the case's sku) > the selected option's
                              per-unit retail
    Returns {} when the inputs aren't present yet (e.g. before a quote is validated). Best-effort."""
    from src.app.services.fulfillment import workflow
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    st = cur.state_json if cur else {}
    vq = st.get("validated_quote") or {}
    po = st.get("purchase_order") or {}
    selection = st.get("selection") or {}

    # A supplier unit quote is not landed COGS: freight, duty, handling, and other
    # attributable costs may still be absent. Keep it as an estimate, but authorize
    # discount headroom only when the validated response supplies landed unit cost.
    su = vq.get("landed_unit_cost_cents")
    currency = str(vq.get("landed_cost_currency") or vq.get("currency") or
                   ((st.get("draft") or {}).get("commercial_scope") or {}).get("currency") or
                   "AUD").upper()
    cost_meta: Dict[str, Any] = {}
    cost_basis = "validated_landed_supplier_quote" if su is not None else None
    if su is None and vq.get("unit_amount_cents") is not None:
        su = vq.get("unit_amount_cents")
        cost_basis = "validated_supplier_quote_unlanded"
    if su is None:
        cost_meta = _catalog_supplier_cost(db, st, tenant_id, currency)
        su = cost_meta.get("unit_cost_cents")
        if su is not None:
            cost_basis = str(cost_meta.get("cost_basis") or "approved_supplier_offer")
    if su is None:
        su = _catalog_wholesale(db, st, tenant_id)  # legacy supplier-level fallback
        if su is not None:
            cost_basis = "approved_supplier_catalog"
    qty = po.get("quantity")
    if qty is None:
        qty = sum(int(a.get("quantity") or 0) for a in (selection.get("allocation") or [])
                  if a.get("source") in ("supplier", "substitute"))
    if not qty:
        # PRE-SEND (at QUOTE_DRAFTED / AWAITING_APPROVAL there is no PO or selection yet): use the quantity
        # the draft actually asks the supplier for (the shortfall being sourced) so margin is real AT the
        # send-approval gate — the moment the operator decides whether the reorder is worth it.
        scope = (st.get("draft") or {}).get("commercial_scope") or {}
        avail = st.get("availability") or {}
        qty = scope.get("quantity") or avail.get("shortfall") or avail.get("requested_qty")
    ru = retail_unit_cents
    if ru is None:
        ru = _catalog_retail(db, st, tenant_id)   # canonical price_book JOIN (flag-gated)
    if ru is None:
        ru = _selected_retail_unit(st)            # fallback: derive from the selected option
    if ru is None:
        ru = _product_retail(db, _case_sku(st))   # last resort: the product catalog list price (always present)
    econ = compute(supplier_unit_cost_cents=su, retail_unit_cents=ru, quantity=qty,
                   floor_margin_pct=floor_margin_pct)
    if not econ:
        return {}
    out = econ.to_dict()
    landed = cost_basis == "validated_landed_supplier_quote"
    simulation_only = bool(cost_meta.get("simulation_only"))
    out.update({"available": True, "cost_basis": cost_basis, "currency": currency,
                "landed_cost_complete": landed,
                "discount_headroom_authorized": landed,
                "cost_is_estimated": not landed, "simulation_only": simulation_only,
                "cost_provenance": cost_meta.get("provenance_chain") or [],
                "cost_confidence": cost_meta.get("confidence"),
                "currency_conversion_applied": False})
    return out


def _case_sku(state_json: Dict[str, Any]) -> Optional[str]:
    """The case's item id, wherever it was recorded (PO > draft scope > availability)."""
    po = state_json.get("purchase_order") or {}
    scope = (state_json.get("draft") or {}).get("commercial_scope") or {}
    avail = state_json.get("availability") or {}
    sku = po.get("item_ref") or scope.get("item_ref") or avail.get("item_ref")
    return str(sku) if sku else None


def _catalog_retail(db, state_json: Dict[str, Any], tenant_id: str) -> Optional[int]:
    """Canonical retail from price_book_entry for the case's sku — only when the catalog flag is on."""
    from src.app.services import commerce_catalog
    if not commerce_catalog.catalog_enabled():
        return None
    sku = _case_sku(state_json)
    if not sku:
        return None
    return commerce_catalog.retail_unit_cents(db, sku, tenant_id=tenant_id)


def _product_retail(db, sku: Optional[str]) -> Optional[int]:
    """The product catalog list price (cents) for a SKU — the always-present retail fallback when neither a
    canonical price_book row nor a selected option supplies one, so margin is computable for any active
    catalog SKU (fixes the demo 'insufficient_data'). Best-effort; None on any failure."""
    if db is None or not sku:
        return None
    try:
        from sqlalchemy import text
        row = db.execute(text("SELECT price_cents FROM products WHERE sku=:s LIMIT 1"),
                         {"s": str(sku)}).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _catalog_wholesale(db, state_json: Dict[str, Any], tenant_id: str) -> Optional[int]:
    """Wholesale fallback (no live quote): the cheapest approved supplier's cost for the case's sku.
    Flag-gated so default behaviour (use the validated quote only) is unchanged."""
    from src.app.services import commerce_catalog, supplier_catalog
    if not commerce_catalog.catalog_enabled():
        return None
    sku = _case_sku(state_json)
    if not sku:
        return None
    return supplier_catalog.cheapest_wholesale_cents(db, sku)


def _catalog_supplier_cost(db, state_json: Dict[str, Any], tenant_id: str,
                           currency: str) -> Dict[str, Any]:
    """Tenant/SKU/currency cost offer, including whether it is simulation-only."""
    from src.app.services import commerce_catalog, supplier_catalog
    if not commerce_catalog.catalog_enabled():
        return {}
    sku = _case_sku(state_json)
    if not sku:
        return {}
    return supplier_catalog.best_supplier_cost(
        db, sku, tenant_id=tenant_id, currency=currency,
    ) or {}


def _selected_retail_unit(state_json: Dict[str, Any]) -> Optional[int]:
    """Per-unit retail from the option the buyer selected (its retail total ÷ its unit count)."""
    sel = (state_json.get("selection") or {}).get("option_id")
    for o in state_json.get("options") or []:
        if o.get("option_id") == sel:
            units = _int(o.get("total_units"))
            total = _int(o.get("total_amount_cents"))
            if units and total and units > 0:
                return int(round(total / units))
    return None


def _int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None
