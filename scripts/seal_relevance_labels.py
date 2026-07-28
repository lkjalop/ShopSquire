"""Create a human relevance-label seal without exposing the signing secret."""
from __future__ import annotations

import argparse
from getpass import getpass
import json

from src.app.services.relevance_label_seal import ATTESTATION, create_human_seal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="tests/golden/relevance_labels.json")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    args = parser.parse_args()
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
    print(json.dumps(seal, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
