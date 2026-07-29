from __future__ import annotations

from pathlib import Path


def test_api_does_not_run_migrations_and_waits_for_migration_job() -> None:
    source = Path("docker-compose.yml").read_text(encoding="utf-8")
    api = source.split("\n  api:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    migrate = source.split("\n  migrate:\n", 1)[1].split("\n  db:\n", 1)[0]

    assert 'AUTO_MIGRATE: "0"' in api
    assert "migrate:\n        condition: service_completed_successfully" in api
    assert 'command: ["alembic", "upgrade", "head"]' in migrate
    assert 'restart: "no"' in migrate
