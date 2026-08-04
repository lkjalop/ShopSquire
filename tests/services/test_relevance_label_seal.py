import json

import pytest

from src.app.services.relevance_label_seal import (
    ATTESTATION,
    create_human_seal,
    verify_human_seal,
)


pytestmark = pytest.mark.protocol


def test_relevance_seal_rejects_automation_and_detects_corpus_change(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"labels": [{"id": "a", "relevant": True}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="independent_human_reviewer_required"):
        create_human_seal(
            path, reviewer="codex", reviewed_at="2026-07-28T00:00:00Z",
            attestation=ATTESTATION, signing_secret="x" * 32,
        )
    seal = create_human_seal(
        path, reviewer="human-reviewer-1", reviewed_at="2026-07-28T00:00:00Z",
        attestation=ATTESTATION, signing_secret="x" * 32,
    )
    assert verify_human_seal(path, seal, signing_secret="x" * 32)
    path.write_text(json.dumps({"labels": [{"id": "a", "relevant": False}]}), encoding="utf-8")
    assert not verify_human_seal(path, seal, signing_secret="x" * 32)
