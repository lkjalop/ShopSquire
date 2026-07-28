from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.ci_ruff_changed import changed_python_files, main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_changed_file_scope_includes_modified_and_untracked_python_only(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "ruff@example.test")
    _git(tmp_path, "config", "user.name", "Ruff Test")
    (tmp_path / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    (tmp_path / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("NEW = 1\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("two\n", encoding="utf-8")

    assert changed_python_files(tmp_path, base=None) == ["new.py", "tracked.py"]


def test_empty_scope_message_does_not_claim_repository_clean(tmp_path, capsys):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "ruff@example.test")
    _git(tmp_path, "config", "user.name", "Ruff Test")
    (tmp_path / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    assert main(["--repo", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "does not evaluate repository-wide cleanliness" in output
