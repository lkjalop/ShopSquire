"""Create a human relevance-label seal without exposing the signing secret."""
from __future__ import annotations

import argparse
from getpass import getpass
import json
from pathlib import Path

from src.app.services.relevance_label_seal import (
    ATTESTATION,
    candidate_label_gaps,
    create_human_seal,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="tests/golden/relevance_labels.json")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--candidates", default="tmp/relevance_review_candidates.json")
    parser.add_argument(
        "--apply", action="store_true",
        help="write the human review metadata and signature into the labels file",
    )
    args = parser.parse_args()
    gaps = candidate_label_gaps(args.labels, args.candidates)
    if gaps:
        print(json.dumps({"status": "unsealed", "unlabeled_shown_skus": gaps}, indent=2))
        print("Grade every currently shown SKU 0, 1, or 2 before sealing.")
        return 2
    print(ATTESTATION)
    confirmation = input("Type the exact attestation above after completing the independent review: ")
    secret = getpass("Human seal secret (24+ characters): ")
    seal = create_human_seal(
        args.labels,
        reviewer=args.reviewer,
        reviewed_at=args.reviewed_at,
        attestation=confirmation,
        signing_secret=secret,
    )
    if args.apply:
        path = Path(args.labels)
        labels = json.loads(path.read_text(encoding="utf-8"))
        labels.update({
            "review_status": "human_sealed",
            "human_reviewed_by": seal["reviewer"],
            "human_reviewed_at": seal["reviewed_at"],
            "human_attestation": seal["attestation"],
            "human_corpus_hash": seal["corpus_hash"],
            "human_signature": seal["signature"],
        })
        path.write_text(
            json.dumps(labels, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
    print(json.dumps(seal, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
