from types import SimpleNamespace

from src.app.services.workload_interpretation_shadow import (
    compare_workload_interpretations,
    observe_workload_interpretations,
)


def _decompose(*use_cases: str):
    return lambda _query: SimpleNamespace(use_cases=list(use_cases))


def test_shadow_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WORKLOAD_INTERPRETATION_SHADOW_ENABLED", raising=False)
    assert observe_workload_interpretations("play an unfamiliar game") is None


def test_equivalent_interpretations_are_observation_only():
    result = compare_workload_interpretations(
        "run Blender",
        canonical_entities=(("software", "Blender"),),
        canonical_use_cases=("video_rendering",),
        decompose_fn=_decompose("video rendering"),
        detect_games_fn=lambda _q: [],
        detect_software_fn=lambda _q: ["blender"],
    ).as_dict()

    assert result["status"] == "equivalent"
    assert result["authoritative"] is False
    assert result["mode"] == "observer"
    assert result["divergence_codes"] == []


def test_legacy_title_only_is_reported_not_authorized():
    result = compare_workload_interpretations(
        "play old title",
        canonical_entities=(),
        canonical_use_cases=("gaming",),
        decompose_fn=_decompose("gaming"),
        detect_games_fn=lambda _q: ["old_title"],
        detect_software_fn=lambda _q: [],
    )

    assert result.status == "divergent"
    assert result.divergence_codes == ("legacy_entity_only",)


def test_canonical_only_and_use_case_mismatch_are_reported():
    result = compare_workload_interpretations(
        "model recognized a new workload",
        canonical_entities=(("software", "New Suite"),),
        canonical_use_cases=("engineering_professional",),
        decompose_fn=_decompose("engineering_student"),
        detect_games_fn=lambda _q: [],
        detect_software_fn=lambda _q: [],
    )

    assert result.divergence_codes == (
        "canonical_entity_only",
        "use_case_mismatch",
    )
