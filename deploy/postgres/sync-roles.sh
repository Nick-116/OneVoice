#!/bin/sh
# Make the database match ./secrets: create the per-service roles if missing and set every
# password from the secret files. Runs on EVERY start (see entrypoint.sh), so changing or
# regenerating secrets can never lock the services out of an existing database.
#   captions_admin  - owns the schema; used by migrations and the admin API
#   captions_worker - reads configuration, writes usage/transcripts (grants in migrations)
#   captions_ingest - reads sender credentials only (column-level grants in migrations)
# The public service has NO database role at all.
set -eu

secret() { cat "/run/secrets/$1"; }

psql -v ON_ERROR_STOP=1 -h /var/run/postgresql -U postgres -d captions -q \
  -v super_pw="$(secret db_superuser_password)" \
  -v admin_pw="$(secret db_admin_password)" \
  -v worker_pw="$(secret db_worker_password)" \
  -v ingest_pw="$(secret db_ingest_password)" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', r)
  FROM unnest(ARRAY['captions_admin', 'captions_worker', 'captions_ingest']) AS r
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) \gexec
ALTER ROLE postgres WITH PASSWORD :'super_pw';
ALTER ROLE captions_admin WITH LOGIN PASSWORD :'admin_pw';
ALTER ROLE captions_worker WITH LOGIN PASSWORD :'worker_pw';
ALTER ROLE captions_ingest WITH LOGIN PASSWORD :'ingest_pw';
ALTER DATABASE captions OWNER TO captions_admin;
ALTER SCHEMA public OWNER TO captions_admin;
REVOKE ALL ON DATABASE captions FROM PUBLIC;
GRANT CONNECT ON DATABASE captions TO captions_admin, captions_worker, captions_ingest;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO captions_worker, captions_ingest;
SQL
