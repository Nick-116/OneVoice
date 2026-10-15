# Testing

## Backend test suite (60 tests)

Runs against real PostgreSQL 16 and Redis 7 in throwaway containers:

```bash
docker compose -f compose.test.yml run --rm --build tests
docker compose -f compose.test.yml down -v
```

| File | Covers |
|---|---|
| `test_schedule.py` | weekly expansion, fall-back and spring-forward DST, non-existent/ambiguous local times, midnight-crossing services, other time zones, validity ranges, cancel/modify exceptions, one-time events, phases before/during/after, early access, manual start/extension overlap, countdown rounding |
| `test_segmenter.py` | partial → final stabilization, sentence cutting, abbreviations, long run-on splitting, endpoint flush |
| `test_translation_channel.py` | a failing language doesn't affect others, circuit breaker + "unavailable/restored" notices, bounded backlog drops oldest |
| `test_public_api.py` | every mutating method → 405, no admin routes on the public service, security headers, stream refused outside service windows, invalid slug/lang, **one shared stream per language**, **campus isolation**, backlog on reconnect, streams closed at service end, slow client cannot block others, **200 concurrent SSE viewers** |
| `test_admin_api.py` | every route requires auth, login throttling, MFA enrolment and verification, TOTP replay, CSRF token and Origin checks, operator vs admin roles, campus/schedule/event validation, cancel/restore occurrences, **manual start/extend/stop** (recurring and one-time), sender tokens shown once, QR PNG/SVG, provider keys write-only, translation test, language management, user safety rules |
| `test_ingest.py` | missing/forged/unknown tokens rejected before accept, bad audio format, **IP allowlist**, audio forwarded **only while live**, status/history, oversized frames, newest connection replaces older, revoked sender, disabled campus, auth-failure rate limiting |
| `test_pipeline_e2e.py` | worker with simulated providers: disconnected → live states, captions in English and only the *viewed* translation, other campus untouched, usage metering, service end stops the pipeline and the ingest flag, countdown status, digital silence = disconnected, disabled/unsupported languages hidden |

Frontend and sender tests:
```bash
cd public-web && npm ci && npm test
cd admin-web && npm ci && npm test
docker run --rm -v "$PWD/sender":/src -w /src python:3.12-slim sh -c "pip install -q -r requirements.txt pytest pytest-asyncio && python -m pytest -q"
```

## Simulated mode (no console, no API keys)

1. Admin → Providers & Settings: STT = `simulated`, Translation = `simulated`.
2. Create a campus and a sender; copy the token.
3. Run `python tools/simulate_sender.py --url ws://localhost:8082/ingest/v1/stream --token cs_...` (against a local install).
4. Overview → **Start service now**. Open `http://localhost:8080/campus/<campus>` and choose any language.

The simulated STT releases words at speaking pace *only while audio is arriving*, so stopping the simulator reproduces a real disconnection. To test a real provider without the console, pass a recorded sermon with `--wav sermon.wav`. Simulated translation can be told to fail specific languages (`fail_languages`) to rehearse provider outages.

## Load testing (≥ 200 viewers)

* `test_public_api.py::test_many_concurrent_viewers` proves fan-out to 200 concurrent viewers in CI.
* Against a deployment, use `loadtest/sse_load.py` during a live or simulated service:
  ```bash
  pip install httpx==0.28.1
  python loadtest/sse_load.py --base http://<server-ip>:8080 --campus main --viewers 300 --langs en,es,pt,ht --duration 120
  ```
  It reports connected viewers, captions received per viewer and delivery delay percentiles.
* The per-IP limit defaults to 400 streams, which suits church Wi-Fi behind one NAT. Spread larger tests across several client machines.
