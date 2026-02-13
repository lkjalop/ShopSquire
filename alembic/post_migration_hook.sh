#!/usr/bin/env bash
# Alembic post-migration hook: smoke tests and quick validations
set -euo pipefail
# Run a quick DB sanity query
psql "$DATABASE_URL" -c "SELECT 1;"
# Optionally run a small SQL check to ensure new tables exist
psql "$DATABASE_URL" -c "SELECT to_regclass('public.evidence_bundles');"
psql "$DATABASE_URL" -c "SELECT to_regclass('public.human_review_tasks');"

echo "post-migration checks complete"
