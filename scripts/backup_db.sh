#!/usr/bin/env bash
# VectoTrace Database Backup Script
# Usage: ./scripts/backup_db.sh [retention_days]

set -euo pipefail

# Load environment if running locally, otherwise rely on Compose environment if run inside container
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

DB_USER=${DB_USER:-vectotrace_user}
DB_NAME=${DB_NAME:-vectotrace_db}
BACKUP_DIR=${BACKUP_DIR:-./backups}
RETENTION_DAYS=${1:-7}

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/vectotrace_${TIMESTAMP}.sql.gz"

echo "Starting backup of database $DB_NAME..."

# Execute pg_dump inside the postgres container
if docker compose exec -T postgressql pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"; then
    echo "Backup successful: $BACKUP_FILE"
else
    echo "Backup failed!"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Encryption if BACKUP_KEY is configured
if [ -n "${BACKUP_KEY:-}" ]; then
    echo "Encrypting backup..."
    openssl enc -aes-256-cbc -salt -in "$BACKUP_FILE" -out "$BACKUP_FILE.enc" -pass pass:"$BACKUP_KEY" -pbkdf2
    rm -f "$BACKUP_FILE"
    echo "Encrypted backup created: $BACKUP_FILE.enc"
fi

# Retention cleanup
echo "Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -type f -name "vectotrace_*.sql.gz*" -mtime +$RETENTION_DAYS -exec rm -f {} \;

echo "Backup process complete."
