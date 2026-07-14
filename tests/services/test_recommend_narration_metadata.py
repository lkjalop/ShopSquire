from src.app.services.recommend_narration_stage import resolve_explainability_mode


def test_explainability_mode_tracks_final_visible_source():
    assert resolve_explainability_mode(
        narration_mode="blocking", narration_model="qwen3:14b", claim_guard_result="passed"
    ) == "llm_assisted"
    assert resolve_explainability_mode(
        narration_mode="blocking",
        narration_model="qwen3:14b",
        claim_guard_result="fell_back_to_deterministic",
    ) == "rules_fallback"
    assert resolve_explainability_mode(
        narration_mode="blocking",
        narration_model="qwen3:14b",
        claim_guard_result="forced_deterministic_use_case_conflict",
    ) == "rules_fallback"
    assert resolve_explainability_mode(
        narration_mode="async", narration_model="qwen3:14b", claim_guard_result="not_run"
    ) == "async_pending"
    assert resolve_explainability_mode(
        narration_mode="skip", narration_model=None, claim_guard_result="not_run"
    ) == "rules_only"
