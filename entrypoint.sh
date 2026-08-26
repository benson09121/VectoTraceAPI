#!/usr/bin/env bash
set -e

# Wait for Postgres. compose's service_healthy covers the API, but the worker
# and beat can still race a database that is accepting connections before it
# has finished recovery.
if [ -n "$DB_HOST" ]; then
  echo "Waiting for database at $DB_HOST:${DB_PORT:-5432}..."
  until python -c "
import os, socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect((os.environ['DB_HOST'], int(os.environ.get('DB_PORT', 5432))))
except OSError:
    sys.exit(1)
" 2>/dev/null; do
    sleep 1
  done
fi

# Only the API container migrates. If the worker and beat did it too they would
# race each other applying the same migrations on startup.
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Running database migrations"
  python manage.py migrate --noinput
fi

echo "Collecting static files"
python manage.py collectstatic --noinput

exec "$@"
