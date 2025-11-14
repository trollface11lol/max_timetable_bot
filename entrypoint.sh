#!/bin/bash
set -e

echo "Waiting for database"
until pg_isready -h postgres_max -p 5432 -U max_bot; do
  sleep 1
done

echo "Running migrations"
alembic upgrade head

echo "Starting process"

exec "$@"