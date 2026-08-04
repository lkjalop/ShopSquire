"""Anti-drift guard: the rerank scorer (_use_case_score) and the fast-path adapter (use_case_fit) must
read their spec-floor thresholds from the SAME profile source, so a profile change moves BOTH paths.

Locks the consolidation from #5: _use_case_score's gaming refresh + content/dev RAM thresholds are no
longer hardcoded — they come from profile use_cases[...].spec_floors via _profile_spec_floor (with the
profile use-case-name alias). The AI 32GB bonus tier is deliberately ABOVE the meets-floor and stays.
"""
from __future__ import annotations

import os

os.environ.setdefault("STORE_PROFILE_ID", "electronics")

from src.app.platform.store_profile import profile_slot  # noqa: E402
from src.app.services.recommendations import RecommendationService  # noqa: E402


def _svc() -> RecommendationService:
    return RecommendationService.__new__(RecommendationService)


def _floor(uc, key):
    pk = RecommendationService._PROFILE_USE_CASE_ALIAS.get(uc, uc)
    ucs = profile_slot("use_cases", default={}) or {}
    return ((ucs.get(pk) or {}).get("spec_floors") or {}).get(key)


def test_gaming_refresh_threshold_tracks_profile():
    svc = _svc()
    floor = _floor("gaming", "refresh_hz_min")
    assert floor is not None
    assert svc._profile_spec_floor("gaming", "refresh_hz_min", 999) == int(floor)
    # the boost fires at exactly the profile floor, and not one Hz below it
    at = svc._use_case_score("gaming", {"gpu_discrete": True, "text": f"{int(floor)}hz gaming laptop"}, None)
    below = svc._use_case_score("gaming", {"gpu_discrete": True, "text": f"{int(floor) - 1}hz gaming laptop"}, None)
    assert "use_case_144hz" in at[1]
    assert "use_case_144hz" not in below[1]


def test_content_and_dev_ram_thresholds_track_profile():
    svc = _svc()
    for uc in ("content_creation", "software_development"):
        floor = _floor(uc, "ram_gb_min")
        assert floor is not None, f"{uc} should have a profile ram floor"
        assert svc._profile_spec_floor(uc, "ram_gb_min", 999) == int(floor)


def test_alias_maps_legacy_names_to_profile_keys():
    # the rerank taxonomy differs from the profile's; the alias map bridges them to ONE source.
    svc = _svc()
    assert svc._PROFILE_USE_CASE_ALIAS["content_creation"] == "video_editing"
    assert svc._PROFILE_USE_CASE_ALIAS["software_development"] == "programming"
    assert svc._PROFILE_USE_CASE_ALIAS["ai_ml_workstation"] == "ml_ai"


def test_unknown_floor_falls_back_to_default():
    svc = _svc()
    assert svc._profile_spec_floor("nonexistent_use_case", "ram_gb_min", 24) == 24
