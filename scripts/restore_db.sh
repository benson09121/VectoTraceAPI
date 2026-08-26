#!/usr/bin/env bash
# VectoTrace Database Restore Script
# Usage: ./scripts/restore_db.sh <backup_file>

set -euo pipefail

if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

DB_USER=${DB_USER:-vectotrace_user}
DB_NAME=${DB_NAME:-vectotrace_db}
BACKUP_FILE=${1:-}

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "Usage: $0 <path_to_backup_file>"
    exit 1
fi

echo "Warning: This will DROP and RECREATE the database $DB_NAME!"
read -p "Are you sure you want to continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Handle decryption if needed
if [[ "$BACKUP_FILE" == *.enc ]]; then
    if [ -z "${BACKUP_KEY:-}" ]; then
        echo "Error: Backup is encrypted but BACKUP_KEY is not set."
        exit 1
    fi
    echo "Decrypting backup..."
    DECRYPTED_FILE="${BACKUP_FILE%.enc}"
    openssl enc -d -aes-256-cbc -in "$BACKUP_FILE" -out "$DECRYPTED_FILE" -pass pass:"$BACKUP_KEY" -pbkdf2
    BACKUP_FILE="$DECRYPTED_FILE"
fi

echo "Stopping application containers..."
docker compose stop django_backend celery_worker celery_beat nextjs_frontend || true

echo "Dropping and recreating database..."
docker compose exec -T postgressql psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
docker compose exec -T postgressql psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME;"

echo "Restoring data..."
if [[ "$BACKUP_FILE" == *.gz ]]; then
    zcat "$BACKUP_FILE" | docker compose exec -T postgressql psql -U "$DB_USER" -d "$DB_NAME"
else
    cat "$BACKUP_FILE" | docker compose exec -T postgressql psql -U "$DB_USER" -d "$DB_NAME"
fi

echo "Restarting application containers..."
docker compose start django_backend celery_worker celery_beat nextjs_frontend || true

echo "Restore complete."

# Cleanup decrypted file if we created it
if [[ "${1:-}" == *.enc ]]; then
    rm -f "$BACKUP_FILE"
fi
