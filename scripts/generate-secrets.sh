#!/usr/bin/env bash
# Creates ./secrets/* with strong random values. Never overwrites an existing file.
# Provider API keys are created empty; fill them in or enter keys in the admin dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p secrets
chmod 700 secrets

gen() {
  local f="secrets/$1"
  if [[ -s "$f" ]]; then echo "keep   $f"; return; fi
  openssl rand -hex 32 | tr -d '\n' > "$f"
  echo "create $f"
}

for name in app_secret_key db_superuser_password db_admin_password db_worker_password db_ingest_password \
            redis_worker_password redis_admin_password redis_ingest_password redis_public_password; do
  gen "$name"
done

for name in deepgram_api_key azure_translator_key; do
  f="secrets/$name"
  [[ -e "$f" ]] || { : > "$f"; echo "create $f (empty - add your key or use the admin dashboard)"; }
done

# Containers run as non-root users and need to read their own secret files.
# The directory itself stays 700 so other host users cannot reach them.
chmod 644 secrets/*
echo "Done. Back up ./secrets securely - losing app_secret_key makes stored provider keys and MFA secrets unreadable."
