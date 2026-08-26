#!/usr/bin/env bash
# VectoTrace Database Backup Test Script
# Usage: ./scripts/test_restore.sh <backup_file>

set -euo pipefail

BACKUP_FILE=${1:-}
if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "Usage: $0 <path_to_backup_file>"
    exit 1
fi

if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Handle decryption if needed
DECRYPTED=false
if [[ "$BACKUP_FILE" == *.enc ]]; then
    if [ -z "${BACKUP_KEY:-}" ]; then
        echo "Error: Backup is encrypted but BACKUP_KEY is not set."
        exit 1
    fi
    echo "Decrypting backup for test..."
    DECRYPTED_FILE="${BACKUP_FILE%.enc}_test"
    openssl enc -d -aes-256-cbc -in "$BACKUP_FILE" -out "$DECRYPTED_FILE" -pass pass:"$BACKUP_KEY" -pbkdf2
    BACKUP_FILE="$DECRYPTED_FILE"
    DECRYPTED=true
fi

CONTAINER_NAME="vectotrace_test_db_$(date +%s)"
TEST_DB="test_restore_db"
TEST_USER="test_user"
TEST_PASS="test_pass"

echo "Starting disposable PostgreSQL container..."
docker run --name "$CONTAINER_NAME" -e POSTGRES_USER="$TEST_USER" -e POSTGRES_PASSWORD="$TEST_PASS" -e POSTGRES_DB="$TEST_DB" -d postgres:17-alpine > /dev/null

echo "Waiting for PostgreSQL to be ready..."
until docker exec "$CONTAINER_NAME" pg_isready -U "$TEST_USER" -d "$TEST_DB" > /dev/null 2>&1; do
    sleep 1
done

echo "Restoring backup into temporary container..."
if [[ "$BACKUP_FILE" == *.gz ]]; then
    zcat "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$TEST_USER" -d "$TEST_DB" > /dev/null
else
    cat "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$TEST_USER" -d "$TEST_DB" > /dev/null
fi

echo "Verifying restoration..."
# Simple verification: count tables in public schema
TABLE_COUNT=$(docker exec "$CONTAINER_NAME" psql -U "$TEST_USER" -d "$TEST_DB" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" | tr -d ' ')

if [ "$TABLE_COUNT" -gt 0 ]; then
    echo "Test Restore SUCCESS! Found $TABLE_COUNT tables in public schema."
    EXIT_CODE=0
else
    echo "Test Restore FAILED! No tables found in public schema."
    EXIT_CODE=1
fi

echo "Cleaning up temporary container..."
docker rm -f "$CONTAINER_NAME" > /dev/null

if [ "$DECRYPTED" = true ]; then
    rm -f "$BACKUP_FILE"
fi

exit $EXIT_CODE
