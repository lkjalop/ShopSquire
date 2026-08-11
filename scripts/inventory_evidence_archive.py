"""Create a file-level, non-destructive evidence/archive inventory.

The script hashes and classifies candidate files. It never moves, deletes, stages,
or edits a candidate. The generated CSV is an advisory review packet.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_status(repo: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    entries = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    statuses: dict[str, str] = {}
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            index += 1
        statuses[path.replace("\\", "/")] = status
    return statuses


def _classification(relative: str) -> tuple[str, str]:
    normalized = relative.replace("\\", "/")
    suffix = Path(normalized).suffix.lower()
    if normalized.startswith("scratchpad/"):
        if suffix == ".log":
            return "runtime_log_review", "retain_until_replaced_by_curated_proof"
        if suffix in {".png", ".json"}:
            return "scratchpad_evidence", "review_for_curated_archive"
        return "scratchpad_uncertain", "owner_review_required"
    if normalized.startswith("docs/"):
        return "project_document", "review_for_documentation_commit_or_external_archive"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "visual_evidence", "review_for_curated_archive"
    return "uncertain_evidence", "owner_review_required"


def inventory(repo: Path) -> list[dict[str, str | int]]:
    statuses = _git_status(repo)
    candidates: set[Path] = set()
    docs = repo / "docs"
    if docs.exists():
        candidates.update(path for path in docs.iterdir() if path.is_file())
    scratchpad = repo / "scratchpad"
    if scratchpad.exists():
        candidates.update(path for path in scratchpad.rglob("*") if path.is_file())
    candidates.update(path for path in repo.glob("*.png") if path.is_file())

    rows: list[dict[str, str | int]] = []
    for path in sorted(candidates, key=lambda item: item.as_posix().lower()):
        relative = path.relative_to(repo).as_posix()
        status = statuses.get(relative, "tracked_or_ignored")
        if status == "tracked_or_ignored" and not relative.startswith("scratchpad/"):
            continue
        classification, action = _classification(relative)
        stat = path.stat()
        rows.append({
            "path": relative,
            "git_status": status,
            "classification": classification,
            "proposed_action": action,
            "bytes": stat.st_size,
            "modified_utc": str(int(stat.st_mtime)),
            "sha256": _sha256(path),
            "deletion_authorized": "false",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    rows = inventory(repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["path"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} evidence/archive rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
