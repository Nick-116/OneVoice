#!/usr/bin/env bash
# Restore a backup made by backup.sh into the running postgres container.
#   scripts/restore.sh backups/captions-20261015-031500.sql.gz
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:?usage: restore.sh <backup.sql.gz>}"
read -r -p "This replaces ALL data in the captions database with $file. Type 'restore' to continue: " ok
[[ "$ok" == "restore" ]] || { echo "aborted"; exit 1; }
docker compose stop admin worker ingest public
gunzip -c "$file" | docker compose exec -T postgres psql -U postgres -d captions -v ON_ERROR_STOP=1 >/dev/null
# Dumps are taken with --no-owner: hand ownership back to the app roles and re-apply grants.
docker compose exec -T postgres psql -U postgres -d captions -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO captions_admin', r.tablename);
  END LOOP;
  FOR r IN SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public' LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO captions_admin', r.sequence_name);
  END LOOP;
END $$;
SQL
docker compose run --rm migrate alembic upgrade head
docker compose run --rm migrate python -m captions.grants
docker compose up -d
echo "Restore complete."
