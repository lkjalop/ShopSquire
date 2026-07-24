"""Split-fulfillment planner (agnostic CORE) — "ship what's in stock now, source the rest with a REAL ETA".

A bulk order rarely fits entirely in on-hand stock. Rather than blocking (or silently backordering), this
splits each line into what ships NOW (from stock) and what FOLLOWS from a supplier — and the "follows" ETA
is the SUPPLIER's own lead time (a real figure from the supplier catalog, not a guess). Delivery fees and a
free-shipping threshold come from the StoreProfile, so every store using ShopSquire sets its own economics.

Pure + vertical-blind: opaque skus, integer qty, cents, days. No DB, no network — the caller supplies the
stock + supplier lead times + the delivery policy. The buyer then CONFIRMS the split before payment (never
silently split a shipment or add a fee).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DeliveryPolicy:
    currency: str = "USD"
    base_fee_cents: int = 1500              # standard delivery for the in-stock shipment
    split_shipment_fee_cents: int = 900     # extra fee for the second (backordered) shipment
    free_shipping_threshold_cents: int = 0  # order subtotal at/above which ALL delivery is waived (0 = never)
    backorder_enabled: bool = True          # store allows "send available now, rest later"

    def as_dict(self) -> Dict[str, Any]:
        return {"currency": self.currency, "base_fee_cents": self.base_fee_cents,
                "split_shipment_fee_cents": self.split_shipment_fee_cents,
                "free_shipping_threshold_cents": self.free_shipping_threshold_cents,
                "backorder_enabled": self.backorder_enabled}


@dataclass(frozen=True)
class SplitLine:
    sku: str
    requested_qty: int
    in_stock: int
    unit_cents: int = 0
    supplier_lead_time_days: Optional[int] = None   # the assigned supplier's real lead time (the ETA)
    supplier_ref: Optional[str] = None
    availability: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SplitPlan:
    now: List[Dict[str, Any]] = field(default_factory=list)     # {sku, qty, unit_cents}
    later: List[Dict[str, Any]] = field(default_factory=list)   # {sku, qty, unit_cents, eta_days, supplier_ref}
    transfers: List[Dict[str, Any]] = field(default_factory=list)
    availability: List[Dict[str, Any]] = field(default_factory=list)
    subtotal_cents: int = 0
    delivery: Dict[str, Any] = field(default_factory=dict)
    fully_in_stock: bool = True
    rationale: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"now": self.now, "later": self.later, "transfers": self.transfers,
                "availability": self.availability, "subtotal_cents": self.subtotal_cents,
                "delivery": self.delivery, "fully_in_stock": self.fully_in_stock, "rationale": self.rationale}


def compute_split(lines: List[SplitLine], *, policy: Optional[DeliveryPolicy] = None) -> SplitPlan:
    """Split lines into now/later and price the delivery. ``later`` carries the supplier's real lead time as
    ``eta_days``. Fully-in-stock → one shipment, no split fee. Free-shipping threshold waives both fees."""
    pol = policy or DeliveryPolicy()
    now: List[Dict[str, Any]] = []
    later: List[Dict[str, Any]] = []
    transfers: List[Dict[str, Any]] = []
    availability: List[Dict[str, Any]] = []
    subtotal = 0
    for l in lines:
        req = max(0, int(l.requested_qty or 0))
        combined = dict(l.availability or {})
        stock = max(0, int(l.in_stock or 0))
        subtotal += int(l.unit_cents or 0) * req
        local_now = min(req, max(0, int(combined.get("local_now", stock) or 0)))
        transfer_qty = min(max(0, req - local_now), max(0, int(combined.get("network_transfer") or 0)))
        back = max(0, int(combined.get("supplier_rfq_qty", req - local_now - transfer_qty) or 0))
        avail = local_now
        if avail > 0:
            now.append({"sku": l.sku, "qty": avail, "unit_cents": int(l.unit_cents or 0)})
        if transfer_qty > 0:
            transfers.append({
                "sku": l.sku, "qty": transfer_qty, "unit_cents": int(l.unit_cents or 0),
                "to_location": combined.get("preferred_location"),
                "transfer_plan": list(combined.get("transfer_plan") or []),
            })
        if back > 0:
            later.append({"sku": l.sku, "qty": back, "unit_cents": int(l.unit_cents or 0),
                          "eta_days": (int(l.supplier_lead_time_days) if l.supplier_lead_time_days is not None else None),
                          "supplier_ref": l.supplier_ref})
        availability.append({
            "sku": l.sku, "requested": req, "local_now": local_now,
            "network_transfer": transfer_qty, "supplier_rfq_qty": back,
            "total_in_network": int(combined.get("total_in_network", stock) or 0),
            "by_location": dict(combined.get("by_location") or {}),
            "preferred_location": combined.get("preferred_location"),
            "transfer_plan": list(combined.get("transfer_plan") or []),
            "supplier_availability": "unconfirmed_rfq",
        })

    fully = not later
    free = bool(pol.free_shipping_threshold_cents) and subtotal >= pol.free_shipping_threshold_cents
    fee_now = 0 if (free or not now) else int(pol.base_fee_cents)
    # a second shipment only exists when there IS a backordered part AND the store allows backorder
    has_second = bool(later) and pol.backorder_enabled
    fee_later = 0 if (free or not has_second) else int(pol.split_shipment_fee_cents)
    shipments = (1 if (now or transfers) else 0) + (1 if has_second else 0)

    # a real, plain-English rationale using the supplier ETAs (max ETA across backordered lines).
    max_eta = max([int(x["eta_days"]) for x in later if x.get("eta_days") is not None], default=None)
    if fully:
        rationale = "All items are in stock — one shipment."
    elif not pol.backorder_enabled:
        rationale = "Some items exceed on-hand stock and this store does not backorder — reduce the qty or source separately."
    else:
        eta_txt = f" in ~{max_eta} days (supplier lead time)" if max_eta is not None else " once replenished"
        local_qty = sum(x["qty"] for x in now)
        transfer_total = sum(x["qty"] for x in transfers)
        transfer_txt = f"; {transfer_total} transfer from other locations" if transfer_total else ""
        rationale = (f"{local_qty} unit(s) are ready at the preferred location{transfer_txt}; "
                     f"{sum(x['qty'] for x in later)} require a supplier RFQ{eta_txt}.")

    delivery = {
        "currency": pol.currency,
        "fee_now_cents": fee_now,
        "fee_later_cents": fee_later,
        "total_fee_cents": fee_now + fee_later,
        "free_shipping_threshold_cents": pol.free_shipping_threshold_cents,
        "waived": free,
        "shipments": shipments,
        "backorder_enabled": pol.backorder_enabled,
    }
    return SplitPlan(now=now, later=later, transfers=transfers, availability=availability,
                     subtotal_cents=subtotal, delivery=delivery,
                     fully_in_stock=fully, rationale=rationale)


def delivery_policy_from_profile() -> DeliveryPolicy:
    """Read the active StoreProfile's ``delivery_policy`` slot (agnostic: each store sets its own fees +
    free-shipping threshold). Falls back to sane defaults when the slot is absent — never raises."""
    slot: Dict[str, Any] = {}
    try:
        from src.app.platform.store_profile import get_store_profile
        prof = get_store_profile()
        if isinstance(prof, dict):
            slot = prof.get("delivery_policy") or {}
    except Exception:
        slot = {}
    base = DeliveryPolicy()
    if not isinstance(slot, dict):
        return base
    def _int(k: str, d: int) -> int:
        try:
            return int(slot.get(k, d))
        except (TypeError, ValueError):
            return d
    return DeliveryPolicy(
        currency=str(slot.get("currency") or base.currency),
        base_fee_cents=_int("base_fee_cents", base.base_fee_cents),
        split_shipment_fee_cents=_int("split_shipment_fee_cents", base.split_shipment_fee_cents),
        free_shipping_threshold_cents=_int("free_shipping_threshold_cents", base.free_shipping_threshold_cents),
        backorder_enabled=bool(slot.get("backorder_enabled", base.backorder_enabled)),
    )
