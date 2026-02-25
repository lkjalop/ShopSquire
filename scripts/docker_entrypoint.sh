#!/usr/bin/env sh
set -eu

# Docker entrypoint for ShopSquire API.
# - Runs Alembic migrations on startup (configurable)
# - Optionally blocks startup if DB schema is not at head

RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
AUTO_MIGRATE="${AUTO_MIGRATE:-1}"
DB_MIGRATION_GUARD="${DB_MIGRATION_GUARD:-1}"
APP_ENV="${APP_ENV:-local}"

# Production hardening guards.
if [ "$APP_ENV" = "prod" ] || [ "$APP_ENV" = "production" ]; then
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
