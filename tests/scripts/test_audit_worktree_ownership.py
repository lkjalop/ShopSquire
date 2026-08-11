from scripts.audit_worktree_ownership import _action_class, _disposition


def test_action_classes_keep_evidence_and_uncertain_bundles_out_of_cleanup() -> None:
    assert _action_class("??", "docs/assessment.md", "documentation") == "evidence_or_archive"
    assert (
        _action_class("??", "scratchpad/", "manual classification required")
        == "evidence_or_uncertain_bundle"
    )
    assert (
        _action_class("??", "src/app/services/new_slice.py", "manual classification required")
        == "intended_change_candidate"
    )

    ownership, disposition, _ = _disposition(
        "??", "scratchpad/", "manual classification required", "evidence_or_uncertain_bundle"
    )
    assert ownership == "mixed_evidence_bundle"
    assert disposition == "inventory_bundle_before_any_cleanup"


def test_unknown_untracked_path_remains_uncertain_user_owned() -> None:
    action_class = _action_class("??", "mystery.bin", "manual classification required")
    assert action_class == "uncertain_user_owned"
    ownership, disposition, _ = _disposition(
        "??", "mystery.bin", "manual classification required", action_class
    )
    assert ownership == "authorship_unverified"
    assert disposition == "review_then_add_to_topic_commit"
