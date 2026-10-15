#!/bin/sh
# Starts PostgreSQL normally, then syncs roles/passwords from ./secrets (sync-roles.sh).
# The health check waits for the marker file, so other services only connect afterwards.
set -eu
MARKER=/tmp/onevoice-roles-synced
rm -f "$MARKER"

docker-entrypoint.sh "$@" &
pid=$!
trap 'kill -TERM "$pid" 2>/dev/null' TERM INT

# Wait for the real server. Over TCP on purpose: during first-time initialisation the
# temporary server listens on the socket only, and must not be touched.
until pg_isready -q -h 127.0.0.1 -U postgres -d captions; do
  if ! kill -0 "$pid" 2>/dev/null; then wait "$pid"; exit $?; fi
  sleep 1
done

if sh /onevoice/sync-roles.sh; then
  touch "$MARKER"
  echo "onevoice: database roles synced with ./secrets"
else
  echo "onevoice: FAILED to sync database roles with ./secrets" >&2
fi
wait "$pid"
