"""Three-vertical agnostic proof: electronics · pharmacy · fashion — same core, no cross-bleed.

This is the strongest demarcation test: the SAME upsell/classifier core, driven only by which
StoreProfile is active (via the runtime selector — no monkeypatch), produces three different,
correct companion behaviours and NEVER bleeds another vertical's product into the result:

  • electronics: laptop  → bag/audio/storage/... (complete the SETUP)
  • pharmacy:    medicine → first_aid/device     (complete the CARE)
  • fashion:     shoes    → sock/belt            (complete the OUTFIT)

If any vertical's companions leaked another vertical's primary type, the core would not be
agnostic. The runtime selector + per-test reset prove it is also tenant-aware (isolated per
context).
"""
from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import text

from src.app.models.db import db_session


@contextlib.contextmanager
def _vertical(pid: str):
    """Activate a vertical via the REAL selector (ContextVar) + rebuild taxonomy caches."""
    import src.app.platform.store_profile as sp
    import src.app.services.product_classifier as pc

    token = sp.set_active_profile_id(pid)
    pc.reset_cache()
    try:
        yield
    finally:
        sp.reset_active_profile_id(token)
        pc.reset_cache()


# (profile, headline product name → type, headline type, expected companion types, a FOREIGN
# headline that must NOT be recognised as this vertical's type)
_CASES = [
    ("electronics", "ASUS Vivobook S16 Laptop", "laptop", {"bag", "audio", "storage", "monitor", "peripheral", "networking"}, "Paracetamol 500mg Tablets"),
    ("pharmacy",    "Paracetamol 500mg Tablets", "medicine", {"first_aid", "device"}, "ASUS Vivobook S16 Laptop"),
    ("fashion",     "Running Sneakers",           "shoes",   {"sock", "belt"}, "Paracetamol 500mg Tablets"),
]


@pytest.mark.parametrize("pid,name,ptype,companions,foreign", _CASES)
def test_vertical_classifies_and_companions_no_bleed(pid, name, ptype, companions, foreign):
    from src.app.services.product_classifier import classify_product_type, companion_types_for

    with _vertical(pid):
        # headline product classifies to this vertical's primary type
        assert classify_product_type(name) == ptype, f"{pid}: {name!r} should be {ptype}"
        # its companions are a SUBSET of this vertical's declared companion types
        got = set(companion_types_for(ptype))
        assert got and got <= companions, f"{pid}: companions {got} not within {companions}"
        # a FOREIGN vertical's headline is NOT recognised here (→ accessory), so it can't bleed in
        assert classify_product_type(foreign) == "accessory", f"{pid}: {foreign!r} bled in as a known type"


def test_budget_floors_are_profile_scoped_no_bleed():
    """Budget floors are vertical-EXCLUSIVE (prefer-profile): a pharmacy must not inherit the
    electronics gaming floor, and must get its own pharmacy floors."""
    from src.app.services.recommend_budget_advisor import _use_case_budget_floors

    with _vertical("electronics"):
        elec = _use_case_budget_floors()
        assert elec.get("gaming_aaa_heavy") == 1200

    with _vertical("pharmacy"):
        ph = _use_case_budget_floors()
        assert "gaming_aaa_heavy" not in ph, "electronics floor bled into pharmacy"
        assert ph.get("pain_relief") == 5

    with _vertical("fashion"):
        fa = _use_case_budget_floors()
        assert "gaming_aaa_heavy" not in fa
        assert fa.get("formal") == 60


def test_vision_brand_resolution_is_profile_scoped_no_bleed():
    """Vision brand-hint resolution is profile-driven: electronics resolves macbook→apple; pharmacy
    resolves its own brand and does NOT recognise an electronics brand (no bleed)."""
    from src.app.services.recommend_vision_stage import _resolve_supported_brand_hint

    with _vertical("electronics"):
        assert _resolve_supported_brand_hint(None, None, "looking for a macbook") == "apple"
        assert _resolve_supported_brand_hint("asus") == "asus"

    with _vertical("pharmacy"):
        assert _resolve_supported_brand_hint(None, None, "panadol for a headache") == "panadol"
        assert _resolve_supported_brand_hint("asus") == "", "electronics brand bled into pharmacy"
        assert _resolve_supported_brand_hint(None, None, "a macbook") == "", "mac bled into pharmacy"


def _seed(db, sku, name, stock=9):
    db.execute(text(
        "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
        "VALUES (:id,:sku,:name,4999,'USD','{}',1)"
    ), {"id": f"p-{sku}", "sku": sku, "name": name})
    db.execute(text(
        "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) "
        "VALUES (:id,:pid,:stock,'default')"
    ), {"id": f"inv-{sku}", "pid": f"p-{sku}", "stock": stock})


def test_fashion_outfit_mix_and_match_end_to_end():
    """The headline demo: same engine, fashion profile → cart shoes surfaces the rest of the
    outfit (socks/belt) and never an electronics/pharmacy item."""
    with db_session() as db:
        _seed(db, "FA-SHOE-1", "Running Sneakers")
        _seed(db, "FA-SOCK-1", "Ankle Socks 3-Pack")
        _seed(db, "FA-BELT-1", "Leather Belt")
        _seed(db, "FA-JKT-1", "Denim Jacket")
        _seed(db, "FA-LAP-1", "Gaming Laptop RTX 4060")  # foreign — must NOT surface
        db.commit()

    from src.app.services.upsell_engine import get_upsell_candidates

    with _vertical("fashion"):
        out = get_upsell_candidates("FA-SHOE-1", cart_skus=[], session_query="new outfit", max_results=5)
        skus = {p["sku"] for p in out}
        assert ("FA-SOCK-1" in skus) or ("FA-BELT-1" in skus), f"expected outfit companion, got {skus}"
        assert "FA-LAP-1" not in skus, "a laptop leaked into a fashion outfit — core is not agnostic"
