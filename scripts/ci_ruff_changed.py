"""Run Ruff only on Python files changed from a declared Git base.

This is an incremental ratchet, not a repository-cleanliness check. Its output
always states that distinction so a green result cannot be presented as a
clean whole-repository Ruff run.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_python_files(repo: Path, *, base: str | None) -> list[str]:
    """Return existing changed Python paths, including local untracked files."""
    if base:
        candidates = _git(
            repo,
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base}...HEAD",
            "--",
            "*.py",
        )
    else:
        candidates = _git(
            repo,
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            "HEAD",
            "--",
            "*.py",
        )
        candidates.extend(
            _git(repo, "ls-files", "--others", "--exclude-standard", "--", "*.py")
        )
    return sorted({
        path
        for path in candidates
        if (repo / path).is_file()
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ruff changed-file ratchet (not a whole-repository check)",
    )
    parser.add_argument("--base", help="Git base revision for BASE...HEAD")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--ruff", default="ruff", help="Ruff executable")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    files = changed_python_files(repo, base=args.base)
    scope = f"{args.base}...HEAD" if args.base else "local changes from HEAD"
    print(
        f"Ruff incremental scope: {len(files)} changed Python file(s) in {scope}. "
        "This does not evaluate repository-wide cleanliness.",
    )
    if not files:
        return 0
    result = subprocess.run(
        [args.ruff, "check", *files],
        cwd=repo,
        check=False,
    )
    if result.returncode == 0:
        print(
            "Ruff changed-file gate passed. "
            "Legacy findings outside the changed-file scope may remain.",
        )
    return int(result.returncode)


if __name__ == "__main__":
    sys.exit(main())
