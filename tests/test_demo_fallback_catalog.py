"""demo_fallback_catalog is per-profile — the fast-path fallback never bleeds laptops into other
verticals. Excised from recommend._fast_path_catalog_recommendation (Track-1 agnostic excision)."""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import profile_slot, reset_active_profile_id, set_active_profile_id


@contextlib.contextmanager
def _vertical(pid):
    tok = set_active_profile_id(pid)
    try:
        yield
    finally:
        reset_active_profile_id(tok)


def _fallback(pid):
    with _vertical(pid):
        return profile_slot("demo_fallback_catalog", default=[]) or []


def test_electronics_keeps_its_demo_fallback():
    fb = _fallback("electronics")
    assert len(fb) == 3
    assert any("MSI" in p.get("name", "") for p in fb)
    assert any("Lenovo" in p.get("name", "") for p in fb)


def test_pharmacy_and_fashion_have_no_laptop_fallback():
    for pid in ("pharmacy", "fashion"):
        fb = _fallback(pid)
        assert not any(
            "MSI" in p.get("name", "") or "Lenovo" in p.get("name", "")
            or "RTX" in str(p.get("specs", {}))
            for p in fb
        ), f"{pid} got electronics fallback products (bleed)"
