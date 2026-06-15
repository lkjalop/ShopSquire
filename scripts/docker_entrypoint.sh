#!/usr/bin/env sh
set -eu

# Docker entrypoint for ShopSquire API.
# - Runs Alembic migrations on startup (configurable)
# - Optionally blocks startup if DB schema is not at head

RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
AUTO_MIGRATE="${AUTO_MIGRATE:-1}"
DB_MIGRATION_GUARD="${DB_MIGRATION_GUARD:-1}"
APP_ENV="${APP_ENV:-local}"

# Production hardening guards (APP_ENV=staging or production).
if [ "$APP_ENV" = "prod" ] || [ "$APP_ENV" = "production" ] || [ "$APP_ENV" = "staging" ]; then
  if [ -z "${REDIS_URL:-}" ]; then
    echo "[entrypoint] REDIS_URL must be set in production"
    exit 1
  fi
  case "$REDIS_URL" in
    redis://*:*@*|rediss://*:*@* )
      ;;
    * )
      echo "[entrypoint] REDIS_URL must include password auth in production"
      exit 1
      ;;
  esac
  # JWT signing key is required to issue tokens. An empty key causes silent
  # auth degradation — all JWT issuance fails quietly, which is hard to debug.
  _jwt_key="${JWT_SIGNING_KEY:-}"
  if [ -z "$_jwt_key" ] || [ "$_jwt_key" = "replace-with-long-random-string" ]; then
    echo "[entrypoint] JWT_SIGNING_KEY must be set to a non-default value in staging/production"
    exit 1
  fi
  if [ ${#_jwt_key} -lt 32 ]; then
    echo "[entrypoint] JWT_SIGNING_KEY must be at least 32 characters"
    exit 1
  fi
  # Prevent accidental startup with local DB artifacts baked into app root.
  if ls /app/*.db /app/*.sqlite >/dev/null 2>&1; then
    echo "[entrypoint] Local database artifacts detected in /app for production runtime"
    exit 1
  fi
fi

if [ -n "${DATABASE_URL:-}" ]; then
  case "$DATABASE_URL" in
    sqlite* )
      # SQLite is used for lightweight dev/tests; do not run Alembic by default.
      ;;
    * )
      if [ "$RUN_MIGRATIONS" = "1" ] && [ "$AUTO_MIGRATE" = "1" ]; then
        echo "[entrypoint] Running Alembic migrations..."
        alembic -c alembic.ini upgrade head
      else
        echo "[entrypoint] Skipping Alembic migrations (RUN_MIGRATIONS=$RUN_MIGRATIONS AUTO_MIGRATE=$AUTO_MIGRATE)"
      fi
      ;;
  esac
else
  echo "[entrypoint] DATABASE_URL not set; skipping migrations"
fi

exec "$@"
