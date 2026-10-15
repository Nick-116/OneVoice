#!/bin/sh
# Runs once, on first database initialisation (empty data volume).
# Creates one login role per service so each gets least-privilege access:
#   captions_admin  - owns the schema; used by migrations and the admin API
#   captions_worker - reads configuration, writes usage/transcripts (grants in migration 0001)
#   captions_ingest - reads sender credentials only (column-level grants in migration 0001)
# The public service has NO database role at all.
set -eu

ADMIN_PW="$(cat /run/secrets/db_admin_password)"
WORKER_PW="$(cat /run/secrets/db_worker_password)"
INGEST_PW="$(cat /run/secrets/db_ingest_password)"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v admin_pw="$ADMIN_PW" -v worker_pw="$WORKER_PW" -v ingest_pw="$INGEST_PW" <<'SQL'
CREATE ROLE captions_admin LOGIN PASSWORD :'admin_pw';
CREATE ROLE captions_worker LOGIN PASSWORD :'worker_pw';
CREATE ROLE captions_ingest LOGIN PASSWORD :'ingest_pw';
ALTER DATABASE captions OWNER TO captions_admin;
ALTER SCHEMA public OWNER TO captions_admin;
REVOKE ALL ON DATABASE captions FROM PUBLIC;
GRANT CONNECT ON DATABASE captions TO captions_admin, captions_worker, captions_ingest;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO captions_worker, captions_ingest;
SQL
