"""Read-only Alembic inspection must not be mistaken for a downgrade plan."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def run(database, *arguments):
    env = dict(os.environ, APP_ENV="test", DATABASE_URL="sqlite:///" + database.as_posix(),
               PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "alembic", *arguments], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=45)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "inspection.sqlite3"
    result = run(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return path


def snapshot(database):
    with sqlite3.connect(database) as db:
        return (db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(),
                db.execute("SELECT version_num FROM alembic_version").fetchall())


@pytest.mark.parametrize("arguments", [("current",), ("current", "--check-heads")])
def test_current_inspection_succeeds_without_changing_schema_or_version(database, arguments):
    before = snapshot(database)
    result = run(database, *arguments)
    assert result.returncode == 0, result.stderr
    assert "20260894_supplier_enquiry_drafts" in result.stdout
    assert snapshot(database) == before


def test_populated_review_history_is_readable_without_granting_a_downgrade(database):
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO supplier_enquiry_draft VALUES "
                   "('owned-tenant','owned-enquiry',1,'hash','{\"reviewed\":true}','2026-10-24')")
    result = run(database, "current", "--check-heads")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT draft_json FROM supplier_enquiry_draft").fetchone() == ('{"reviewed":true}',)
    rejected = run(database, "downgrade", "-1")
    assert rejected.returncode != 0
    assert "no downgrade steps started" in rejected.stdout + rejected.stderr


def test_check_heads_rejects_an_empty_rolled_back_database_for_the_correct_reason(database):
    result = run(database, "downgrade", "-1")
    assert result.returncode == 0, result.stderr
    result = run(database, "current", "--check-heads")
    assert result.returncode != 0
    assert "not on all head revisions" in (result.stdout + result.stderr).lower()
    assert "KeyError" not in result.stdout + result.stderr
