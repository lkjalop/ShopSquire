"""Sell engine (rung A) — margin verdict + a PROPOSED buyer discount that keeps a buffer above the floor.

The advisor computes and proposes; it never commits (no send, no price applied). Tests pin the verdict
boundaries and the buffered-discount math by stubbing economics.from_case (proven by test_economics)."""
from __future__ import annotations

from src.app.services.fulfillment import economics as feco
from src.app.services.fulfillment import margin_advisor as ma


def _econ(cost_unit, retail_unit, qty, floor=0.10):
    out = feco.compute(supplier_unit_cost_cents=cost_unit, retail_unit_cents=retail_unit,
                       quantity=qty, floor_margin_pct=floor).to_dict()
    out.update({"cost_basis": "validated_landed_supplier_quote",
                "discount_headroom_authorized": True})
    return out


def test_healthy_margin_proposes_a_buffered_discount(monkeypatch):
    # retail 1000c/unit, cost 500c/unit, qty 10 → margin 50% (healthy). Floor 10%, buffer 5% → keep 15%.
    monkeypatch.setattr(feco, "from_case", lambda db, cid, **k: _econ(500, 1000, 10))
    monkeypatch.setattr(ma, "_supplier_last_invoice_cents", lambda db, cid, t: 4800)
    monkeypatch.setattr(ma, "_case_price_breaks", lambda db, cid, t: [
        {"min_qty": 25, "discount_pct": 5},
    ])
    out = ma.assess(None, "c1")
    assert out["available"] is True and out["verdict"] == "healthy"
    # min retail to keep 15% margin = 5000/0.85 = 5882 → discount = 10000-5882 = 4118, under the hard ceiling
    assert out["recommended_buyer_discount_cents"] == 4118
    assert out["recommended_buyer_discount_cents"] <= out["max_buyer_discount_cents"]
    assert out["supplier_last_invoice_cents"] == 4800
    assert any("offer up to" in r for r in out["rationale"])
    projection = out["deal_projection"]
    assert projection["margin_pct"] == 0.5
    assert projection["projected_profit_cents"] == 5000
    assert projection["discount_authorized"] is True
    assert projection["bulk_breaks"] == [{
        "min_qty": 25,
        "discount_pct": 5.0,
        "estimated_supplier_unit_cents": 475,
        "margin_pct": 0.525,
        "projected_profit_cents_at_min_qty": 13125,
        "pricing_authorized": False,
    }]


def test_below_floor_flags_not_worth_it_and_proposes_no_discount(monkeypatch):
    # retail 1000, cost 950, qty 1 → margin 5% < floor 10% → below_floor, no discount headroom
    monkeypatch.setattr(feco, "from_case", lambda db, cid, **k: _econ(950, 1000, 1))
    monkeypatch.setattr(ma, "_supplier_last_invoice_cents", lambda db, cid, t: None)
    out = ma.assess(None, "c1")
    assert out["verdict"] == "below_floor"
    assert out["recommended_buyer_discount_cents"] == 0
    assert any("BELOW the floor" in r for r in out["rationale"])


def test_thin_margin_is_distinguished_from_healthy(monkeypatch):
    # retail 1000, cost 870, qty 1 → margin 13% — above floor 10% but within the 5% buffer → "thin"
    monkeypatch.setattr(feco, "from_case", lambda db, cid, **k: _econ(870, 1000, 1))
    monkeypatch.setattr(ma, "_supplier_last_invoice_cents", lambda db, cid, t: None)
    out = ma.assess(None, "c1")
    assert out["verdict"] == "thin"


def test_insufficient_data_is_unavailable(monkeypatch):
    monkeypatch.setattr(feco, "from_case", lambda db, cid, **k: {})
    out = ma.assess(None, "c1")
    assert out["available"] is False and out["verdict"] is None


def test_unlanded_quote_never_exposes_discount_headroom(monkeypatch):
    econ = _econ(500, 1000, 10)
    econ.update({"cost_basis": "validated_supplier_quote_unlanded",
                 "discount_headroom_authorized": False})
    monkeypatch.setattr(feco, "from_case", lambda db, cid, **k: econ)
    monkeypatch.setattr(ma, "_supplier_last_invoice_cents", lambda db, cid, t: None)
    monkeypatch.setattr(ma, "_case_price_breaks", lambda db, cid, t: [])

    out = ma.assess(None, "c1")

    assert out["available"] is True
    assert out["discount_headroom_authorized"] is False
    assert out["max_buyer_discount_cents"] == 0
    assert out["recommended_buyer_discount_cents"] == 0
    assert out["deal_projection"]["max_discount_cents"] == 0
    assert out["deal_projection"]["discount_authorized"] is False
    assert any("landed unit cost" in reason for reason in out["rationale"])
