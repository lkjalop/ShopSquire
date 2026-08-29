from pydantic import ValidationError
import pytest

from src.app.services.research_control_loop import (
    ExecutionStateEnvelope,
    ExperientialPatchCandidate,
    PromotionEvidence,
    localize_control_faults,
    propose_sanitized_failure_lesson,
    promote_experiential_patch,
)


def _envelope(**overrides):
    values = {
        "case_id": "case-held-out-game",
        "case_revision": 1,
        "buyer_text_hash": "a" * 64,
        "model_status": "completed",
        "material_concept_status": "unresolved",
        "research_authority": "granted",
        "provider_status": "disabled",
        "evidence_status": "none",
        "requirement_status": "blocked",
        "catalog_authority": "blocked",
        "presentation_status": "clarification_only",
        "commerce_authority": "none",
    }
    values.update(overrides)
    return ExecutionStateEnvelope(**values)


def test_component_fault_localization_distinguishes_invocation_from_model_failure():
    faults = localize_control_faults(_envelope())
    assert [(item.component, item.code) for item in faults] == [
        ("invocation", "authorized_provider_disabled"),
    ]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"research_authority": "required", "provider_status": "not_attempted"}, []),
        ({"provider_status": "not_attempted"}, [("invocation", "authorized_provider_not_invoked")]),
        ({"provider_status": "timeout"}, [("invocation", "provider_timeout")]),
        ({"provider_status": "failed"}, [("invocation", "provider_failed")]),
        ({"provider_status": "completed", "evidence_status": "stale"}, [("checker", "evidence_stale")]),
        ({"provider_status": "completed", "evidence_status": "contradicted"}, [("checker", "evidence_contradicted")]),
        ({"model_status": "timeout"}, [("model", "model_timeout"), ("invocation", "authorized_provider_disabled")]),
        (
            {
                "material_concept_status": "resolved",
                "provider_status": "completed",
                "evidence_status": "identity_only",
            },
            [("working_state", "identity_resolved_requirements_missing")],
        ),
    ],
)
def test_certified_control_failures_are_localized_without_granting_authority(overrides, expected):
    faults = localize_control_faults(_envelope(**overrides))
    assert [(item.component, item.code) for item in faults] == expected
    assert all(item.authority == "none" for item in faults)


def test_model_variation_is_provenance_not_authority():
    first = _envelope(model_identity="qwen3:14b", model_output_hash="b" * 64)
    second = _envelope(model_identity="qwen3:8b", model_output_hash="c" * 64)
    assert first.model_identity != second.model_identity
    assert first.model_output_hash != second.model_output_hash
    assert first.catalog_authority == second.catalog_authority == "blocked"
    assert first.commerce_authority == second.commerce_authority == "none"


def test_unresolved_material_cannot_be_presented_as_qualified():
    with pytest.raises(ValidationError, match="presentation_exceeds_evidence_authority"):
        _envelope(presentation_status="qualified_recommendation")


def test_failure_lesson_is_sanitized_and_non_authoritative():
    lesson = propose_sanitized_failure_lesson(_envelope(), localize_control_faults(_envelope()))
    assert lesson.buyer_text_hash == "a" * 64
    assert lesson.raw_buyer_text is None
    assert lesson.authority == "none"
    assert lesson.lifecycle == "cold"


def test_experiential_patch_needs_repeated_failures_and_heldout_gain_before_promotion():
    candidate = ExperientialPatchCandidate(
        patch_id="patch-provider-readiness",
        failure_code="authorized_provider_disabled",
        component="invocation",
        proposed_change="Require aligned provider readiness before research dispatch.",
        rollback_ref="git:before-provider-readiness",
        provenance_ids=("failure-1", "failure-2", "failure-3"),
    )
    rejected = promote_experiential_patch(
        candidate,
        PromotionEvidence(
            repeated_failure_count=3,
            heldout_cases=10,
            baseline_successes=8,
            candidate_successes=8,
            safety_regressions=0,
        ),
    )
    assert rejected.lifecycle == "cold"
    assert rejected.promoted is False

    promoted = promote_experiential_patch(
        candidate,
        PromotionEvidence(
            repeated_failure_count=3,
            heldout_cases=10,
            baseline_successes=8,
            candidate_successes=10,
            safety_regressions=0,
        ),
    )
    assert promoted.lifecycle == "warm"
    assert promoted.promoted is True

    hot = promote_experiential_patch(
        candidate.model_copy(update={"lifecycle": "warm"}),
        PromotionEvidence(
            repeated_failure_count=8,
            heldout_cases=25,
            baseline_successes=18,
            candidate_successes=24,
            safety_regressions=0,
        ),
    )
    assert hot.lifecycle == "hot"
    assert hot.promoted is True
