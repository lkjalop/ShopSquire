"""sales_response_policy — the demand→sales responsiveness matrix (agnostic CORE, pure + explainable)."""
from __future__ import annotations

from src.app.services import sales_response_policy as srp
from src.app.services.sales_response_policy import SalesSituation


# ── classifiers ───────────────────────────────────────────────────────────────
def test_classify_demand_trend_reads_direction_and_picks_strongest():
    findings = [
        {"finding_type": "demand_shift", "severity": "warn", "confidence": 0.6, "evidence": {"direction": "slowdown"}},
        {"finding_type": "demand_shift", "severity": "critical", "confidence": 0.8, "evidence": {"direction": "spike"}},
    ]
    trend, conf = srp.classify_demand_trend(findings)
    assert trend == srp.DEMAND_RISING and conf == 0.8   # critical spike outweighs the warn slowdown
    assert srp.classify_demand_trend([])[0] == srp.DEMAND_STEADY
    assert srp.classify_demand_trend([{"finding_type": "conversion_anomaly"}])[0] == srp.DEMAND_STEADY


def test_classify_inventory_position():
    assert srp.classify_inventory_position({"shortfall": 40, "in_stock": 10}) == srp.INV_SHORTAGE
    assert srp.classify_inventory_position({"shortfall": 0, "in_stock": 300, "requested_qty": 20}) == srp.INV_SURPLUS
    assert srp.classify_inventory_position({"shortfall": 0, "in_stock": 25, "requested_qty": 20}) == srp.INV_BALANCED
    assert srp.classify_inventory_position(None) == srp.INV_BALANCED   # unknown → neutral


def test_classify_margin_headroom_thresholds_and_floor():
    assert srp.classify_margin_headroom({"max_buyer_discount_pct": 0.30, "clears_floor": True})[0] == srp.MARGIN_GENEROUS
    assert srp.classify_margin_headroom({"max_buyer_discount_pct": 0.10, "clears_floor": True})[0] == srp.MARGIN_HEALTHY
    assert srp.classify_margin_headroom({"max_buyer_discount_pct": 0.02, "clears_floor": True})[0] == srp.MARGIN_THIN
    # below the floor → thin with ZERO room, regardless of the raw pct
    tier, room = srp.classify_margin_headroom({"max_buyer_discount_pct": 0.4, "clears_floor": False})
    assert tier == srp.MARGIN_THIN and room == 0.0
    assert srp.classify_margin_headroom(None) == (srp.MARGIN_THIN, 0.0)


# ── the decision matrix ───────────────────────────────────────────────────────
def test_rising_demand_short_stock_protects_margin_and_reorders():
    r = srp.decide(SalesSituation(srp.DEMAND_RISING, srp.INV_SHORTAGE, srp.MARGIN_HEALTHY, max_discount_pct=0.15))
    assert r.discount_action == srp.DISCOUNT_REDUCE and r.recommended_discount_pct == 0.0
    assert r.price_bias == srp.PRICE_RAISE          # rising + short + margin room → price can firm
    assert r.reorder_urgency == srp.REORDER_URGENT
    assert r.promotion_bias == srp.PROMO_STEADY     # don't over-promote what can't ship
    assert r.rationale                              # explainable


def test_falling_demand_surplus_generous_margin_discounts_to_clear():
    r = srp.decide(SalesSituation(srp.DEMAND_FALLING, srp.INV_SURPLUS, srp.MARGIN_GENEROUS, max_discount_pct=0.30))
    assert r.discount_action == srp.DISCOUNT_INCREASE
    assert r.recommended_discount_pct == 0.15       # deep target (pressure +2), within the 0.30 ceiling
    assert r.price_bias == srp.PRICE_LOWER and r.promotion_bias == srp.PROMO_BOOST
    assert r.reorder_urgency == srp.REORDER_DEFER


def test_margin_is_a_hard_clamp_never_below_floor():
    # policy WANTS a deep discount (falling+surplus) but margin only allows 6% → recommend 6%, not 15%
    r = srp.decide(SalesSituation(srp.DEMAND_FALLING, srp.INV_SURPLUS, srp.MARGIN_HEALTHY, max_discount_pct=0.06))
    assert r.discount_action == srp.DISCOUNT_INCREASE and r.recommended_discount_pct == 0.06
    assert any("capped" in s.lower() for s in r.rationale)


