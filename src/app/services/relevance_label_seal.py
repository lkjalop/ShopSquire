"""Human-only sealing workflow for relevance labels."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re


ATTESTATION = "I independently reviewed every relevance slate and accept these labels."


def candidate_label_gaps(
    labels_path: str | Path,
    candidates_path: str | Path,
) -> dict[str, list[str]]:
    """Return every currently shown SKU that the prospective human seal leaves ungraded."""
    labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    candidates = json.loads(Path(candidates_path).read_text(encoding="utf-8"))
    cases = labels.get("cases") if isinstance(labels, dict) else None
    if not isinstance(cases, dict) or not isinstance(candidates, dict):
        raise ValueError("relevance_review_inputs_must_be_objects")
    gaps: dict[str, list[str]] = {}
    for case_id, slate in candidates.items():
        products = slate.get("products") if isinstance(slate, dict) else None
        graded = (cases.get(case_id) or {}).get("labels")
        graded = graded if isinstance(graded, dict) else {}
        missing = [
            str(item.get("sku"))
            for item in (products or [])
            if isinstance(item, dict) and item.get("sku") and str(item["sku"]) not in graded
        ]
        if missing:
            gaps[str(case_id)] = missing
    return gaps


def canonical_corpus_hash(path: str | Path) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("relevance_corpus_must_be_object")
    review_copy = dict(data)
    for key in (
        "review_status",
        "human_reviewed_by",
        "human_reviewed_at",
        "human_attestation",
        "human_corpus_hash",
        "human_signature",
    ):
        review_copy.pop(key, None)
    encoded = json.dumps(review_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def create_human_seal(
    path: str | Path,
    *,
    reviewer: str,
    reviewed_at: str,
    attestation: str,
    signing_secret: str,
) -> dict[str, str]:
    identity = str(reviewer or "").strip()
    secret = str(signing_secret or "")
    identity_tokens = {
        token for token in re.split(r"[^a-z0-9]+", identity.lower()) if token
    }
    if not identity or identity_tokens & {
        "codex", "ai", "automation", "system", "claude", "chatgpt", "bot",
    }:
        raise ValueError("independent_human_reviewer_required")
    if attestation != ATTESTATION:
        raise ValueError("exact_human_attestation_required")
    if len(secret) < 24:
        raise ValueError("human_seal_secret_too_short")
    corpus_hash = canonical_corpus_hash(path)
    message = f"{corpus_hash}|{identity}|{reviewed_at}|{attestation}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "corpus_hash": corpus_hash,
        "reviewer": identity,
        "reviewed_at": reviewed_at,
        "attestation": attestation,
        "signature": signature,
    }


def verify_human_seal(path: str | Path, seal: dict[str, str], *, signing_secret: str) -> bool:
    if canonical_corpus_hash(path) != seal.get("corpus_hash"):
        return False
    message = (
        f"{seal.get('corpus_hash')}|{seal.get('reviewer')}|"
        f"{seal.get('reviewed_at')}|{seal.get('attestation')}"
    )
    expected = hmac.new(str(signing_secret).encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(seal.get("signature") or ""))
