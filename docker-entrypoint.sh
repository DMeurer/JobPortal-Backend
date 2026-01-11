#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."
while ! pg_isready -h "$DATABASE_HOST" -p "$DATABASE_PORT" -U "$DATABASE_USER" > /dev/null 2>&1; do
    echo "PostgreSQL is unavailable - sleeping"
    sleep 1
done

echo "PostgreSQL is up - executing command"

# Run migrations
echo "Running database migrations..."
alembic upgrade head

# Execute the main command
exec "$@"
