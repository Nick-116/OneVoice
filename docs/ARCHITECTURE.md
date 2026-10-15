# Architecture

## Components

```
 CHURCH (per campus)                                VPS (Docker Compose, no published ports)
 ┌──────────────────────────┐                        ┌────────────────────────────────────────────────────────────┐
 │ Yamaha console speech mix│                        │                                                            │
 │        │ Dante           │   ws(s) to port 8082   │           ingest:8082 ──XADD (bounded)──► Redis stream     │
 │ Dante VSC / AVIO USB     │──(or local input)───────►│                                             │              │
 │ Church Audio Sender app  │   + per-campus token   │                                worker ◄─────┘              │
 └──────────────────────────┘                        │   schedule engine ─ STT session (Deepgram) ─ segmenter      │
                                                     │                       └─ 1 translation channel per viewed lang│
 PHONES ─ <caption site>/campus/<campus> ───────────►│  port 8080 public ◄── Redis pub/sub cap:<campus>:<lang>  │
           (SSE, GET only)                           │            one subscription, in-process fan-out to viewers  │
 STAFF ─ dashboard (login+TOTP) ────────────────────►│  port 8081 admin ──► PostgreSQL (config) ──► worker    │
                                                     └────────────────────────────────────────────────────────────┘
```

| Concern | Where it is enforced |
|---|---|
| Only the caption site is public | Separate containers, ports (`*_BIND`) and Docker networks |
| Public API is read-only | Method allow-list middleware (GET/HEAD only); no DB credentials; Redis ACL allows reads + viewer counters only; no admin code routes |
| Captions only during services | Worker starts/stops pipelines from the schedule; ingest forwards audio only while `campus:live:<id>` exists; public refuses streams unless status is live and closes them when it ends |
| Campus isolation | Audio keyed by campus id from the authenticated sender token (never client-supplied); separate channels `cap:<slug>:<lang>`; tests verify no cross-delivery |
| Admin authorization | App sessions + TOTP + CSRF + roles |
| Unauthorized audio injection | Sender tokens (SHA-256 hashed, revocable instantly), per-sender CIDR allowlist, frame size and byte-rate limits, one active connection per campus |

## Why Redis

The public, ingest, worker and admin services are separate processes in separate containers, so they need a message bus. Redis gives:

* pub/sub for captions and status (fan-out without touching PostgreSQL);
* streams with `MAXLEN` for the bounded audio buffer between ingest and worker (about 30 s maximum, so there's never a long backlog);
* small TTL keys for live status and viewer counts.

It runs **without persistence** on an internal network, with the default user disabled and one ACL user per service. PostgreSQL holds only configuration, schedules, users, usage and optional transcripts.

## Live data flow and latency budget

1. **Sender:** captures one Dante channel, resamples to 16 kHz mono and sends 100 ms PCM frames over one persistent WebSocket. Adds about 100–150 ms.
2. **Ingest:**
   - authenticates the sender;
   - measures levels, and flags *digital silence* when every sample is exactly zero;
   - `XADD`s audio frames to the campus stream only while the service is live;
   - updates the audio status hash.
3. **Worker:**
   - reads the stream, skipping anything older than 2 s, so after a hiccup live audio wins over backlog;
   - sends the audio to the STT session;
   - turns STT events (interim / stable / endpoint) into partial and final segments in the `Segmenter`;
   - publishes source-language captions immediately: partials in about 0.3–0.8 s.
4. **Translation:** each final segment goes to every *active* language channel. A channel is one sequential translator per language, with timeout, a single retry and a circuit breaker. Each translated final is published about 1.5–4 s after speech.
5. **Public:**
   - holds one pattern subscription and fans out to every viewer queue (bounded; slow clients are dropped, never blocking others);
   - reports viewer counts per language every 2 s, which tells the worker which languages to translate.

## Status model (public)

* `phase`: `upcoming` (countdown) → `live` → `ended` (thank-you message plus next service) → `upcoming`/`idle`.
* While live, `captions` is one of:
  - `live`
  - `waiting`: audio is fine, no text yet
  - `disconnected`: no audio, or digital silence; shows the "please check with the production team" message
  - `unavailable`: STT failing for more than 8 s

## Database schema (PostgreSQL)

| Table | Purpose |
|---|---|
| `campuses`, `campus_languages` | campus slug/name/timezone/source language, enabled languages, transcript retention flag |
| `languages` | catalog (code, native name, RTL, enabled, provider code overrides); seeded with 12 languages, extensible |
| `service_schedules` | recurring weekly services (weekday, local start/end, IANA timezone, early access, language subset, validity range) |
| `service_events` | one-time special/holiday/manual services (UTC instants), cancellable |
| `schedule_exceptions` | per-date cancel or re-time (stop early / extend) of a recurring service |
| `audio_senders` | per-campus sender credentials (token SHA-256, CIDR allowlist, revoked_at) |
| `admin_users`, `admin_sessions` | argon2id passwords, roles, encrypted TOTP secrets; hashed session tokens with CSRF token |
| `provider_configs` | selected STT/translation provider, settings, encrypted API key |
| `app_settings` | general settings (JSON) |
| `usage_records` | hourly metered STT seconds / translation characters and estimated cost |
| `transcripts` | only if retention is enabled; purged after N days |
| `audit_log` | every administrative change with user and IP |

Database roles: `captions_admin` (owner; migrations and admin), `captions_worker` (read config, write usage/transcripts), `captions_ingest` (column-level read of sender credentials). The public service has no database access.

## Scheduling rules

* Recurring services are stored as **local wall-clock times** in an IANA zone (default `America/New_York`) and expanded per date with `zoneinfo`. "9:00 AM Sunday" stays 9:00 AM local across DST. Non-existent times in the spring-forward gap move forward. Ambiguous fall-back times use the first occurrence.
* **Early access** opens captions N minutes before the official start. The countdown still targets the official start.
* **Overlaps** (e.g. a manual start or an extension) resolve to the window ending last.
* **Manual stop:** a recurring service gets a `modify` exception (end = now). A one-time event has its `end_at` set. If the stop happens during early access, the occurrence is cancelled.

## Extending later

* **Self-hosted STT/translation:** add a provider class (see PROVIDERS_AND_PRIVACY.md) that points at a GPU host. Nothing else changes.
* **More campuses or languages:** dashboard only.
* **Horizontal scale:** run several `public` replicas. Each has its own subscription and reports its own viewer-count key; the worker sums them. A single `public` process comfortably serves thousands of SSE clients.
