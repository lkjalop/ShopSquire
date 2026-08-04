"""Split-fulfillment planner — ship-now + backorder-later with the SUPPLIER's real ETA, agnostic delivery."""
from src.app.services.fulfillment.fulfillment_split import (
    DeliveryPolicy, SplitLine, compute_split, delivery_policy_from_profile)

_POL = DeliveryPolicy(base_fee_cents=1500, split_shipment_fee_cents=900,
                      free_shipping_threshold_cents=500000, backorder_enabled=True)


def test_fully_in_stock_is_one_shipment_no_split_fee():
    plan = compute_split([SplitLine("LAP-1", requested_qty=5, in_stock=10, unit_cents=1_59900)], policy=_POL)
    # subtotal 5*1599 = 7995.00 >= 5000 threshold → free shipping
    assert plan.fully_in_stock is True and plan.later == []
    assert plan.delivery["shipments"] == 1 and plan.delivery["waived"] is True


def test_partial_splits_now_and_later_with_supplier_eta():
    line = SplitLine("LAP-1", requested_qty=25, in_stock=12, unit_cents=170000,
                     supplier_lead_time_days=7, supplier_ref="SUP-BIZ")
    plan = compute_split([line], policy=DeliveryPolicy(free_shipping_threshold_cents=0))  # no free shipping
    assert [x["qty"] for x in plan.now] == [12]                 # 12 in stock ship now
    assert plan.later[0]["qty"] == 13 and plan.later[0]["eta_days"] == 7   # 13 follow in 7 days (real supplier ETA)
    assert plan.later[0]["supplier_ref"] == "SUP-BIZ"
    assert plan.delivery["shipments"] == 2
    assert plan.delivery["fee_now_cents"] == 1500 and plan.delivery["fee_later_cents"] == 900
    assert "~7 days" in plan.rationale and "supplier lead time" in plan.rationale


def test_free_threshold_waives_both_shipment_fees():
    line = SplitLine("LAP-1", requested_qty=25, in_stock=10, unit_cents=170000, supplier_lead_time_days=6)
    plan = compute_split([line], policy=_POL)          # 25*1700 = 42500.00 >= 5000 threshold
    assert plan.delivery["waived"] is True
    assert plan.delivery["fee_now_cents"] == 0 and plan.delivery["fee_later_cents"] == 0


def test_backorder_disabled_never_creates_a_second_shipment():
    line = SplitLine("LAP-1", requested_qty=25, in_stock=10, unit_cents=1000)
    plan = compute_split([line], policy=DeliveryPolicy(backorder_enabled=False, free_shipping_threshold_cents=0))
    # the split still reports the backordered qty, but there is no second shipment/fee (store won't backorder)
    assert plan.later and plan.delivery["shipments"] == 1 and plan.delivery["fee_later_cents"] == 0
    assert "does not backorder" in plan.rationale


def test_multi_line_uses_the_max_supplier_eta_in_the_rationale():
    lines = [
        SplitLine("HDD-1", requested_qty=5, in_stock=1, unit_cents=17000, supplier_lead_time_days=4),
        SplitLine("AUD-1", requested_qty=10, in_stock=3, unit_cents=9000, supplier_lead_time_days=12),
    ]
    plan = compute_split(lines, policy=DeliveryPolicy(free_shipping_threshold_cents=0))
    assert len(plan.later) == 2 and "~12 days" in plan.rationale   # slowest supplier drives the ETA


def test_delivery_policy_reads_the_active_profile_slot():
    pol = delivery_policy_from_profile()   # electronics.json has the slot; falls back to defaults otherwise
    assert isinstance(pol, DeliveryPolicy) and pol.base_fee_cents >= 0
