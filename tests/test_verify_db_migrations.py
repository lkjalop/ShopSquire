from __future__ import annotations

import os

from scripts.verify_db_migrations import _database_url_environment


def test_database_url_environment_overrides_and_restores_existing_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///demo.sqlite")

    with _database_url_environment("postgresql://migration-target"):
        assert os.environ["DATABASE_URL"] == "postgresql://migration-target"

    assert os.environ["DATABASE_URL"] == "sqlite:///demo.sqlite"


def test_database_url_environment_removes_temporary_value(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with _database_url_environment("postgresql://migration-target"):
        assert os.environ["DATABASE_URL"] == "postgresql://migration-target"

    assert "DATABASE_URL" not in os.environ
