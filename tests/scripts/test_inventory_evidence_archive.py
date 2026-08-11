from scripts.inventory_evidence_archive import _classification


def test_classification_separates_runtime_logs_from_evidence() -> None:
    assert _classification("scratchpad/backend.err.log") == (
        "runtime_log_review", "retain_until_replaced_by_curated_proof",
    )
    assert _classification("scratchpad/browser-proof.png") == (
        "scratchpad_evidence", "review_for_curated_archive",
    )
    assert _classification("docs/assessment.md") == (
        "project_document", "review_for_documentation_commit_or_external_archive",
    )


def test_no_classification_authorizes_deletion() -> None:
    for path in (
        "scratchpad/runtime.log",
        "scratchpad/result.json",
        "docs/roadmap.md",
        "browser-proof.png",
        "unknown.bin",
    ):
        assert "delete" not in _classification(path)[1]
