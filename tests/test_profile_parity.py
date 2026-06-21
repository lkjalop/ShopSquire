"""StoreProfile PARITY (Track 7 — the safety net for inline-fallback removal).

The agnostic core only stays vertical-blind if every profile carries the same core slots. This test
asserts that parity for the slots the core READS without an inline fallback. It is what makes the
Track-7 fallback removals safe: e.g. use_case_advisor no longer ships an electronics
use_case_keyword_map, so this test guarantees EVERY vertical supplies one.

It also documents the remaining inline-adapter slots (electronics still parses these inline pending a
byte-equivalent profile extraction) so the backlog is explicit and tested, not hidden.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_DIR = Path("config/store_profiles")
_PROFILES = {p.stem: json.loads(p.read_text(encoding="utf-8"))
             for p in _DIR.glob("*.json") if p.name != "store_profile.schema.json"}

# Slots the core reads with NO inline fallback — MUST be present + non-empty in EVERY profile.
_REQUIRED_IN_ALL = [
    "use_case_keyword_map",            # use_case_advisor.match_use_case_from_query
    "use_case_keyword_priority",       # use_case_advisor.match_use_case_from_query
    "use_case_to_persona",             # use_case_advisor._get_use_case_to_persona
    "nqe_use_case_fallback_question",  # recommend_nqe_helpers.apply_persona_confidence_fallback
    "supplier_message_templates",      # supplier_communication (Track 4)
    "external_research_allowlist",     # external research (Track 5) — may be [] but key present
    "persona_patterns",
    "nqe_brand_detect",
    "brand_price_floors_usd",
    "manufacturers",
    "primary_types",
    "use_cases",
]

# Inline-adapter slots: electronics parses these INLINE today (recommend_utils / recommend_ranking);
# other verticals carry the slot. Documented + tested so the backlog is explicit. When electronics
# gains a byte-equivalent slot here, flip it into _REQUIRED_IN_ALL and remove the inline adapter.
_INLINE_ADAPTER_SLOTS = {
    "spec_extraction_rules": {"electronics"},   # recommend_utils inline electronics spec parser
    "ranking_rules": {"electronics"},           # recommend_ranking inline electronics scorer
}


def test_profiles_loaded():
    assert {"electronics", "fashion", "pharmacy"}.issubset(set(_PROFILES)), f"profiles: {sorted(_PROFILES)}"


@pytest.mark.parametrize("slot", _REQUIRED_IN_ALL)
def test_required_slot_present_and_non_empty_in_every_profile(slot):
    missing = [name for name, prof in _PROFILES.items()
               if slot not in prof or prof.get(slot) in (None, "", [], {})]
    # external_research_allowlist legitimately may be an empty list — only require the KEY there.
    if slot == "external_research_allowlist":
        missing = [name for name, prof in _PROFILES.items() if slot not in prof]
    assert not missing, f"slot '{slot}' missing/empty in profiles: {missing} (breaks agnostic core)"


def test_nqe_fallback_question_shape():
    # Each profile's NQE disambiguation question must have text + options[{id,label}].
    for name, prof in _PROFILES.items():
        q = prof.get("nqe_use_case_fallback_question") or {}
        assert str(q.get("text") or "").strip(), f"{name}: nqe fallback question has no text"
        opts = q.get("options") or []
        assert isinstance(opts, list) and opts, f"{name}: nqe fallback question has no options"
        for o in opts:
            assert isinstance(o, dict) and o.get("id") and o.get("label"), f"{name}: bad option {o}"


def test_electronics_nqe_fallback_has_no_gaming_only_bleed_into_other_verticals():
    # The hardcoded electronics question ("...or gaming?") was excised to the profile. Non-electronics
    # verticals must NOT inherit a gaming option.
    for name in ("fashion", "pharmacy"):
        opts = _PROFILES[name]["nqe_use_case_fallback_question"]["options"]
        labels = " ".join(str(o.get("label", "")).lower() for o in opts)
        assert "gaming" not in labels, f"{name} NQE fallback leaked a gaming option"


@pytest.mark.parametrize("slot,expected_owners", sorted(_INLINE_ADAPTER_SLOTS.items()))
def test_inline_adapter_slots_are_absent_from_owner_and_present_elsewhere(slot, expected_owners):
    # The 'owner' verticals (electronics) intentionally LACK the slot (inline adapter); every other
    # vertical MUST carry it. If electronics gains the slot, update _REQUIRED_IN_ALL and remove the
    # inline adapter — this test will then fail, prompting that cleanup.
    for name, prof in _PROFILES.items():
        if name in expected_owners:
            assert slot not in prof, (
                f"{name} now carries '{slot}' — promote it to _REQUIRED_IN_ALL and remove the inline "
                f"adapter in recommend_utils/recommend_ranking, then drop it from _INLINE_ADAPTER_SLOTS"
            )
        else:
            assert prof.get(slot), f"{name} is missing inline-adapter slot '{slot}' (non-owner must carry it)"
