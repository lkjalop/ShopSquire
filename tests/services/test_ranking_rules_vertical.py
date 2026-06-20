"""Use-case ranking is PER-REQUEST profile-scoped — Phase 2A (ranking half).

recommend_ranking.use_case_rank_adjustment uses the active profile's `ranking_rules` table when
present (generic evaluator over metrics from spec_extraction_rules), else the electronics inline
scorer (byte-identical). The second vertical now ranks in ITS vocabulary (breathable/formal/
non_drowsy…) with human-readable reasons, and an electronics use-case under a non-electronics
tenant scores 0 (its rules simply don't match) — no laptop ranking bleed.
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import recommend_ranking as rr
from src.app.services import recommend_utils as ru


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    rr.reset_cache()
    ru.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        rr.reset_cache()
        ru.reset_cache()


def _adj(candidate, uc, q="x"):
    return rr.use_case_rank_adjustment(candidate, use_case_key=uc, query=q)


def test_electronics_inline_ranking_still_works():
    with _vertical("electronics"):
        score, plus, minus = _adj({"name": "Gaming ROG RTX 4070", "specs": {"ram_gb": 16, "gpu": "RTX 4070", "refresh_hz": 144}}, "gaming_casual")
        assert score > 0 and any("GPU" in p or "gaming" in p.lower() or "refresh" in p.lower() for p in plus)


def test_fashion_ranks_in_its_vocabulary():
    with _vertical("fashion"):
        s_breath, plus, _ = _adj({"name": "Linen Breathable Shirt", "specs": {}}, "summer")
        assert s_breath > 0 and any("breathable" in p for p in plus)
        s_warm, _, minus = _adj({"name": "Merino Wool Puffer", "specs": {}}, "summer")
        assert s_warm < 0 and any("warm" in m for m in minus)
        s_formal, plusf, _ = _adj({"name": "Tailored Blazer Suit", "specs": {}}, "formal")
        assert s_formal > 0 and any("formal" in p for p in plusf)


def test_pharmacy_ranks_in_its_vocabulary():
    with _vertical("pharmacy"):
        s, plus, _ = _adj({"name": "Antihistamine non-drowsy fast acting", "specs": {}}, "cold_flu")
        assert s > 0 and any("non-drowsy" in p for p in plus)
        s2, plus2, _ = _adj({"name": "Ibuprofen fast acting", "specs": {"strength_mg": 400}}, "pain_relief")
        assert s2 > 0 and any("strength" in p for p in plus2)


def test_no_electronics_ranking_bleed():
    # an electronics use-case under a non-electronics tenant matches no rule -> neutral 0
    with _vertical("fashion"):
        assert _adj({"name": "Whatever", "specs": {}}, "gaming_casual") == (0.0, [], [])
    with _vertical("pharmacy"):
        assert _adj({"name": "Whatever", "specs": {}}, "ai_ml_workstation") == (0.0, [], [])
