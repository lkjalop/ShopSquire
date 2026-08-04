"""Candidate spec extraction is PER-REQUEST profile-scoped — Phase 2A (spec half).

recommend_utils._extract_candidate_numeric_specs resolves a profile's `spec_extraction_rules`
(numeric: spec_key + ordered regex patterns; flags: token presence) when present, else falls back
to the electronics inline parser (byte-identical). A non-electronics vertical extracts ITS spec
metrics and NONE of the electronics ones (ram_gb/has_dedicated_gpu/gaming_style…) — so ranking
later thinks in the right vocabulary, with no laptop-spec bleed.
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import recommend_utils as ru

_ELECTRONICS_KEYS = {"ram_gb", "storage_gb", "display_inches", "refresh_hz", "gpu_vram_gb",
                     "has_dedicated_gpu", "gaming_style", "portable", "nvidia", "creator_hint", "workstation_hint"}


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    ru.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        ru.reset_cache()


def test_electronics_inline_specs():
    with _vertical("electronics"):
        m = ru._extract_candidate_numeric_specs(
            {"name": "Gaming ROG RTX 4070", "specs": {"ram_gb": 16, "gpu": "RTX 4070", "refresh_hz": 144}}
        )
        assert m["ram_gb"] == 16 and m["has_dedicated_gpu"] is True and m["gaming_style"] is True
        assert m["refresh_hz"] == 144


def test_fashion_specs_no_electronics_bleed():
    with _vertical("fashion"):
        m = ru._extract_candidate_numeric_specs({"name": "Merino Wool Puffer Jacket", "specs": {}})
        assert m["warm"] is True
        m2 = ru._extract_candidate_numeric_specs({"name": "Linen Breathable Summer Shirt", "specs": {}})
        assert m2["breathable"] is True and m2["warm"] is False
        # no electronics metric keys present
        assert not (_ELECTRONICS_KEYS & set(m.keys()))


def test_pharmacy_specs_no_electronics_bleed():
    with _vertical("pharmacy"):
        m = ru._extract_candidate_numeric_specs(
            {"name": "Ibuprofen fast acting", "specs": {"strength_mg": 400, "pack_size": 24}}
        )
        assert m["strength_mg"] == 400.0 and m["pack_size"] == 24.0 and m["fast_acting"] is True
        m2 = ru._extract_candidate_numeric_specs({"name": "Children Paracetamol sugar-free", "specs": {}})
        assert m2["childrens"] is True and m2["sugar_free"] is True
        assert not (_ELECTRONICS_KEYS & set(m.keys()))
