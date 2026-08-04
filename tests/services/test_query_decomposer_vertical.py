"""query_decomposer use-case detection is PER-REQUEST profile-scoped — no electronics bleed.

Surfaces (and guards against) the wiring bug where _USE_CASE_PATTERNS was frozen at import to the
electronics default, so a pharmacy/fashion request was scored against gaming/GPU use-cases. The
decision path now resolves the ACTIVE vertical's patterns per request.
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import query_decomposer as qd
from src.app.services.query_decomposer import decompose


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    qd.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        qd.reset_cache()


def test_electronics_detects_gaming():
    with _vertical("electronics"):
        assert "gaming" in decompose("gaming laptop for valorant under 1800").use_cases


def test_pharmacy_detects_pharmacy_use_case_not_electronics():
    with _vertical("pharmacy"):
        p = decompose("something for my headache and body pain")
        assert "pain_relief" in p.use_cases
        # electronics use-cases must NOT appear under the pharmacy profile
        assert "gaming" not in p.use_cases and "video_editing" not in p.use_cases
        # an electronics-flavoured query under pharmacy yields NO electronics use-case (no bleed)
        assert "gaming" not in decompose("gaming laptop rtx 4070").use_cases


def test_fashion_detects_fashion_use_case_not_electronics():
    with _vertical("fashion"):
        p = decompose("formal outfit for a wedding")
        assert "formal" in p.use_cases
        assert "gaming" not in p.use_cases
        # "office" under fashion means formal attire — fashion's pattern, not electronics' office
        assert "office" not in decompose("office wear").use_cases


def test_dgpu_flag_is_profile_scoped():
    # dedicated-GPU is an electronics concept; a non-electronics vertical must never set it.
    with _vertical("pharmacy"):
        assert decompose("vitamins for energy").needs_dedicated_gpu is False
        assert decompose("gaming laptop").needs_dedicated_gpu is False
