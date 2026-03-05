#!/usr/bin/env bash
# scripts/pg_backup.sh — Automated Postgres backup for ShopSquire.
#
# Usage:
#   PGPASSWORD=<pw> ./scripts/pg_backup.sh            # defaults
#   BACKUP_DIR=/mnt/nfs ./scripts/pg_backup.sh         # custom dir
#   BACKUP_RETENTION_DAYS=14 ./scripts/pg_backup.sh    # custom retention
#
# Designed to be called via cron or the db-backup Docker service.
# Exit codes: 0 = success, 1 = pg_dump failed, 2 = upload failed (if S3)

set -euo pipefail

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGDATABASE="${PGDATABASE:-shopsquire}"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/shopsquire}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILENAME="shopsquire_${PGDATABASE}_${TIMESTAMP}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

mkdir -p "${BACKUP_DIR}"

echo "[backup] Starting pg_dump for ${PGDATABASE}@${PGHOST}:${PGPORT} ..."

pg_dump \
  -h "${PGHOST}" \
  -p "${PGPORT}" \
  -U "${PGUSER}" \
  -d "${PGDATABASE}" \
  --no-owner \
  --no-acl \
  --format=plain \
  | gzip > "${FILEPATH}"

SIZE=$(stat --printf='%s' "${FILEPATH}" 2>/dev/null || stat -f '%z' "${FILEPATH}" 2>/dev/null || echo "?")
echo "[backup] Created ${FILEPATH} (${SIZE} bytes)"

# ── Optional: upload to S3 ──
if [ -n "${S3_BACKUP_BUCKET:-}" ]; then
  S3_PATH="s3://${S3_BACKUP_BUCKET}/pg-backups/${FILENAME}"
  echo "[backup] Uploading to ${S3_PATH} ..."
  aws s3 cp "${FILEPATH}" "${S3_PATH}" --sse aws:kms || {
    echo "[backup] S3 upload failed" >&2
    exit 2
  }
  echo "[backup] Upload complete"
fi

# ── Prune old local backups ──
echo "[backup] Pruning backups older than ${BACKUP_RETENTION_DAYS} days ..."
find "${BACKUP_DIR}" -name 'shopsquire_*.sql.gz' -mtime "+${BACKUP_RETENTION_DAYS}" -delete 2>/dev/null || true

echo "[backup] Done"
