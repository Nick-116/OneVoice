# API Reference

Three separate HTTP services, each its own container, port and Pangolin resource.

| Service | Port | Pangolin resource | Who |
|---|---|---|---|
| public-web | 8080 | `captions.example.com` (public) | congregation phones |
| admin | 8081 | `admin.example.com` (private, SSO) | staff |
| ingest | 8082 | `audio.example.com` (private, IP allowlist) | audio sender app |

All timestamps are ISO-8601 UTC strings ending in `Z` unless noted; `server_time`, `ts`, `*_at` numeric fields are Unix epoch seconds (float).

---

## 1. Public API (port 8080) — GET/HEAD only

Every other method returns `405`. No cookies, no auth, no writes.

### `GET /api/public/config`
```json
{ "church_name": "Grace Church", "campuses": [ {"slug": "east-hartford", "name": "East Hartford"} ] }
```

### `GET /api/public/campus/{slug}`
`404` unknown campus. `503` with `{"slug", "phase":"unavailable", "server_time"}` if the backend worker is not publishing.
```json
{
  "slug": "east-hartford",
  "name": "East Hartford",
  "timezone": "America/New_York",
  "source_language": "en",
  "default_language": "en",
  "phase": "live",                       // live | upcoming | ended | idle
  "captions": "live",                    // only when phase=live: live | waiting | disconnected | unavailable ; null otherwise
  "service": {"key": "r3-2026-10-18", "name": "Sunday 9 AM", "start": "...Z", "end": "...Z"},   // null unless live
  "next": {"name": "Sunday 11 AM", "start": "...Z", "window_start": "...Z"},                     // or null
  "languages": [ {"code": "en", "name": "English", "rtl": false}, {"code": "ar", "name": "العربية", "rtl": true} ],
  "server_time": 1760000000.123
}
```
Caption states to show the viewer:
* `live` – show captions.
* `waiting` – audio OK, transcription warming up → "Waiting for live captions…"
* `disconnected` – no audio reaching the server (or pure digital silence) → "The streaming service is currently not connected. Please check with the production team."
* `unavailable` – speech recognition provider failing → "Live captions are temporarily unavailable. We're working to restore them."

`countdown` = `next.window_start` (when captions open) vs `next.start` (official start). Show "Service starts in N minutes" against `next.start`; switch to live when `phase` becomes `live` (poll status; when local countdown to `window_start` hits 0, poll every 2–3 s).
Use `server_time` to correct the phone's clock: `offset = server_time - Date.now()/1000` at fetch time.

### `GET /api/public/campus/{slug}/stream?lang={code}` — Server-Sent Events
Only while `phase == "live"`, otherwise `409` with the status JSON body. `404` if language not offered. `429/503` when connection limits are hit (retry with backoff).

Events (each `data:` is one JSON line):
* `event: status` – the status object above. Sent first, and whenever it changes. If `phase != "live"` the server then closes the stream; the client should show the ended/upcoming screen and resume polling.
* `event: backlog` – JSON array of recent final caption messages (oldest first) so a late joiner has context.
* `event: caption` – a caption message:
  ```json
  {"t":"caption","occ":"r3-2026-10-18","id":42,"final":false,"lang":"es","text":"…","ts":1760000000.1,"lat":850}
  ```
  `id` is a segment sequence number within the occurrence `occ`. A **partial** (`final:false`) for id N replaces any previous partial; a **final** for id N replaces the partial N and is permanent. A partial with empty text means "clear the partial line". Ignore messages whose `occ` differs from the current service (reset on change). Render `text` as plain text only.
* `event: caption` with `{"t":"notice","code":"translation_unavailable"|"translation_restored","lang":"es",...}` – show/hide a small localized banner "Translation is temporarily unavailable…".
* Comment lines `: keepalive` every 15 s.

The browser's EventSource gives up on non-200 responses, so clients should manage reconnection themselves (exponential backoff 1 s → 15 s with jitter, re-fetch status first).

### `GET /branding/logo[?v=<logo_version>]`
The church logo uploaded in the dashboard (PNG), falling back to a file in `branding/`. `404` if none. With `?v=` it's cached as immutable.

`/api/public/config` also returns `theme` (accent palette, hex per shade) and `logo_version`.

---

## 2. Admin API (port 8081)

Session cookie (`__Host-cc_admin`, HttpOnly, Secure, SameSite=Strict). All requests use `credentials: "same-origin"`.
Every non-GET request must send header `X-CSRF-Token: <csrf_token>` (from login / `/api/auth/me` / mfa responses — it changes when the session rotates after MFA). Errors are `{"detail": "..."}` (422 validation errors have `detail` as an array of `{loc,msg}`).
`401` → show login. `403 "Multi-factor authentication required"` → show MFA screen.
Roles: `admin` (everything) and `operator` (view + live controls: start/stop/extend/cancel/restore occurrences, test translation). Endpoints marked **admin** return 403 for operators.

