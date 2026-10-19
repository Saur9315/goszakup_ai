#!/usr/bin/env bash
set -euo pipefail

dump="$(realpath "${1:?usage: deploy/restore-dump.sh goszakup-YYYY-MM-DD.dump}")"
cd "$(dirname "$0")/.."
list="$(mktemp)"
trap 'rm -f "$list"' EXIT

psql() { docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }

docker compose up -d --wait postgres
psql <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'goszakup_api') THEN
    CREATE ROLE goszakup_api NOLOGIN;
  END IF;
END $$;
SQL
docker compose exec -T postgres pg_restore -l < "$dump" | grep -v "MATERIALIZED VIEW DATA" > "$list"
docker compose cp "$list" postgres:/tmp/restore.list
docker compose exec -T postgres sh -c \
  'pg_restore -L /tmp/restore.list --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$dump"
echo "ANALYZE;" | psql
docker compose run --rm migrate
docker compose run --rm worker marts refresh
docker compose up -d
