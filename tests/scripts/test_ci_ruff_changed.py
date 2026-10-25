from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize('invalid', [False, True])
def test_wide_native_scope_reports_clean_or_bad_source_without_command_overflow(tmp_path, invalid):
    """Real Git and Ruff: this scope exceeded Windows' native command line."""
    _git(tmp_path, 'init')
    _git(tmp_path, 'config', 'user.email', 'ruff@example.test')
    _git(tmp_path, 'config', 'user.name', 'Ruff Test')
    (tmp_path / 'README.md').write_text('baseline\n', encoding='utf-8')
    _git(tmp_path, 'add', 'README.md')
    _git(tmp_path, 'commit', '-m', 'baseline')
    executable = Path(sys.executable).with_name('ruff.exe' if sys.platform == 'win32' else 'ruff')
    ruff = str(executable) if executable.is_file() else shutil.which('ruff')
    assert ruff, 'The committed test profile must provide Ruff'
    (tmp_path / 'pyproject.toml').write_text('[tool.ruff.lint]\nselect = ["F"]\n', encoding='utf-8')
    directory = tmp_path / ('scope_' + 'x' * 48)
    directory.mkdir()
    for index in range(600):
        content = 'import os\n' if invalid and index == 599 else 'VALUE = 1\n'
        (directory / (f'{index:04d}_' + 'candidate_' * 5 + '.py')).write_text(content, encoding='utf-8')
    assert main(['--repo', str(tmp_path), '--ruff', ruff]) == (1 if invalid else 0)


def test_terminated_ruff_process_never_reports_clean(tmp_path, monkeypatch, capsys):
    from scripts import ci_ruff_changed as runner
    monkeypatch.setattr(runner, 'changed_python_files', lambda *args, **kwargs: ['file.py'])
    monkeypatch.setattr(runner.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, -9))
    assert runner.main(['--repo', str(tmp_path)]) == -9
    assert 'gate passed' not in capsys.readouterr().out