### Auth
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/auth/login` | `{username, password}` | `{user, mfa, csrf_token}`; `mfa` = `ok` \| `required` (enter code) \| `setup_required` (enrol) |
| GET | `/api/auth/me` | – | same shape; 401 if not logged in |
| POST | `/api/auth/mfa/verify` | `{code:"123456"}` | `{user, mfa:"ok", csrf_token}` (new session cookie) |
| POST | `/api/auth/mfa/setup` | – | `{secret, otpauth_uri, qr_svg}` (`qr_svg` is an inline `<svg>` string; render via `<img src={"data:image/svg+xml;utf8,"+encodeURIComponent(qr_svg)}>`, never innerHTML) |
| POST | `/api/auth/mfa/enable` | `{code}` | `{user, mfa:"ok", csrf_token}` |
| POST | `/api/auth/logout` | – | `{ok}` |
| POST | `/api/auth/password` | `{current_password, new_password}` | `{ok}` |

`user` = `{id, username, display_name, role, mfa_enabled}`.

### Overview & monitoring
`GET /api/overview` →
```json
{
 "worker": {"alive": true, "heartbeat": 1760000000.0},
 "campuses": [{
   "campus": {campus},
   "status": {                      // null if worker hasn't reported
     "phase": "live", "captions": "live",
     "service": {...}|null, "next": {...}|null,
     "viewers": {"es": 12, "en": 40},
     "pipeline": null | {
        "occurrence": "r3-2026-10-18", "stt": "idle|connecting|connected|error", "stt_error": null,
        "stt_connected_since": 1760.., "first_result_at": .., "last_caption_at": .., "segments": 120,
        "translation": {"es": "ok", "fr": "failing"},
        "metrics": {"stt_partial_ms": {"p50":..,"p95":..,"n":..}, "stt_final_ms": {...},
                    "translate_ms": {"es": {...}}, "end_to_end_ms": {"es": {...}}}
     },
     "stt_provider": "deepgram", "stt_configured": true,
     "translation_provider": "azure", "translation_configured": true, "updated": 1760..
   },
   "audio": {audio}
 }],
 "recent_errors": [{"at":.., "component":"stt","campus_id":1,"message":"..."}],
 "usage_month": {"stt_minutes": 312.5, "translation_chars": 1200000, "est_cost_usd": 14.2},
 "server_time": 1760..
}
```
`audio` = `{connected, sender_name, remote_ip, connected_at, disconnected_at, last_frame_at, last_signal_at, level_dbfs, peak_dbfs, sample_rate, format, forwarding, bytes}`.

`GET /api/errors?limit=100` → list of error entries.
`GET /api/audio` → `[{campus, audio, history:[{at, event:"connected"|"disconnected", sender, ip?, reason?, duration?}]}]`.

### Campuses (**admin** for writes)
`campus` = `{id, slug, name, timezone, source_language, default_language, enabled, retain_transcripts, languages:[codes]}`
* `GET /api/campuses`
* `POST /api/campuses` body `{slug, name, timezone?, source_language?, default_language?, enabled?, retain_transcripts?, languages?}`
* `PATCH /api/campuses/{id}` any subset
* `DELETE /api/campuses/{id}`
* `GET /api/campuses/{id}/occurrences?days=14` → `[{key, campus_id, name, kind:"recurring"|"special"|"holiday"|"manual", start, end, window_start, cancelled, schedule_id, event_id, local_date}]` (includes cancelled ones)
* Live controls (operators allowed): `POST /api/campuses/{id}/start` `{duration_minutes?, name?}` · `POST /api/campuses/{id}/stop` · `POST /api/campuses/{id}/extend` `{minutes}`
* `GET /api/campuses/{id}/qr?format=svg|png&scale=12` → image (QR to `{public_base_url}/{slug}`)
* `GET /api/qr-links` → `[{campus_id, slug, name, url}]`
* `GET /api/campuses/{id}/transcripts` (**admin**) → `[{occurrence, language, segments, started}]`; `GET .../transcripts/download?occurrence=&language=` → text file

### Schedules (**admin** for writes)
`schedule` = `{id, campus_id, name, weekday (0=Mon…6=Sun), start_time "HH:MM", end_time "HH:MM", timezone, enabled, early_access_minutes, languages: null|[codes], valid_from: null|"YYYY-MM-DD", valid_until}`
* `GET /api/schedules?campus_id=` · `POST /api/schedules` · `PATCH /api/schedules/{id}` · `DELETE /api/schedules/{id}`

`event` (one-time / holiday / manual) = `{id, campus_id, name, kind, start_at, end_at, early_access_minutes, cancelled, languages}`
* `GET /api/events?campus_id=&include_past=false` · `POST /api/events` (`kind` special|holiday; `start_at`/`end_at` must include offset) · `PATCH /api/events/{id}` · `DELETE /api/events/{id}`

Occurrence exceptions (operators allowed): `POST /api/occurrences/cancel {key}` · `POST /api/occurrences/restore {key}`

### Languages
* `GET /api/languages` → `[{code, name_en, native_name, rtl, enabled, sort_order, provider_codes, provider_supported, builtin, viewers}]`
* `POST /api/languages` (**admin**) `{code, name_en, native_name, rtl?, enabled?, sort_order?, provider_codes?}`
* `PATCH /api/languages/{code}` (**admin**) · `DELETE /api/languages/{code}` (**admin**, custom only)
* `POST /api/languages/test` `{text, target, source?}` → `{provider, text, latency_ms}`

### Providers (**admin**)
* `GET /api/providers` → `{stt: {provider, settings, has_key, options:{name: defaultSettings}}, translation: {...}}`
* `PUT /api/providers/{stt|translation}` `{provider, settings, api_key?: string (omit/null = keep), clear_key?: bool}`
  STT options: `deepgram {model, endpointing_ms, keyterms[], price_per_minute}`, `assemblyai {price_per_minute, keyterms[]}`, `simulated {price_per_minute, words_per_minute}`.
  Translation options: `azure {region, endpoint, price_per_million_chars}`, `google {price_per_million_chars}`, `simulated {price_per_million_chars, fail_languages[], delay_ms}`.
  Keys are write-only (never returned).

### Settings
* `GET /api/settings` → `{church_name, public_base_url, effective_public_base_url, manual_default_minutes, ended_grace_minutes, lookahead_days, transcript_retention_days, translate_partials, partial_min_interval_ms, language_grace_seconds, audio_timeout_seconds, digital_silence_seconds}`
* `PUT /api/settings` (**admin**) any subset (except `effective_public_base_url`)

### Audio senders (**admin**)
* `GET /api/senders` → `[{id, campus_id, name, allowed_cidrs, created_at, revoked_at}]`
* `POST /api/senders` `{campus_id, name, allowed_cidrs?}` → sender + `token` (shown once)
* `PATCH /api/senders/{id}` `{name?, allowed_cidrs?}` · `POST /api/senders/{id}/revoke` · `DELETE /api/senders/{id}`

### Branding
* `GET /api/branding` → `{church_name, accent_color, palette:{50,100,500,600,700,800}, contrast:{...}, logo:{sha256,updated_at,bytes}|null}`
* `PUT /api/branding` (**admin**) `{church_name?, accent_color?: "#RRGGBB"}`
* `PUT /api/branding/logo` (**admin**) raw PNG body, `Content-Type: image/png`, ≤ 5 MB; re-encoded server-side and resized to ≤ 1024 px
* `GET /api/branding/logo` · `DELETE /api/branding/logo` (**admin**)

### Updates (**admin**)
* `GET /api/updates` → `{installed:{version,commit,built_at}, updater_online, updater_installed, status:{state,message,behind,commits[],latest_commit,blocked,...}, pending_request, log[]}`
* `POST /api/updates/check` · `POST /api/updates/apply {force?: bool}` (409 while a service is live unless `force`)

### Users (**admin**)
* `GET /api/users` → `[{id, username, display_name, role, mfa_enabled, disabled, created_at, last_login_at}]`
* `POST /api/users` `{username, display_name?, password (≥12), role}` · `PATCH /api/users/{id}` `{display_name?, role?, disabled?, password?, reset_mfa?}` · `DELETE /api/users/{id}`

### Usage & audit
* `GET /api/usage?days=30` → `{days, month:{stt_minutes, translation_chars, est_cost_usd}, rows:[{day, campus_id, provider, metric:"stt_seconds"|"translation_chars", language, quantity, est_cost_usd}]}`
* `GET /api/audit?limit=200` (**admin**) → `[{at, username, action, target, details, ip}]`

---

## 3. Ingest (port 8082) — WebSocket

`wss://audio.example.com/ingest/v1/stream?sample_rate=16000&channels=1&format=s16le`

* Header `Authorization: Bearer cs_<32 hex>_<secret>` (token from Admin → Audio senders). Invalid/revoked/IP-not-allowed → handshake rejected (HTTP 403).
* Any extra headers Pangolin needs (e.g. resource access-token headers) may be added by the sender.
* Client → server: binary frames, raw signed 16-bit little-endian mono PCM, ≤ 32 000 bytes each (send 100 ms = 3 200 bytes at 16 kHz). Byte rate above 3× real time → disconnected.
* Server → client: text JSON every 2 s `{"type":"status","live":bool,"campus":"slug","server_time":..}`. `live:false` = outside a service window (audio only feeds the level meter).
* Silence for 15 s with no frames → server closes (4008). Close code 4009 = replaced by a newer connection from the same campus; 4003 = revoked.
* Sender should reconnect with backoff (1 s → 30 s), drop queued audio older than ~1 s on reconnect (live audio over backlog), and consider the link dead if no status frame for 10 s.
