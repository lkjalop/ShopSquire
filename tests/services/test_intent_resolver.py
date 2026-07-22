"""The intent→requirements resolver: KB profiles, alias normalization, multi-intent merge,
and model-requirement merge — the unifying mechanism, deterministic and vertical-blind.

M2-B1: requirements are now RANGES ({key: [(op, thr), ...]}) merged by INTERSECTION with
provenance; a stated ceiling meeting a KB floor is a SURFACED CONFLICT, never a silent win
for either side (the old one-slot incoming-wins rule is gone)."""
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
    assert req["ram_gb"] == [(">=", 16.0)] and req["refresh_hz"] == [(">=", 144.0)]
    assert req["storage_gb"] == [(">=", 512.0)] and req["gpu_vram_gb"] == [(">=", 4.0)]  # gpu_tier discrete
    assert r["use_cases"] == ["gaming"] and r["persona_hint"]
    # provenance rides every bound (the 'Why Recommended' trace)
    assert r["constraints"]["ram_gb"]["provenance"] == ["use_case:gaming"]


def test_persona_differentiation():
    # the census-5 failure: primary/english vs CS/engineering must produce DIFFERENT floors
    uni = resolve(["university"])["requirements"]
    eng = resolve(["engineering_student"])["requirements"]
    assert uni["ram_gb"] == [(">=", 8.0)]               # light academic
    assert eng["ram_gb"] == [(">=", 16.0)]              # engineering is heavier
    assert "gpu_vram_gb" in eng and "gpu_vram_gb" not in uni


def test_multi_intent_merges_most_demanding_floor():
    # 'gaming AND video editing' → the union, most-demanding floor per key
    r = resolve(["gaming", "creative"])
    req = r["requirements"]
    assert req["ram_gb"] == [(">=", 16.0)]              # both want 16
    assert req["refresh_hz"] == [(">=", 144.0)]         # from gaming
    assert req["storage_gb"] == [(">=", 512.0)]
    assert set(r["use_cases"]) == {"gaming", "creative"}
    assert not r["conflicts"]                           # floors only → no conflict possible


def test_workload_precedes_audience_context_without_losing_either_profile():
    first = resolve(["university", "game_development"])
    second = resolve(["game_development", "university"])

    assert first["use_cases"] == ["game_development", "university"]
    assert second["use_cases"] == first["use_cases"]
    assert first["primary_use_case"] == "game_development"
    assert "game developer" in first["persona_hint"].lower()
    assert set(first["profile_trace"]) == {"game_development", "university"}
    assert first["requirements"]["gpu_vram_gb"] == [(">=", 6.0)]
    assert "battery_hours" not in first["requirements"]
    assert first["context_use_cases"] == ["university"]
    assert first["workload_use_cases"] == ["game_development"]
    assert first["context_preferences"]["university"]["battery_hours"] == [(">=", 8.0)]
    assert first["requirements"] == second["requirements"]


def test_audience_profile_is_baseline_when_no_workload_is_known():
    result = resolve(["university"])

    assert result["workload_use_cases"] == []
    assert result["context_use_cases"] == ["university"]
    assert result["requirements"]["battery_hours"] == [(">=", 8.0)]
    assert result["context_preferences"] == {}


def test_ai_ml_is_most_demanding():
    req = resolve(["ai_ml_workstation"])["requirements"]
    assert req["ram_gb"] == [(">=", 32.0)] and req["gpu_vram_gb"] == [(">=", 8.0)]
    assert req["storage_gb"] == [(">=", 1000.0)]


def test_model_requirements_merge():
    # model extracted '144fps' on a university turn → merges in; floors intersect to the max
    r = resolve(["university"], model_requirements={"refresh_hz": [(">=", 144.0)],
                                                    "ram_gb": [(">=", 4.0)]})
    req = r["requirements"]
    assert req["refresh_hz"] == [(">=", 144.0)]         # model's, kept
    assert req["ram_gb"] == [(">=", 8.0)]               # KB's 8 beats model's 4
    assert set(r["constraints"]["ram_gb"]["provenance"]) == {"use_case:university", "stated"}


def test_stated_ceiling_vs_kb_floor_is_a_surfaced_conflict():
    """B1 acceptance (review-4 Q1 / spec B1): 'nothing over 8GB' on a university turn (KB floor
    16 via engineering? university floor is 8) — use engineering_student (floor 16) so the
    ceiling 8 CONFLICTS: surfaced in conflicts, EXCLUDED from gating, never inverted."""
    r = resolve(["engineering_student"], model_requirements={"ram_gb": [("<=", 8.0)]})
    keys = [c["key"] for c in r["conflicts"]]
    assert "ram_gb" in keys
    assert "ram_gb" not in r["requirements"]            # contradictions never gate
    conflict = next(c for c in r["conflicts"] if c["key"] == "ram_gb")
    assert conflict["lower"] == 16.0 and conflict["upper"] == 8.0
    assert set(conflict["provenance"]) == {"use_case:engineering_student", "stated"}


def test_compatible_ceiling_becomes_a_range():
    # university floor 8 + stated ceiling 16 → ONE range, both bounds enforced (the shape the
    # old one-slot physically couldn't hold)
    r = resolve(["university"], model_requirements={"ram_gb": [("<=", 16.0)]})
    assert r["requirements"]["ram_gb"] == [(">=", 8.0), ("<=", 16.0)]
    assert not r["conflicts"]


def test_empty_and_unknown_are_safe():
    assert resolve([])["requirements"] == {}
    assert resolve(["garbage", "also_garbage"])["use_cases"] == []
    assert resolve(None, {"ram_gb": [(">=", 16.0)]})["requirements"] == {"ram_gb": [(">=", 16.0)]}
    # legacy single-tuple shape still accepted at the boundary
    assert resolve(None, {"ram_gb": (">=", 16.0)})["requirements"] == {"ram_gb": [(">=", 16.0)]}


def test_profile_trace_for_why_recommended():
    r = resolve(["gaming", "creative"])
    assert set(r["profile_trace"]) == {"gaming", "creative"}
    assert r["profile_trace"]["gaming"]["label"] == "Gaming"
    assert "requirements" in r["profile_trace"]["creative"]
