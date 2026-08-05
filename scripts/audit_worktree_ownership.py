"""Create a non-destructive ownership manifest for a mixed Git worktree.

The report is advisory: this script never stages, deletes, moves, or edits the
paths it classifies. It is intended to make a large dirty tree reviewable before
topic commits are assembled.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from pathlib import Path


GENERATED_PREFIXES = (
    ".tmp-",
    "terraform/.terraform/",
)
GENERATED_NAMES = {
    "celerybeat-schedule.bak",
    "celerybeat-schedule.dat",
    "celerybeat-schedule.dir",
    "tmp-thread-debug.db-shm",
    "tmp-thread-debug.db-wal",
}


def _topic(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith(GENERATED_PREFIXES) or normalized in GENERATED_NAMES:
        return "generated runtime evidence"
    if normalized.startswith((".github/", "deploy/", "terraform/")) or normalized in {
        "Dockerfile",
        "Dockerfile.web",
        ".dockerignore",
    }:
        return "CI/cloud"
    if normalized.startswith("docs/"):
        return "documentation"
    if normalized.startswith(("frontend/", "src/frontend/")):
        return "frontend and Decision Trace"
    if normalized.startswith(("tests/security/", "src/app/security/")) or any(
        marker in normalized
        for marker in ("vision", "artifact_authority", "security_", "geoip", "rate_limit")
    ):
        return "security and vision"
    if any(
        marker in normalized
        for marker in (
            "semantic",
            "conversation_case",
            "recommendation_core",
            "external_product_research",
            "product_identity",
        )
    ):
        return "semantic reasoning and research"
    if any(
        marker in normalized
        for marker in (
            "allocation",
            "fulfillment",
            "inventory",
            "supplier",
            "market_",
            "temporal",
            "cache",
            "return",
        )
    ):
        return "procurement, ATP and temporal cache"
    if normalized.startswith("tests/"):
        return "tests/evidence requiring topic assignment"
    return "manual classification required"


def _disposition(status: str, path: str, topic: str) -> tuple[str, str, str]:
    untracked = status == "??"
    if topic == "generated runtime evidence":
        return (
            "generated",
            "verify_then_remove_or_archive",
            "Retain only when no hosted/final certification artifact supersedes it.",
        )
    if untracked:
        return (
            "authorship_unverified",
            "review_then_add_to_topic_commit",
            "Untracked source/evidence must be reviewed before staging.",
        )
    return (
        "mixed_tracked_history",
        "stage_reviewed_hunks_only",
        "Do not stage the whole file when unrelated user changes are present.",
    )


def _status_rows(repo: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    entries = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    rows: list[dict[str, str]] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:]
        if "R" in status or "C" in status:
            if index < len(entries):
                original = entries[index]
                index += 1
                path = f"{original} -> {path}"
        topic = _topic(path)
        ownership, disposition, notes = _disposition(status, path, topic)
        rows.append(
            {
                "status": status,
                "path": path,
                "topic": topic,
                "ownership": ownership,
                "proposed_disposition": disposition,
                "test_proof": "not_yet_linked",
                "notes": notes,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    rows = _status_rows(repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["path"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
