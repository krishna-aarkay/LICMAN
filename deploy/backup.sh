#!/usr/bin/env bash
# /opt/licman/deploy/backup.sh — rotating Mongo backup
# Called weekly by systemd timer. Keeps last 14 archives.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/licman}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/licman/deploy}"

mkdir -p "$BACKUP_DIR"

cd "$COMPOSE_DIR"
# shellcheck disable=SC1091
source .env

STAMP=$(date +%F-%H%M)
OUTFILE="${BACKUP_DIR}/licman-${STAMP}.gz"

echo "[$(date)] Starting Mongo backup → ${OUTFILE}"
docker compose exec -T mongo mongodump \
    --uri="mongodb://${MONGO_INITDB_ROOT_USERNAME}:${MONGO_INITDB_ROOT_PASSWORD}@localhost:27017/?authSource=admin" \
    --archive --gzip > "${OUTFILE}"
chmod 600 "${OUTFILE}"

# Rotate
find "${BACKUP_DIR}" -type f -name 'licman-*.gz' -mtime "+${KEEP_DAYS}" -delete

echo "[$(date)] Backup complete. Stored copies:"
ls -lh "${BACKUP_DIR}" | tail -10
