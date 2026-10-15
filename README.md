# OneVoice: Church Live Captions & Translation

A self-hosted platform for live captioning and translating church services across multiple campuses.

Congregation members:
1. scan a campus QR code;
2. pick their language;
3. read live captions on their phone.

No app, no account, no tracking.

```
Yamaha console → Dante → Church Audio Sender ──wss──► VPS ──► Deepgram (speech) ──► Azure (translation)
                                                          └──► phones via Server-Sent Events
```

| Part | Directory | Exposure |
|---|---|---|
| Public caption website + read-only API | `public-web/`, `backend/captions/public/` | **Public**: `captions.<domain>` (port 8080) |
| Administration dashboard + API | `admin-web/`, `backend/captions/admin/` | Private: `admin.<domain>` (port 8081, Pangolin SSO + app login + TOTP) |
| Audio ingest | `backend/captions/ingest/` | Private: `audio.<domain>` (port 8082, church IPs + sender token) |
| Transcription / translation worker | `backend/captions/worker/`, `backend/captions/providers/` | Internal only |
| Church Audio Sender (macOS/Windows) | `sender/` | Runs at the church |
| PostgreSQL, Redis | `compose.yml` | Internal only |

## Highlights
* **Scheduling is enforced by the backend:**
  - recurring services that stay correct across DST;
  - one-time, holiday and cancelled services;
  - manual start, stop and extend;
  - an early-access window;
  - a countdown before the service, a thank-you screen after it, and no processing (or cost) outside service windows.
* **Honest status:** viewers see "Waiting for live captions…", or "The streaming service is currently not connected. Please check with the production team." Captions are never shown as live when the audio is down.
* **One translation per language**, only for languages someone is watching right now. 100 Spanish viewers cost the same as one.
* **Multi-campus:** each campus has its own schedule, audio sender, languages, QR code, status and stream, isolated end to end.
* **Security:**
  - only the caption site is public;
  - the public container is GET-only, with no database credentials and a restricted Redis ACL;
  - separate internal networks and per-service DB/Redis credentials;
  - non-root, read-only containers;
  - CSP and security headers;
  - CSRF protection, argon2id passwords and TOTP MFA;
  - revocable, IP-restricted sender tokens.
* **Provider abstraction:**
  - speech: Deepgram, AssemblyAI or simulated;
  - translation: Azure, Google or simulated;
  - a self-hosted model can be added later as one class.
* **Self-service branding:** church name, logo and button color are set in the dashboard. Shades are adjusted automatically for readable contrast.
* **One-click updates** from GitHub, with an automatic database backup and rollback (the dashboard itself never gets Docker access).
* **Measured latency** (p50/p95 per stage and language), usage metering and cost estimates in the dashboard.

## Documentation
* [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): VPS sizing (no GPU) and step-by-step install on Ubuntu
* [docs/PANGOLIN.md](docs/PANGOLIN.md): exactly which resources are public and which are private
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): components, data flow, schema, security boundaries
* [docs/API.md](docs/API.md): public, admin and ingest API reference
* [docs/PROVIDERS_AND_PRIVACY.md](docs/PROVIDERS_AND_PRIVACY.md): providers, pricing, cost controls, latency strategy, privacy
* [docs/OPERATIONS.md](docs/OPERATIONS.md): monitoring, logs, backups, updates, troubleshooting
* [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md)
* [docs/UPDATES.md](docs/UPDATES.md): installing updates from GitHub
* [docs/TESTING.md](docs/TESTING.md): test suites, simulated mode, load testing
* [sender/README.md](sender/README.md): audio sender install, Dante setup, packaging

## Quick start (production)
```bash
git clone https://github.com/Nick-116/OneVoice.git /opt/church-captions && cd /opt/church-captions
./scripts/generate-secrets.sh
cp .env.example .env            # domains + Pangolin Newt credentials
APP_COMMIT=$(git rev-parse HEAD) docker compose up -d --build
docker compose run --rm admin python -m captions.admin.cli create-user --username you --role admin
```
Then set up the three Pangolin resources ([docs/PANGOLIN.md](docs/PANGOLIN.md)), install the updater ([docs/UPDATES.md](docs/UPDATES.md)), and configure everything else, including branding, in the dashboard.

## Never committed to Git
`.env`, `secrets/` (passwords, keys, tokens), `backups/`, `updater/` (runtime state) and uploaded logos are all in `.gitignore`. Provider API keys and the church logo live in the database, so they're never in the repository.
