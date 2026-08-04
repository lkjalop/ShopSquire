"""checkout_upsell flavour is StoreProfile-backed (agnostic core, electronics fallback).

The four upsell flavour pieces (cart crossover, persona->accessory slugs, intent-family
keywords, family complement matrix) now PREFER the active StoreProfile slot and fall back to
the electronics table. These tests prove both directions: a non-electronics vertical overrides
via its profile slot, and electronics behavior is unchanged when no slot is present.
"""
from __future__ import annotations

import src.app.services.checkout_upsell as cu
import src.app.platform.store_profile as sp


def _no_slots(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot", lambda slot, **k: None)


def test_crossover_falls_back_to_electronics(monkeypatch):
    _no_slots(monkeypatch)
    assert cu._cart_crossover_cents() == cu._ADAPTIVE_CART_CROSSOVER_CENTS


def test_crossover_prefers_profile_slot(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot",
                        lambda slot, **k: 5000 if slot == "cart_crossover_cents" else None)
    assert cu._cart_crossover_cents() == 5000
    # And the guard uses it: a $40 cart (<= $50 crossover) is now in the relaxed branch.
    assert cu._passes_price_guard(7000, 4000) is True   # 70 <= 40*1.9
    assert cu._passes_price_guard(9000, 4000) is False  # 90 > 40*1.9


def test_persona_slugs_prefer_profile_and_normalize_lists(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot",
                        lambda slot, **k: {"shopper": ["scarf", "Belt"]} if slot == "persona_accessory_slugs" else None)
    assert cu._persona_accessory_slugs() == {"shopper": {"scarf", "belt"}}
    assert cu._persona_accessory_boost("shopper", "belt") == 1.0
    assert cu._persona_accessory_boost("gamer", "headset") == 0.0  # electronics persona not in profile


def test_intent_family_prefers_profile(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot",
                        lambda slot, **k: {"MED": ["aspirin", "vitamin"]} if slot == "intent_family_keywords" else None)
    assert cu._infer_intent_family("need aspirin today", None, None) == "MED"
    assert cu._infer_intent_family("gaming laptop", None, None) is None  # electronics keyword not in profile


def test_family_matrix_prefers_profile(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot",
                        lambda slot, **k: {"MED": {"MED": 1.0, "VIT": 0.5}} if slot == "family_complement_matrix" else None)
    assert cu._family_complement_weight("MED", "VIT") == 0.5
    assert cu._family_complement_weight("MED", "MED") == 1.0
    assert cu._family_complement_weight("LAP", "PERIPH") == 0.0  # electronics row not in profile


def test_electronics_fallbacks_unchanged(monkeypatch):
    _no_slots(monkeypatch)
    assert cu._infer_intent_family("gaming laptop", None, None) == "LAP"
    assert cu._infer_intent_family("buy a dress", None, None) == "FSH"
    assert cu._persona_accessory_boost("gamer", "headset") == 1.0
    assert cu._family_complement_weight("LAP", "PERIPH") == 0.95
    assert cu._cart_crossover_cents() == 20000
