#!/usr/bin/env bash
# Nightly PostgreSQL backup. Keeps 14 days by default.
#   scripts/backup.sh            -> backups/captions-YYYYmmdd-HHMMSS.sql.gz
# Cron (as the deploy user):
#   15 3 * * * cd /opt/onevoice && ./scripts/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p backups
chmod 700 backups
out="backups/captions-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T postgres pg_dump -U postgres --clean --if-exists --no-owner captions | gzip -9 > "$out.tmp"
mv "$out.tmp" "$out"
chmod 600 "$out"
find backups -name 'captions-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "$(date -Is) backup written: $out ($(du -h "$out" | cut -f1))"
