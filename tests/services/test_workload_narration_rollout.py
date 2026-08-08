from src.app.services.recommendation_core.workload_narration_rollout import (
    NarrationRolloutPolicy,
    configured_rollout_policy,
    decide_shadow_rollout,
)


DECISION = {"authorized_narration_blocks": ["Deterministic authorized explanation."]}


def test_even_accepted_shadow_remains_audit_only() -> None:
    result = decide_shadow_rollout(
        DECISION, {"status": "accepted_shadow", "candidate": "Model prose"},
        tenant_id="tenant-a", identity_id="buyer-a",
        policy=NarrationRolloutPolicy(mode="shadow", canary_percent=100),
    )
    assert result.shadow_evaluation_selected is True
    assert result.buyer_visible is False
    assert result.commercial_authority_granted is False
    assert result.buyer_renderer == "deterministic_authorized_blocks"
    assert result.deterministic_blocks == ["Deterministic authorized explanation."]
    assert result.fallback_reason == "accepted_shadow_audit_only"


def test_rejected_shadow_falls_back_to_exact_deterministic_blocks() -> None:
    result = decide_shadow_rollout(
        DECISION, {"status": "rejected_shadow"}, tenant_id="tenant-a",
        identity_id="buyer-a", policy=NarrationRolloutPolicy(mode="shadow"),
    )
    assert result.buyer_renderer == "deterministic_authorized_blocks"
    assert result.deterministic_blocks is not DECISION["authorized_narration_blocks"]
    assert result.deterministic_blocks == DECISION["authorized_narration_blocks"]
    assert result.fallback_reason == "shadow_rejected_shadow_deterministic_fallback"


def test_canary_assignment_is_stable_and_never_changes_visibility() -> None:
    policy = NarrationRolloutPolicy(mode="canary", canary_percent=30)
    first = decide_shadow_rollout(
        DECISION, None, tenant_id="tenant-a", identity_id="buyer-a", policy=policy,
    )
    second = decide_shadow_rollout(
        DECISION, None, tenant_id="tenant-a", identity_id="buyer-a", policy=policy,
    )
    assert first.cohort_bucket == second.cohort_bucket
    assert first.shadow_evaluation_selected == second.shadow_evaluation_selected
    assert first.buyer_visible is False


def test_invalid_environment_configuration_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("WORKLOAD_NARRATION_ROLLOUT_MODE", "buyer-visible")
    monkeypatch.setenv("WORKLOAD_NARRATION_CANARY_PERCENT", "900")
    policy = configured_rollout_policy()
    assert policy.mode == "off"
    assert policy.canary_percent == 0
