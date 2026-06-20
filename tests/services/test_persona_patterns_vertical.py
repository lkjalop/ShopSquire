"""Buyer-persona detection is PER-REQUEST profile-scoped — Phase 2A P0.

recommend_persona's detection algorithm is vertical-blind; the persona keyword patterns live in
each StoreProfile's `persona_patterns` slot. Electronics keeps its exact personas; fashion and
pharmacy detect THEIR personas (athlete/professional/patient/wellness...), and an electronics
query under a non-electronics tenant detects NO persona (no gamer/developer bleed).
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import recommend_persona as rp


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    rp.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        rp.reset_cache()


def test_electronics_personas():
    with _vertical("electronics"):
        assert rp.detect_buyer_persona("gaming laptop for valorant") == "gamer"
        assert rp.detect_buyer_persona("university student assignments") == "student"
        assert rp.detect_buyer_persona("ai engineer pytorch cuda") == "developer"


def test_fashion_detects_its_personas_no_electronics_bleed():
    with _vertical("fashion"):
        assert rp.detect_buyer_persona("gym workout running shoes") == "athlete"
        assert rp.detect_buyer_persona("formal outfit for a wedding") == "professional"
        # electronics personas must not leak into a fashion tenant
        assert rp.detect_buyer_persona("gaming laptop valorant cuda pytorch") is None


def test_pharmacy_detects_its_personas_no_electronics_bleed():
    with _vertical("pharmacy"):
        assert rp.detect_buyer_persona("something for my headache and fever") == "patient"
        assert rp.detect_buyer_persona("vitamins for energy and immune support") == "wellness"
        assert rp.detect_buyer_persona("baby formula and nappies") == "parent"
        assert rp.detect_buyer_persona("gaming laptop developer pytorch") is None


def test_backcompat_constant_is_electronics():
    # recommend.py aliases PERSONA_PATTERNS — it must stay the electronics default set.
    assert set(rp.PERSONA_PATTERNS.keys()) == {
        "student", "high_schooler", "corporate", "job_hunter", "gamer",
        "creative", "developer", "engineer_student", "traveler",
    }
