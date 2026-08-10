import json

import pytest

from src.app.services.relevance_label_seal import (
    ATTESTATION,
    candidate_label_gaps,
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
    with pytest.raises(ValueError, match="independent_human_reviewer_required"):
        create_human_seal(
            path, reviewer="codex-independent-reviewer", reviewed_at="2026-07-28T00:00:00Z",
            attestation=ATTESTATION, signing_secret="x" * 32,
        )
    seal = create_human_seal(
        path, reviewer="human-reviewer-1", reviewed_at="2026-07-28T00:00:00Z",
        attestation=ATTESTATION, signing_secret="x" * 32,
    )
    assert verify_human_seal(path, seal, signing_secret="x" * 32)
    reviewed = json.loads(path.read_text(encoding="utf-8"))
    reviewed.update({
        "review_status": "human_sealed",
        "human_reviewed_by": seal["reviewer"],
        "human_reviewed_at": seal["reviewed_at"],
        "human_attestation": seal["attestation"],
        "human_corpus_hash": seal["corpus_hash"],
        "human_signature": seal["signature"],
    })
    path.write_text(json.dumps(reviewed), encoding="utf-8")
    assert verify_human_seal(path, seal, signing_secret="x" * 32)
    path.write_text(json.dumps({"labels": [{"id": "a", "relevant": False}]}), encoding="utf-8")
    assert not verify_human_seal(path, seal, signing_secret="x" * 32)


def test_candidate_coverage_fails_for_any_unlabeled_shown_sku(tmp_path):
    labels = tmp_path / "labels.json"
    candidates = tmp_path / "candidates.json"
    labels.write_text(json.dumps({
        "cases": {"case-a:0": {"labels": {"SKU-1": 2}}},
    }), encoding="utf-8")
    candidates.write_text(json.dumps({
        "case-a:0": {"products": [{"sku": "SKU-1"}, {"sku": "SKU-2"}]},
    }), encoding="utf-8")

    assert candidate_label_gaps(labels, candidates) == {"case-a:0": ["SKU-2"]}
