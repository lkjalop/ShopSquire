"""Second-vertical proof: the agnostic upsell path serves PHARMACY without laptop logic.

This is the characterization test that makes "core is agnostic" verifiable rather than asserted.
With the pharmacy StoreProfile active, the product-type-keyed companion path
(upsell_engine._companion_type_candidates → product_classifier.companion_types_for → profile
`upsell_companions`) must surface pharmacy companions (first_aid / device for a medicine) and must
NEVER surface an electronics companion. The same core code, a different profile.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from src.app.models.db import db_session


def _pharmacy_profile() -> dict:
    return json.loads(Path("config/store_profiles/pharmacy.json").read_text(encoding="utf-8"))


@pytest.fixture
def pharmacy_active(monkeypatch):
    """Activate the pharmacy profile for the classifier/upsell vocab (no active-profile env exists
    yet — _vocab() calls get_store_profile() no-arg → electronics; so we patch it)."""
    import src.app.platform.store_profile as sp
    import src.app.services.product_classifier as pc

    prof = _pharmacy_profile()
    monkeypatch.setattr(sp, "get_store_profile", lambda *a, **k: prof)
    pc.reset_cache()
    yield
    pc.reset_cache()


def _seed(db, sku: str, name: str, stock: int = 9):
    db.execute(
        text(
            "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
            "VALUES (:id,:sku,:name,1999,'USD','{}',1)"
        ),
        {"id": f"p-{sku}", "sku": sku, "name": name},
    )
    db.execute(
        text(
            "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) "
            "VALUES (:id,:pid,:stock,'default')"
        ),
        {"id": f"inv-{sku}", "pid": f"p-{sku}", "stock": stock},
    )


def test_profile_swaps_companion_vocab(pharmacy_active):
    """Same core, different vocab: under pharmacy, medicine→{first_aid,device} and laptop is unknown."""
    from src.app.services.product_classifier import classify_product_type, companion_types_for

    assert classify_product_type("Paracetamol 500mg Tablets") == "medicine"
    assert classify_product_type("Bandage Pack") == "first_aid"
    assert classify_product_type("Digital Thermometer") == "device"
    assert set(companion_types_for("medicine")) == {"first_aid", "device"}
    # a laptop is not a recognised pharmacy type, and has no pharmacy companions
    assert companion_types_for("laptop") == []


def test_pharmacy_medicine_surfaces_pharmacy_companions_not_laptop(pharmacy_active):
    with db_session() as db:
        _seed(db, "PH-MED-1", "Paracetamol 500mg Tablets")
        _seed(db, "PH-FA-1", "Bandage Pack")
        _seed(db, "PH-DEV-1", "Digital Thermometer")
        _seed(db, "PH-LAP-1", "Gaming Laptop RTX 4060")  # must NOT surface as a medicine companion
        db.commit()

    from src.app.services.upsell_engine import get_upsell_candidates

    out = get_upsell_candidates("PH-MED-1", cart_skus=[], session_query="need pain relief", max_results=5)
    skus = {p["sku"] for p in out}

    assert ("PH-FA-1" in skus) or ("PH-DEV-1" in skus), f"expected a pharmacy companion, got {skus}"
    assert "PH-LAP-1" not in skus, "a laptop leaked as a pharmacy companion — core is not agnostic"
