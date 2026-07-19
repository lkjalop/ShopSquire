"""use_case_advisor use-case matching is PER-REQUEST profile-scoped — no electronics bleed.

Proves that match_use_case_from_query and persona inference resolve from the active
StoreProfile's use_case_keyword_map + use_case_to_persona — so a pharmacy/fashion
request never matches gaming/GPU/laptop use-cases.
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import (
    clear_active_profile_id,
    reset_active_profile_id,
    reset_cache,
    set_active_profile_id,
)
from src.app.services.use_case_advisor import match_use_case_from_query, _get_use_case_to_persona


@contextlib.contextmanager
def _vertical(pid: str):
    reset_cache()
    token = set_active_profile_id(pid)
    try:
        yield
    finally:
        reset_active_profile_id(token)
        reset_cache()


# ── Electronics: existing behavior preserved ──

class TestElectronicsUseCaseMatch:
    def test_gaming_query(self):
        with _vertical("electronics"):
            assert match_use_case_from_query("AAA gaming ultra settings") == "gaming_aaa_heavy"

    def test_game_development_is_not_playing_games(self):
        with _vertical("electronics"):
            assert match_use_case_from_query("25 laptops for gaming development") == "game_development"
            assert match_use_case_from_query("Unity game development workstation") == "game_development"

    def test_medical_student(self):
        with _vertical("electronics"):
            assert match_use_case_from_query("medical student anatomy") == "medical_student"

    def test_office_finance(self):
        with _vertical("electronics"):
            assert match_use_case_from_query("finance and accounting spreadsheets") == "office_finance"

    def test_note_taking(self):
        with _vertical("electronics"):
            assert match_use_case_from_query("note taking with stylus") == "note_taking_student"

    def test_executive(self):
        with _vertical("electronics"):
            assert match_use_case_from_query("executive travel laptop") == "office_executive"

    def test_persona_gamer(self):
        with _vertical("electronics"):
            persona_map = _get_use_case_to_persona()
            assert persona_map.get("gaming_aaa_heavy") == "gamer"
            assert persona_map.get("gaming_competitive") == "gamer"

    def test_persona_student(self):
        with _vertical("electronics"):
            persona_map = _get_use_case_to_persona()
            assert persona_map.get("university_general") == "student"
            assert persona_map.get("engineering_student") == "student"

    def test_persona_game_developer(self):
        with _vertical("electronics"):
            assert _get_use_case_to_persona().get("game_development") == "developer"


# ── Pharmacy: no electronics bleed ──

class TestPharmacyUseCaseMatch:
    def test_pain_relief(self):
        with _vertical("pharmacy"):
            assert match_use_case_from_query("headache and body pain") == "pain_relief"

    def test_cold_flu(self):
        with _vertical("pharmacy"):
            assert match_use_case_from_query("cough and sore throat") == "cold_flu"

    def test_allergy(self):
        with _vertical("pharmacy"):
            assert match_use_case_from_query("hay fever antihistamine") == "allergy"

    def test_vitamins(self):
        with _vertical("pharmacy"):
            assert match_use_case_from_query("vitamin supplement for immune") == "vitamins"

    def test_skincare(self):
        with _vertical("pharmacy"):
            assert match_use_case_from_query("moisturiser for dry skin") == "skincare"

    def test_baby_care(self):
        with _vertical("pharmacy"):
            assert match_use_case_from_query("baby formula and nappies") == "baby_care"

    def test_no_electronics_bleed_gaming(self):
        """An electronics-flavoured query under pharmacy MUST NOT return gaming/laptop use-cases."""
        with _vertical("pharmacy"):
            result = match_use_case_from_query("gaming laptop rtx 4070")
            assert result is None or result not in (
                "gaming_casual", "gaming_competitive", "gaming_aaa_heavy", "gaming_light",
                "content_creator", "ai_ml_workstation", "engineering_student",
            )

    def test_no_electronics_bleed_student(self):
        """Electronics 'university_general' must not fire under pharmacy."""
        with _vertical("pharmacy"):
            result = match_use_case_from_query("university student laptop")
            # Pharmacy has no 'university_general' use-case
            assert result != "university_general"

    def test_persona_pharmacy(self):
        with _vertical("pharmacy"):
            persona_map = _get_use_case_to_persona()
            assert persona_map.get("pain_relief") == "patient"
            assert persona_map.get("baby_care") == "parent"
            assert persona_map.get("vitamins") == "wellness"
            # No gaming persona should exist in pharmacy
            assert "gamer" not in persona_map.values()


# ── Fashion: no electronics bleed ──

class TestFashionUseCaseMatch:
    def test_casual(self):
        with _vertical("fashion"):
            assert match_use_case_from_query("casual everyday streetwear") == "casual"

    def test_formal(self):
        with _vertical("fashion"):
            assert match_use_case_from_query("formal outfit for a wedding") == "formal"

    def test_athletic(self):
        with _vertical("fashion"):
            assert match_use_case_from_query("gym workout running") == "athletic"

    def test_outdoor(self):
        with _vertical("fashion"):
            assert match_use_case_from_query("hiking outdoor cold weather") == "outdoor"

    def test_no_electronics_bleed_gaming(self):
        """Electronics gaming use-cases must not fire under fashion."""
        with _vertical("fashion"):
            result = match_use_case_from_query("gaming laptop rtx 4070 cyberpunk")
            assert result is None or result not in (
                "gaming_casual", "gaming_competitive", "gaming_aaa_heavy", "gaming_light",
            )

    def test_no_electronics_bleed_office(self):
        """Fashion's 'formal' is NOT electronics 'office_general'."""
        with _vertical("fashion"):
            # "office" keyword matches fashion "formal" (which has "office" in keywords)
            result = match_use_case_from_query("office wear for meetings")
            assert result != "office_general"
            assert result != "business_professional"

    def test_persona_fashion(self):
        with _vertical("fashion"):
            persona_map = _get_use_case_to_persona()
            assert persona_map.get("casual") == "shopper"
            assert persona_map.get("athletic") == "athlete"
            assert persona_map.get("formal") == "professional"
            # No laptop-era personas
            assert "gamer" not in persona_map.values()
            assert "student" not in persona_map.values()
