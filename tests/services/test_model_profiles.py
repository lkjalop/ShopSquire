"""Model descriptors (B3) — per-model physics resolution: env -> descriptor -> fallback."""
from __future__ import annotations

import src.app.services.model_profiles as mp


def _clear_env(monkeypatch):
    for var in ("OLLAMA_SUMMARY_TIMEOUT_S", "RECOMMEND_NARRATION_TIMEOUT_SEC", "OLLAMA_SUMMARY_THINK"):
        monkeypatch.delenv(var, raising=False)


def test_exact_and_family_and_default_resolution():
    q = mp.model_profile("qwen3:14b")
    assert "narrator" in q.get("certified_roles", [])
    fam = mp.model_profile("qwen3:8b")  # family fallback: qwen3 physics, not _default
    assert fam.get("think_mode") == "off"
    d = mp.model_profile("totally-unknown:1b")
    assert d.get("certified_roles") == []  # _default
    assert mp.model_profile(None)  # never raises


def test_descriptor_supplies_timeouts_when_env_unset(monkeypatch):
    _clear_env(monkeypatch)
    assert mp.summary_timeout_s("qwen3:14b") == 45.0
    assert mp.narration_timeout_s("qwen3:14b") == 45.0
    assert mp.think_mode("qwen3:14b") == "off"
    # unknown model -> _default descriptor values
    assert mp.summary_timeout_s("totally-unknown:1b") == 25.0
    assert mp.narration_timeout_s("totally-unknown:1b") == 30.0


def test_env_override_wins(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OLLAMA_SUMMARY_TIMEOUT_S", "12")
    monkeypatch.setenv("RECOMMEND_NARRATION_TIMEOUT_SEC", "3")
    monkeypatch.setenv("OLLAMA_SUMMARY_THINK", "auto")
    assert mp.summary_timeout_s("qwen3:14b") == 12.0
    assert mp.narration_timeout_s("qwen3:14b") == 3.0
    assert mp.think_mode("qwen3:14b") == "auto"


def test_cut_models_carry_no_certified_roles():
    assert mp.model_profile("phi4").get("certified_roles") == []
    assert mp.model_profile("granite4:micro").get("certified_roles") == []


def test_resident_footprint_present_for_co_residency_cert():
    # round-4 lesson: certification is per resident SET; the footprint field is the input
    for m in ("qwen3:14b", "gemma3:12b", "granite4:micro"):
        assert float(mp.model_profile(m)["resident_footprint_gb"]) > 0
