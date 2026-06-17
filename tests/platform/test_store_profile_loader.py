"""StoreProfile loader (R1) — the first enforceable core/adapter cut.

Characterization: the profile-backed brand price floors must EQUAL the values that were
inline in recommend.py before excision (parity). Plus loader behaviour + cache reset.
"""
from __future__ import annotations

import pytest

from src.app.platform.store_profile import (
    get_store_profile,
    profile_slot,
    brand_price_floors,
    reset_cache,
)

# The exact values excised from recommend.py _BRAND_PRICE_FLOORS — the parity baseline.
_EXCISED_FLOORS = {
    "apple": 1200, "msi": 900, "razer": 1200, "gigabyte": 1000, "lenovo": 500,
    "dell": 500, "hp": 400, "asus": 400, "acer": 350, "microsoft": 900, "samsung": 800,
}


def test_electronics_profile_loads():
    p = get_store_profile("electronics")
    assert p.get("id") == "electronics"
    assert "brand_price_floors_usd" in p


def test_brand_price_floors_match_excised_values():
    # CHARACTERIZATION: profile-backed floors are byte-identical to the inline dict.
    assert brand_price_floors("electronics") == _EXCISED_FLOORS


def test_unknown_profile_falls_back_to_electronics():
    p = get_store_profile("does_not_exist_zzz")
    assert p.get("id") == "electronics"  # graceful fallback, never empty


def test_profile_slot_default():
    assert profile_slot("nope_slot", default="x") == "x"
    assert isinstance(profile_slot("known_brands", default=[]), list)


def test_reset_cache_is_callable_and_safe():
    get_store_profile("electronics")
    reset_cache()  # must not raise; clears the lru_cache (determinism fixture calls this)
    assert get_store_profile("electronics").get("id") == "electronics"


def test_strict_mode_raises_on_missing_dir(monkeypatch):
    monkeypatch.setenv("STORE_PROFILE_STRICT", "1")
    monkeypatch.setenv("STORE_PROFILES_DIR", "config/__no_such_dir__")
    reset_cache()
    with pytest.raises(Exception):
        get_store_profile("electronics")
    reset_cache()


def test_strict_mode_fails_closed_on_missing_named_profile(monkeypatch):
    # P0 fix: a typo'd / unknown tenant profile must NOT silently become electronics in
    # strict mode — it must fail closed so pharmacy can't be routed through laptop rules.
    monkeypatch.setenv("STORE_PROFILE_STRICT", "1")
    reset_cache()
    with pytest.raises(FileNotFoundError):
        get_store_profile("pharmacy_typo_zzz")
    reset_cache()


def test_strict_mode_loads_existing_profile(monkeypatch):
    # Fail-closed must not break the happy path: a real profile still loads under strict.
    monkeypatch.setenv("STORE_PROFILE_STRICT", "1")
    reset_cache()
    assert get_store_profile("pharmacy").get("id") == "pharmacy"
    assert get_store_profile("electronics").get("id") == "electronics"
    reset_cache()


def test_nonstrict_still_falls_back_on_missing_named_profile(monkeypatch):
    # Dev/test convenience preserved: without strict, unknown profile falls back to electronics.
    monkeypatch.setenv("STORE_PROFILE_STRICT", "0")
    reset_cache()
    assert get_store_profile("pharmacy_typo_zzz").get("id") == "electronics"
    reset_cache()
