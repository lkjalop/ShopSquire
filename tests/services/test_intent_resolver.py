"""The intent→requirements resolver: KB profiles, alias normalization, multi-intent MAX merge,
and model-requirement merge — the unifying mechanism, deterministic and vertical-blind."""
from src.app.services.recommendation_core.intent_resolver import (
    known_use_cases,
    normalize_use_case,
    resolve,
)


def test_kb_vocabulary_present():
    ks = known_use_cases()
    assert {"gaming", "university", "creative", "ai_ml_workstation"} <= set(ks)


def test_alias_normalization():
    assert normalize_use_case("gamer") == "gaming"
    assert normalize_use_case("video editing") == "creative"
    assert normalize_use_case("uni") == "university"
    assert normalize_use_case("not_a_use_case") is None


def test_single_use_case_profile():
    r = resolve(["gaming"])
    req = r["requirements"]
    assert req["ram_gb"] == (">=", 16.0) and req["refresh_hz"] == (">=", 144.0)
    assert req["storage_gb"] == (">=", 512.0) and req["gpu_vram_gb"] == (">=", 4.0)  # gpu_tier discrete
    assert r["use_cases"] == ["gaming"] and r["persona_hint"]


def test_persona_differentiation():
    # the census-5 failure: primary/english vs CS/engineering must produce DIFFERENT floors
    uni = resolve(["university"])["requirements"]
    eng = resolve(["engineering_student"])["requirements"]
    assert uni["ram_gb"] == (">=", 8.0)                 # light academic
    assert eng["ram_gb"] == (">=", 16.0)                # engineering is heavier
    assert "gpu_vram_gb" in eng and "gpu_vram_gb" not in uni


def test_multi_intent_merges_by_max():
    # 'gaming AND video editing' → the union, most-demanding floor per key
    r = resolve(["gaming", "creative"])
    req = r["requirements"]
    assert req["ram_gb"] == (">=", 16.0)                # both want 16
    assert req["refresh_hz"] == (">=", 144.0)           # from gaming
    assert req["storage_gb"] == (">=", 512.0)
    assert set(r["use_cases"]) == {"gaming", "creative"}


def test_ai_ml_is_most_demanding():
    req = resolve(["ai_ml_workstation"])["requirements"]
    assert req["ram_gb"] == (">=", 32.0) and req["gpu_vram_gb"] == (">=", 8.0)
    assert req["storage_gb"] == (">=", 1000.0)


def test_model_requirements_merge_max():
    # model extracted '144fps' on a university turn → merges in, MAX
    r = resolve(["university"], model_requirements={"refresh_hz": (">=", 144.0),
                                                    "ram_gb": (">=", 4.0)})
    req = r["requirements"]
    assert req["refresh_hz"] == (">=", 144.0)           # model's, kept
    assert req["ram_gb"] == (">=", 8.0)                 # KB's 8 beats model's 4 (MAX)


def test_empty_and_unknown_are_safe():
    assert resolve([])["requirements"] == {}
    assert resolve(["garbage", "also_garbage"])["use_cases"] == []
    assert resolve(None, {"ram_gb": (">=", 16.0)})["requirements"] == {"ram_gb": (">=", 16.0)}


def test_profile_trace_for_why_recommended():
    r = resolve(["gaming", "creative"])
    assert set(r["profile_trace"]) == {"gaming", "creative"}
    assert r["profile_trace"]["gaming"]["label"] == "Gaming"
    assert "requirements" in r["profile_trace"]["creative"]
