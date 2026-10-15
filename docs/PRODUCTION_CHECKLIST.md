# Production deployment checklist

## Server
- [ ] Ubuntu 24.04 LTS, unattended security upgrades on, SSH key-only login (`PasswordAuthentication no`)
- [ ] `ufw` allows only SSH inbound
- [ ] `docker compose ps` shows only the ports you intend (8080/8081/8082 on the right addresses)
- [ ] Provider backups/snapshots enabled

## Secrets & configuration
- [ ] `./scripts/generate-secrets.sh` run; `secrets/` is mode 700 and **not** in git
- [ ] `secrets/` and nightly `backups/` copied off-server
- [ ] `.env`: real `PUBLIC_BASE_URL` and `ADMIN_ORIGIN`; `COOKIE_SECURE=true` if served over HTTPS; `ADMIN_REQUIRE_MFA=true`
- [ ] Branding set in the dashboard (name, logo, color, fonts)

## Network / reverse proxy
- [ ] Ports: `*_BIND` set for your setup (local network `0.0.0.0`; reverse proxy `127.0.0.1`), see [Ports & reverse proxy](REVERSE_PROXY.md)
- [ ] Caption hostname allows only `/campus/*`, `/assets/*`, `/api/public/*`, `/branding/*`, `/favicon.svg`
- [ ] Dashboard is private (proxy login/SSO, local network only, or `ADMIN_BIND=127.0.0.1`)
- [ ] Audio input (only if using the Sender app) is reachable only from the church
- [ ] From cellular: `POST <caption site>/api/public/config` → 405; dashboard and audio not reachable

## Application
- [ ] Setup wizard completed (first admin, MFA, providers); at least two admins exist (lockout protection)
- [ ] Operators (production volunteers) created with role `operator`
- [ ] Deepgram + Azure keys saved; **Test translation** works for every enabled language
- [ ] Deepgram keyterms added (church name, pastors, towns, scripture books)
- [ ] Campuses, languages and recurring services entered; **Upcoming** list looks right (check a date after the next DST change)
- [ ] One sender per campus with *Allowed CIDRs* set; tokens installed on church computers
- [ ] Sender app: correct Dante channel, "Launch at login" + "Start streaming automatically" on, levels around −30 to −12 dBFS during speech
- [ ] QR codes printed from the dashboard and tested with iPhone and Android
- [ ] Provider data-retention/training opt-outs configured; transcript retention decision documented

## Rehearsal (before the first real service)
- [ ] Full rehearsal with a manual start: English partials appear in about 1 s; Spanish finals in about 2–5 s
- [ ] Unplug the sender's network for 30 s → phones show the "not connected" message → captions resume after reconnect
- [ ] Stop the service → phones show "service has ended"
- [ ] Load test with ≥ 200 viewers (`loadtest/sse_load.py`) during the rehearsal
- [ ] `./scripts/backup.sh` works and a restore was tested on a scratch VM
- [ ] Production staff briefed on Overview status colors, Start/Extend/Stop, and the troubleshooting table in OPERATIONS.md
