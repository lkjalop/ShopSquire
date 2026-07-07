"""N4 — challenge-defense: spec-vs-KB justification with honest gaps (uses the real electronics KB)."""
from __future__ import annotations

from src.app.services.recommend_justification import (
    build_challenge_justification, is_challenge_turn, _resolve_kb_entry,
)


def _top(vram=8, ram=16, storage=512):
    return [{"name": "Alpha X1", "specs": {"gpu_vram_gb": vram, "ram_gb": ram, "storage_gb": storage,
                                           "gpu_tier": "discrete_8gb"}}]


def test_challenge_detection():
    assert is_challenge_turn("are you sure? why would it be good for training llm models?")
    assert is_challenge_turn("prove it")
    assert not is_challenge_turn("show me gaming laptops under 2000")


def test_fuzzy_kb_resolution_bridges_id_drift():
    from src.app.services.recommend_budget_parsing import load_capability_kb
    kb = load_capability_kb()
    key, entry = _resolve_kb_entry("ml_ai", kb)          # profile id != KB key
    assert key == "ai_ml_workstation" and entry


def test_defense_admits_gaps_honestly():
    ans = build_challenge_justification(
        "are you sure this is right for ml?", _top(vram=8, ram=16), {"use_case": "ml_ai"})
    assert "meets" in ans and "falls short" in ans
    assert "ram gb: 16 vs 32 minimum" in ans.lower()      # the gap is NAMED, not glossed
    assert "Honest verdict" in ans


def test_defense_confident_when_all_bars_cleared():
    ans = build_challenge_justification(
        "you sure about this one?", _top(vram=16, ram=64, storage=2000), {"use_case": "ml_ai"})
    assert "clears every stated minimum" in ans


def test_unrecorded_spec_is_unverified_not_assumed():
    ans = build_challenge_justification(
        "are you sure?", [{"name": "Alpha", "specs": {"ram_gb": 64}}], {"use_case": "ml_ai"})
    assert "unverified" in ans and "not recorded" in ans


def test_non_challenge_returns_empty():
    assert build_challenge_justification("gaming laptop under 2000", _top(), {"use_case": "gaming"}) == ""
