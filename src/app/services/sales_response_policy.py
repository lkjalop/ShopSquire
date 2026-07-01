"""Sales-response policy (agnostic CORE) — how the sell side responds as market intelligence changes.

This is the missing link between the market-analysis DETECTORS (demand shift/forecast, inventory
mismatch) and a coherent SELL-SIDE decision. Given a situation for one item —

    { demand_trend, inventory_position, margin_headroom }

— it returns what should happen to that item's DISCOUNT, PRICE, PROMOTION visibility, and REORDER
urgency, with the rationale that produced each. It answers the owner's question directly: "how do sales
change as demand / inventory / margin change?"

Two invariants:
  • It RECOMMENDS, never ACTS. The output is a proposal an operator (or a gated action) applies — nothing
    here mutates a price, a cart, or a supplier order.
  • Margin is a HARD constraint. A recommended discount is ALWAYS clamped to the headroom that still clears
    the margin floor (from economics). The policy can never propose selling below the floor.

Vertical-blind: demand / inventory / margin / discount are commerce-generic. There is NO product
vocabulary here (no sku patterns, no gpu/ram/brand literals) — the item is an opaque ref. Pure functions:
no DB, no request locals, no LLM. Deterministic → fully testable and auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── vocabularies (opaque enums, not product terms) ───────────────────────────
DEMAND_RISING, DEMAND_STEADY, DEMAND_FALLING = "rising", "steady", "falling"
INV_SHORTAGE, INV_BALANCED, INV_SURPLUS = "shortage", "balanced", "surplus"
MARGIN_THIN, MARGIN_HEALTHY, MARGIN_GENEROUS = "thin", "healthy", "generous"

DISCOUNT_INCREASE, DISCOUNT_HOLD, DISCOUNT_REDUCE = "increase", "hold", "reduce"
PRICE_RAISE, PRICE_HOLD, PRICE_LOWER = "raise", "hold", "lower"
PROMO_BOOST, PROMO_STEADY, PROMO_SUPPRESS = "boost", "steady", "suppress"
REORDER_URGENT, REORDER_NORMAL, REORDER_DEFER = "urgent", "normal", "defer"

# discount depth targets (fraction of retail) BEFORE the margin clamp — a strong move-the-stock signal
# aims deeper, a mild one shallower. The margin ceiling always wins.
_DEEP_DISCOUNT_TARGET = 0.15
_MILD_DISCOUNT_TARGET = 0.08
# margin-headroom thresholds on max-clearing-floor discount pct
_THIN_MAX = 0.05
_HEALTHY_MAX = 0.15
# surplus when on-hand covers demand this many times over
_SURPLUS_MULT = 3.0


@dataclass(frozen=True)
class SalesSituation:
    demand_trend: str = DEMAND_STEADY
    inventory_position: str = INV_BALANCED
    margin_headroom: str = MARGIN_HEALTHY
    max_discount_pct: float = 0.0          # hard ceiling that still clears the floor (0 = unknown → no discount)
    demand_confidence: float = 0.5


@dataclass(frozen=True)
class SalesResponse:
    discount_action: str
    recommended_discount_pct: float        # ALWAYS ≤ situation.max_discount_pct
    price_bias: str
    promotion_bias: str
    reorder_urgency: str
    rationale: List[str] = field(default_factory=list)
    situation: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "discount_action": self.discount_action,
            "recommended_discount_pct": self.recommended_discount_pct,
            "price_bias": self.price_bias,
            "promotion_bias": self.promotion_bias,
            "reorder_urgency": self.reorder_urgency,
            "rationale": list(self.rationale),
            "situation": dict(self.situation),
        }


# ── classifiers: turn the existing detector/agent outputs into the three axes ──
def classify_demand_trend(findings: Optional[List[Any]]) -> tuple[str, float]:
    """Reduce demand_shift / demand_forecast findings to (trend, confidence). Reads the ``direction`` the
    detectors already carry in evidence (spike→rising, slowdown→falling), weighting by severity then
    confidence, and picks the STRONGEST signal. Accepts MarketFinding objects or plain dicts. Empty → steady."""
    sev_w = {"critical": 2.0, "warn": 1.0, "info": 0.5}
    best_trend, best_weight, best_conf = DEMAND_STEADY, 0.0, 0.5
    for f in (findings or []):
        ftype = _attr(f, "finding_type")
        if ftype not in ("demand_shift", "demand_forecast"):
            continue
        ev = _attr(f, "evidence") or {}
        direction = str((ev.get("direction") if isinstance(ev, dict) else "") or "").strip().lower()
        if direction == "spike":
            trend = DEMAND_RISING
        elif direction == "slowdown":
            trend = DEMAND_FALLING
        else:
            continue
        conf = _to_float(_attr(f, "confidence"), 0.5)
        weight = sev_w.get(str(_attr(f, "severity") or "warn").lower(), 1.0) * max(0.1, conf)
        # a forecast is forward-looking → slightly discount vs a realised shift
        if ftype == "demand_forecast":
            weight *= 0.9
        if weight > best_weight:
            best_trend, best_weight, best_conf = trend, weight, conf
    return best_trend, best_conf


def classify_inventory_position(availability: Optional[Dict[str, Any]], *,
                                demand_units: Optional[int] = None) -> str:
    """shortage when there's a shortfall for the requested quantity; surplus when on-hand covers
    demand many times over; balanced otherwise. ``demand_units`` (recent demand volume) refines surplus;
    absent, the requested quantity stands in. Unknown availability → balanced (neutral)."""
    a = availability if isinstance(availability, dict) else {}
    shortfall = _to_int(a.get("shortfall"), 0)
    if shortfall > 0:
        return INV_SHORTAGE
    in_stock = _to_int(a.get("in_stock"), None)
    if in_stock is None:
        return INV_BALANCED
    reference = demand_units if (isinstance(demand_units, int) and demand_units > 0) else _to_int(a.get("requested_qty"), 0)
    if reference and in_stock >= reference * _SURPLUS_MULT:
        return INV_SURPLUS
    return INV_BALANCED


def classify_margin_headroom(economics: Optional[Any]) -> tuple[str, float]:
    """(headroom, max_discount_pct) from deal economics. Reads max_buyer_discount_pct (the deepest discount
    that still clears the margin floor). Below floor / unknown → thin, 0.0 (no room)."""
    e = economics
    if e is None:
        return MARGIN_THIN, 0.0
    max_pct = _to_float(_attr(e, "max_buyer_discount_pct"), 0.0)
    clears = _attr(e, "clears_floor")
    if clears is False:
        return MARGIN_THIN, 0.0
    if max_pct < _THIN_MAX:
        return MARGIN_THIN, max(0.0, max_pct)
    if max_pct < _HEALTHY_MAX:
        return MARGIN_HEALTHY, max_pct
    return MARGIN_GENEROUS, max_pct


# ── the decision matrix ───────────────────────────────────────────────────────
def decide(situation: SalesSituation) -> SalesResponse:
    """Map a SalesSituation → SalesResponse. Explainable: every axis appends its rationale. Discount is
    computed as a target then CLAMPED to the margin ceiling (never proposes below the floor)."""
    dt, inv, margin = situation.demand_trend, situation.inventory_position, situation.margin_headroom
    rationale: List[str] = []

    # discount pressure: falling demand and/or surplus stock push to discount; rising demand and/or a
    # shortage push the other way (protect margin, don't discount what's selling / scarce). Range [-2, +2].
    pressure = 0
    if dt == DEMAND_FALLING:
        pressure += 1; rationale.append("Demand is softening — a discount can re-stimulate it.")
    elif dt == DEMAND_RISING:
        pressure -= 1; rationale.append("Demand is rising — no need to discount what's already selling.")
    if inv == INV_SURPLUS:
        pressure += 1; rationale.append("Stock is in surplus — moving units matters more than peak margin.")
    elif inv == INV_SHORTAGE:
        pressure -= 1; rationale.append("Stock is short — discounting would only accelerate a stockout.")

    if pressure >= 1:
        discount_action = DISCOUNT_INCREASE
        target = _DEEP_DISCOUNT_TARGET if pressure >= 2 else _MILD_DISCOUNT_TARGET
    elif pressure <= -1:
        discount_action = DISCOUNT_REDUCE
        target = 0.0
        rationale.append("Recommend trimming any promotional discount to hold margin.")
    else:
        discount_action = DISCOUNT_HOLD
        target = 0.0

    # HARD margin clamp — the recommended discount can never exceed what clears the floor.
    ceiling = max(0.0, float(situation.max_discount_pct or 0.0))
    recommended = round(min(target, ceiling), 4)
    if discount_action == DISCOUNT_INCREASE and recommended < target:
        if ceiling <= 0.0:
            rationale.append("Margin is too thin to discount — recommend clearing via visibility/price, not price cuts.")
        else:
            rationale.append(f"Discount capped at {int(round(ceiling * 100))}% by the margin floor (wanted deeper).")

    # price bias
    if dt == DEMAND_RISING and inv == INV_SHORTAGE and margin in (MARGIN_HEALTHY, MARGIN_GENEROUS):
        price_bias = PRICE_RAISE
        rationale.append("Rising demand against short stock with margin room — price can firm up.")
    elif dt == DEMAND_FALLING and inv == INV_SURPLUS:
        price_bias = PRICE_LOWER
        rationale.append("Soft demand on surplus stock — a lower price clears inventory.")
    else:
        price_bias = PRICE_HOLD

    # promotion (recommendation-surface visibility)
    if inv == INV_SURPLUS and dt in (DEMAND_RISING, DEMAND_FALLING):
        promotion_bias = PROMO_BOOST
        rationale.append("Surface it more to work down the surplus.")
    elif dt == DEMAND_RISING and inv == INV_SHORTAGE:
        promotion_bias = PROMO_STEADY
        rationale.append("Don't over-promote what can't ship — restock instead.")
    elif dt == DEMAND_FALLING and inv == INV_SHORTAGE:
        promotion_bias = PROMO_SUPPRESS
        rationale.append("Low demand and low stock — deprioritise until restocked or cleared.")
    else:
        promotion_bias = PROMO_STEADY

    # reorder urgency
    if inv == INV_SHORTAGE and dt == DEMAND_RISING:
        reorder_urgency = REORDER_URGENT
        rationale.append("Short stock into rising demand — reorder is urgent.")
    elif inv == INV_SURPLUS:
        reorder_urgency = REORDER_DEFER
        rationale.append("Surplus on hand — defer any reorder.")
    else:
        reorder_urgency = REORDER_NORMAL

    return SalesResponse(
        discount_action=discount_action, recommended_discount_pct=recommended,
        price_bias=price_bias, promotion_bias=promotion_bias, reorder_urgency=reorder_urgency,
        rationale=rationale,
        situation={"demand_trend": dt, "inventory_position": inv, "margin_headroom": margin,
                   "max_discount_pct": ceiling, "demand_confidence": round(float(situation.demand_confidence or 0.0), 3)},
    )


def promotion_biases(demand_trend: str, inventory_by_sku: Dict[str, str], *,
                     margin_headroom: str = MARGIN_HEALTHY) -> Dict[str, str]:
    """Per-item promotion_bias (boost | steady | suppress) from the SHARED demand trend + each item's
    inventory position — the M5 ranking consumer. Runs the same decide() matrix per item, so the ranking
    nudge and the margin panel stay consistent. Opaque sku + enum inputs (vertical-blind); pure. Items whose
    bias is 'steady' are still returned (the caller can skip them). Empty input → {}."""
    out: Dict[str, str] = {}
    for sku, inv in (inventory_by_sku or {}).items():
        if not sku:
            continue
        out[str(sku)] = decide(SalesSituation(demand_trend=demand_trend, inventory_position=str(inv),
                                              margin_headroom=margin_headroom)).promotion_bias
    return out


def assess_sales_response(*, demand_findings: Optional[List[Any]] = None,
                          availability: Optional[Dict[str, Any]] = None,
                          economics: Optional[Any] = None,
                          demand_units: Optional[int] = None) -> SalesResponse:
    """End-to-end: classify the three axes from the existing detector/agent/economics outputs, then decide.
    Every input is optional and defaults to the neutral axis — a fully-unknown situation yields a safe
    'hold everything' response, never a fabricated move."""
    trend, conf = classify_demand_trend(demand_findings)
    inv = classify_inventory_position(availability, demand_units=demand_units)
    margin, max_pct = classify_margin_headroom(economics)
    return decide(SalesSituation(demand_trend=trend, inventory_position=inv, margin_headroom=margin,
                                 max_discount_pct=max_pct, demand_confidence=conf))


# ── small tolerant coercions (keep this off the silent-except ratchet) ────────
def _attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: Optional[int]) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default
