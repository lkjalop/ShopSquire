"""R2 parity — query_decomposer use-case/spec patterns excised to StoreProfile.

The risk in R2 is regex-in-JSON transcription. This test compiles BOTH the profile
pattern and the inline fallback and asserts byte-identical match behaviour on a probe
corpus — any transcription error fails here immediately, before it reaches behaviour.
"""
from __future__ import annotations

from src.app.services import query_decomposer as qd

# Probe strings that exercise each use-case alternation (hits + near-misses).
_PROBES = [
    "best gaming laptop", "esports ray tracing rig", "video editing premiere davinci",
    "content creator youtube streaming", "coding docker android studio ide",
    "machine learning cuda pytorch data science", "autocad solidworks blender 3d modelling",
    "photoshop lightroom raw photo", "office excel spreadsheet productivity email",
    "university student note taking", "uni college study", "portable lightweight ultrabook travel",
    "a plain query about nothing in particular", "16gb ram 1tb storage 240hz rtx 4070",
    "thin and light commuter laptop", "engineering student revit",
]


def test_use_case_patterns_loaded_from_profile_match_inline():
    profile = qd._load_use_case_patterns()
    inline = qd._USE_CASE_PATTERNS_FALLBACK
    assert set(profile.keys()) == set(inline.keys()), "use-case set drifted"
    for uc in inline:
        for s in _PROBES:
            assert bool(profile[uc].search(s)) == bool(inline[uc].search(s)), \
                f"transcription mismatch for use_case={uc!r} on {s!r}"


def test_portable_pattern_parity():
    prof = qd._load_portable_re()
    inline = qd._PORTABLE_RE_FALLBACK
    for s in _PROBES:
        assert bool(prof.search(s)) == bool(inline.search(s)), f"portable mismatch on {s!r}"


def test_dgpu_use_cases_match_inline():
    assert qd._load_dgpu_use_cases() == qd._DGPU_USE_CASES_FALLBACK


def test_active_patterns_are_profile_backed():
    # The module-level actives were built from the profile (electronics default).
    assert set(qd._USE_CASE_PATTERNS.keys()) == set(qd._USE_CASE_PATTERNS_FALLBACK.keys())
    assert qd._DGPU_USE_CASES == {"gaming", "video_editing", "ml_ai", "cad_3d"}
