# Operations: monitoring, backups, updates, troubleshooting

## What runs where

| Container | Role | Talks to |
|---|---|---|
| `public` | Caption site + read-only API + SSE fan-out | Redis (restricted ACL user) |
| `admin` | Dashboard + admin API | PostgreSQL (owner role), Redis, internet (translation test) |
| `ingest` | Audio WebSocket from church senders | PostgreSQL (sender credentials only), Redis (audio keys only) |
| `worker` | Schedule enforcement, STT, translation, metrics | PostgreSQL (read config, write usage), Redis, internet (APIs) |
| `postgres` | Configuration, schedules, users, usage | – |
| `redis` | Live caption pub/sub, audio buffer, status (in memory, no persistence) | – |
| `local-audio` (optional) | Capture from an audio interface on the server | Redis (audio keys only) |

All containers restart automatically (`unless-stopped`) and have health checks. If the worker stops publishing, the public site shows "temporarily unavailable" instead of stale data.

## During a service: what to watch (Admin → Overview)

* **Phase / Captions:**
  - `Live / Live` is the goal.
  - `Waiting` means audio is arriving but speech recognition hasn't produced text yet. It's normal for the first seconds, or while nobody is speaking.
* **Audio disconnected:**
  - The sender isn't connected, or is sending pure digital silence. Digital silence usually means the Dante subscription is broken; check Dante Controller.
  - Phones show *"The streaming service is currently not connected. Please check with the production team."*
* **STT unavailable:** the speech provider is failing (key, quota, outage). Recent Errors shows the reason. The worker retries automatically with backoff.
* **Translation `failing` for a language:** only that language is affected. Viewers see a small notice, and it recovers automatically.
* **Latency:** STT final p95 under about 1.5 s and end-to-end under about 4 s is healthy.

Controls:

* **Start service now** for unscheduled events.
* **Extend +15/+30** when a service runs long.
* **Stop service** to end early. Phones switch to the ended screen immediately.

## Logs

All services log JSON to stdout, rotated by Docker (5 × 20 MB per container).

```bash
docker compose logs -f worker
docker compose logs --since 1h ingest | grep '"level": "WARNING"'
docker compose logs public admin ingest | grep '"logger": "security"'   # auth failures, rejected senders, CSRF, limits
```

## Backups

Only PostgreSQL holds durable data. Redis is intentionally ephemeral.

```bash
./scripts/backup.sh                                   # backups/captions-YYYYmmdd-HHMMSS.sql.gz (keeps 14 days)
crontab -e   # 15 3 * * * cd /opt/onevoice && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Copy `backups/` **and** `secrets/` off the server, e.g. with `rclone` to cloud storage or your provider's snapshots.

Without `secrets/app_secret_key`, stored provider keys and MFA enrolments can't be decrypted. You would have to re-enter the keys and re-enrol MFA.

Restore:
```bash
./scripts/restore.sh backups/captions-20261015-031500.sql.gz
```

## Updating

Use **Admin → Updates** (see [UPDATES.md](UPDATES.md)). It:

1. backs up the database;
2. pulls the latest `main` from GitHub;
3. rebuilds and restarts;
4. rolls back automatically if anything fails.

Update outside service times when possible.

Manual equivalent on the server:
```bash
sudo python3 scripts/updater.py apply
```

## Common problems

| Symptom | Check |
|---|---|
| Sender "Authentication failed" | Token copied fully? Sender revoked? Church public IP changed (proxy IP rule and sender *Allowed CIDRs*)? Campus set to *local* audio (the Sender says so)? |
| Sender connected, phones say "not connected" | Level meter flat at −120 dBFS means digital silence. Check the Dante route and the channel selected in the sender app. |
| "Waiting for live captions…" never clears | Recent Errors → STT key/quota. Test with the `simulated` STT provider to isolate. |
| One language missing on phones | Disabled in Languages, not enabled for that campus, or not supported by the current translation provider. |
| Phones show countdown during the service | Schedule time zone / weekday wrong, or the occurrence was cancelled. Check Services → Upcoming. Use **Start service now** as a fallback. |
| Admin login loops | `ADMIN_ORIGIN` must exactly match the dashboard address in the browser (several can be listed, comma-separated). `COOKIE_SECURE=true` only works over HTTPS; use `false` for plain `http://`. |
| Locked out of MFA | `docker compose run --rm admin python -m captions.admin.cli reset-mfa --username NAME` |
