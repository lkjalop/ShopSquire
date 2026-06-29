"""WS-1 — per-(supplier, SKU) commercial terms: the seed populates MOQ / region / lead-time / price-breaks
on supplier_products, supplier_terms merges per-SKU over supplier defaults, and price_break_advisory nudges
the next volume tier. Vertical-blind (qty / cents / %)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.supplier_catalog import price_break_advisory, seed_demo, supplier_terms


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_seed_populates_per_sku_terms_and_supplier_terms_merges(db):
    seed_demo(db, skus=["LAP-X"])
    t = supplier_terms(db, "SUP-3", "LAP-X")
    assert t["moq"] == 5 and t["region"] == "AU" and t["lead_time_days"] == 12
    assert t["contract_status"] == "spot" and t["min_order_value_cents"] == 500000
    assert any(b["min_qty"] == 50 and b["discount_pct"] == 15 for b in t["price_breaks"])


def test_price_break_advisory_points_at_next_tier(db):
    seed_demo(db, skus=["LAP-X"])
    t = supplier_terms(db, "SUP-7", "LAP-X")  # breaks at 25 (5%) and 50 (10%)
    assert "25+" in price_break_advisory(10, t) and "5% off" in price_break_advisory(10, t)
    assert "50+" in price_break_advisory(30, t)            # past 25 → next is 50
    assert price_break_advisory(60, t) is None             # above the top tier → no nudge


def test_supplier_terms_empty_when_unknown(db):
    seed_demo(db, skus=["LAP-X"])
    assert supplier_terms(db, "SUP-NONE", "LAP-X").get("moq") is None
    assert price_break_advisory(5, {}) is None