def test_thin_margin_clears_via_visibility_not_price_cuts():
    r = srp.decide(SalesSituation(srp.DEMAND_FALLING, srp.INV_SURPLUS, srp.MARGIN_THIN, max_discount_pct=0.0))
    assert r.discount_action == srp.DISCOUNT_INCREASE and r.recommended_discount_pct == 0.0
    assert r.promotion_bias == srp.PROMO_BOOST      # still surface it, just don't cut price below the floor
    assert any("thin" in s.lower() or "visibility" in s.lower() for s in r.rationale)


def test_neutral_situation_holds_everything():
    r = srp.decide(SalesSituation())   # steady / balanced / healthy defaults
    assert r.discount_action == srp.DISCOUNT_HOLD and r.recommended_discount_pct == 0.0
    assert r.price_bias == srp.PRICE_HOLD and r.reorder_urgency == srp.REORDER_NORMAL
    assert r.messaging_emphasis == srp.EMPHASIS_FEATURES   # neutral → features copy


def test_storefront_messaging_emphasis():
    # surplus → VALUE (clear it); rising demand we can ship → URGENCY; can't-ship shortage → neutral FEATURES
    assert srp.decide(SalesSituation(srp.DEMAND_FALLING, srp.INV_SURPLUS)).messaging_emphasis == srp.EMPHASIS_VALUE
    assert srp.decide(SalesSituation(srp.DEMAND_RISING, srp.INV_BALANCED)).messaging_emphasis == srp.EMPHASIS_URGENCY
    assert srp.decide(SalesSituation(srp.DEMAND_RISING, srp.INV_SHORTAGE)).messaging_emphasis == srp.EMPHASIS_FEATURES


def test_recommended_discount_never_exceeds_ceiling_property():
    # exhaustive over the matrix: the recommended discount is ALWAYS ≤ the margin ceiling
    for dt in (srp.DEMAND_RISING, srp.DEMAND_STEADY, srp.DEMAND_FALLING):
        for inv in (srp.INV_SHORTAGE, srp.INV_BALANCED, srp.INV_SURPLUS):
            for mh in (srp.MARGIN_THIN, srp.MARGIN_HEALTHY, srp.MARGIN_GENEROUS):
                for ceiling in (0.0, 0.03, 0.10, 0.25):
                    r = srp.decide(SalesSituation(dt, inv, mh, max_discount_pct=ceiling))
                    assert r.recommended_discount_pct <= ceiling + 1e-9


# ── end-to-end assembler ──────────────────────────────────────────────────────
def test_assess_sales_response_end_to_end():
    findings = [{"finding_type": "demand_shift", "severity": "critical", "confidence": 0.9,
                 "evidence": {"direction": "slowdown"}}]
    availability = {"shortfall": 0, "in_stock": 300, "requested_qty": 20}   # surplus
    economics = {"max_buyer_discount_pct": 0.22, "clears_floor": True}       # generous
    r = srp.assess_sales_response(demand_findings=findings, availability=availability, economics=economics)
    assert r.discount_action == srp.DISCOUNT_INCREASE and r.recommended_discount_pct == 0.15
    assert r.reorder_urgency == srp.REORDER_DEFER and r.price_bias == srp.PRICE_LOWER
    d = r.as_dict()
    assert d["situation"]["demand_trend"] == srp.DEMAND_FALLING and d["situation"]["inventory_position"] == srp.INV_SURPLUS


def test_assess_all_unknown_is_a_safe_hold():
    r = srp.assess_sales_response()   # nothing known
    assert r.discount_action == srp.DISCOUNT_HOLD and r.recommended_discount_pct == 0.0
    assert r.price_bias == srp.PRICE_HOLD


# ── M5 consume #2: per-item promotion_biases for the ranking nudge ────────────
def test_promotion_biases_per_item_from_shared_demand():
    inv = {"A": srp.INV_SURPLUS, "B": srp.INV_SHORTAGE, "C": srp.INV_BALANCED}
    # falling demand: surplus → boost (clear it); shortage → suppress; balanced → steady
    b = srp.promotion_biases(srp.DEMAND_FALLING, inv)
    assert b == {"A": srp.PROMO_BOOST, "B": srp.PROMO_SUPPRESS, "C": srp.PROMO_STEADY}
    # rising demand: surplus still boosts (hot), a shortage is steady (don't over-promote what can't ship)
    b2 = srp.promotion_biases(srp.DEMAND_RISING, inv)
    assert b2["A"] == srp.PROMO_BOOST and b2["B"] == srp.PROMO_STEADY
    assert srp.promotion_biases(srp.DEMAND_STEADY, {}) == {}
