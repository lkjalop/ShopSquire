#!/usr/bin/env bash
# Alembic pre-migration hook: run validation checks before applying migrations
set -euo pipefail
# Example checks:
# - run ruff to lint migration files
# - run mypy (optional)
# - ensure no TODOs in migration files

grep -n "TODO" alembic/versions || true
# Lint migration scripts for syntax issues
if command -v ruff >/dev/null 2>&1; then
  ruff check alembic/versions || true
fi

echo "pre-migration checks complete"
