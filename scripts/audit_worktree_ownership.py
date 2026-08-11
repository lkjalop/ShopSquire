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

EVIDENCE_SUFFIXES = (".md", ".png", ".jpg", ".jpeg", ".txt", ".csv")


def _action_class(status: str, path: str, topic: str) -> str:
    normalized = path.replace("\\", "/")
    if topic == "generated runtime evidence":
        return "generated_artifact"
    if normalized.startswith("scratchpad/"):
        return "evidence_or_uncertain_bundle"
    if normalized.startswith("docs/") or normalized.lower().endswith(EVIDENCE_SUFFIXES):
        return "evidence_or_archive"
    if normalized.startswith(
        (
            ".github/",
            "config/",
            "frontend/",
            "scripts/",
            "src/",
            "tests/",
            "alembic/",
        )
    ) or normalized in {".dockerignore", "Dockerfile", "Dockerfile.web", "start_demo.ps1"}:
        return "intended_change_candidate"
    if status != "??":
        return "tracked_change_requires_hunk_review"
    return "uncertain_user_owned"


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


def _disposition(
    status: str, path: str, topic: str, action_class: str
) -> tuple[str, str, str]:
    untracked = status == "??"
    if topic == "generated runtime evidence":
        return (
            "generated",
            "verify_then_remove_or_archive",
            "Retain only when no hosted/final certification artifact supersedes it.",
        )
    if action_class == "evidence_or_archive":
        return (
            "user_evidence",
            "review_and_archive_or_commit",
            "Do not delete; decide whether this is durable project evidence or an external archive.",
        )
    if action_class == "evidence_or_uncertain_bundle":
        return (
            "mixed_evidence_bundle",
            "inventory_bundle_before_any_cleanup",
            "A single Git status row may contain many files; never delete the bundle wholesale.",
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
        action_class = _action_class(status, path, topic)
        ownership, disposition, notes = _disposition(status, path, topic, action_class)
        rows.append(
            {
                "status": status,
                "path": path,
                "topic": topic,
                "action_class": action_class,
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
