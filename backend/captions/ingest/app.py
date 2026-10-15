"""Private audio ingestion service (port 8082, Pangolin resource audio.example.com).

Protocol (WebSocket ``/ingest/v1/stream``):

* Handshake must carry ``Authorization: Bearer cs_<sender id>_<secret>`` and
  query parameters ``sample_rate`` (e.g. 16000), ``channels=1``, ``format=s16le``.
  Invalid credentials are rejected *before* the WebSocket is accepted.
* Client sends binary frames of raw 16-bit little-endian mono PCM, ideally
  50-100 ms each. Max frame size and byte rate are enforced.
* Server sends a JSON text frame every 2 s:
  ``{"type":"status","live":bool,"campus":"slug","server_time":...}``.
  ``live`` is false outside a service window; audio is then used only for the
  level meter and is never forwarded to transcription.

Only the newest connection per campus is kept: a reconnecting sender replaces
a half-open stale one immediately.
"""

from __future__ import annotations

import array
import asyncio
import json
import logging
import math
import sys
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .. import db, rkeys
from ..config import get_settings
from ..logging_setup import security_event, setup_logging
from ..models import AudioSender, Campus
from ..netutil import client_ip
from ..redisio import make_redis
from ..security import constant_time_equal, ip_allowed, parse_sender_token, sha256_hex

log = logging.getLogger(__name__)

STREAM_MAXLEN = 300  # ~30 s of 100 ms chunks: bounded buffer, never a long backlog
STATUS_TTL = 30
HISTORY_LEN = 50
AUTH_CACHE_SECONDS = 15


@dataclass
class SenderAuth:
    sender_id: str
    sender_name: str
    campus_id: int
    campus_slug: str
    allowed_cidrs: list[str]


class AuthFailures:
    """Per-IP auth failure limiter (in memory: ingest runs as one process)."""

    def __init__(self, limit: int = 10, window: float = 300.0) -> None:
        self.limit = limit
        self.window = window
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def blocked(self, ip: str) -> bool:
        q = self.events[ip]
        now = time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        return len(q) >= self.limit

    def add(self, ip: str) -> None:
        self.events[ip].append(time.monotonic())


def pcm_levels(pcm: bytes) -> tuple[float, float, bool]:
    """Return (rms dBFS, peak dBFS, has_signal) for s16le mono PCM."""
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return -120.0, -120.0, False
    peak = max(abs(min(samples)), abs(max(samples)))
    # Subsample for RMS: plenty accurate for a meter, cheap on CPU.
    step = max(1, len(samples) // 400)
    sub = samples[::step]
    rms = math.sqrt(sum(s * s for s in sub) / len(sub))
    to_db = lambda v: 20 * math.log10(v / 32768.0) if v > 0 else -120.0  # noqa: E731
    # Any non-zero sample counts as signal; true digital silence is exactly zero.
    return round(to_db(rms), 1), round(to_db(peak), 1), peak > 1


class IngestState:
    def __init__(self) -> None:
        self.redis = None
        self.redis_bin = None
        self.active: dict[int, WebSocket] = {}
        self.auth_cache: dict[str, tuple[float, SenderAuth | None, str]] = {}
        self.failures = AuthFailures()
        self.revoked: set[str] = set()


state = IngestState()


async def _listen_revocations() -> None:
    """Admin publishes sender ids on revoke; drop those connections immediately."""
    while True:
        try:
            pubsub = state.redis.pubsub()
            await pubsub.subscribe(rkeys.INGEST_REVOKED_CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                sender_id = msg["data"]
                state.revoked.add(sender_id)
                state.auth_cache = {k: v for k, v in state.auth_cache.items() if v[1] is None or v[1].sender_id != sender_id}
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("revocation listener failed; retrying")
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging("ingest", s.log_level)
    state.redis = make_redis(decode=True)
    state.redis_bin = make_redis(decode=False)
    listener = asyncio.create_task(_listen_revocations())
    yield
    listener.cancel()
    await db.dispose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
async def healthz():
    try:
        await state.redis.ping()
    except Exception:
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}


async def authenticate(token: str) -> SenderAuth | None:
    parsed = parse_sender_token(token)
    if not parsed:
        return None
    sender_hex, secret = parsed
    cache_key = sha256_hex(token)
    cached = state.auth_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < AUTH_CACHE_SECONDS:
        return cached[1]
    sender_uuid = uuid.UUID(hex=sender_hex)
    # Explicit columns only: the ingest DB role is granted SELECT on these columns alone.
    stmt = (
        select(
            AudioSender.id, AudioSender.name, AudioSender.token_hash, AudioSender.allowed_cidrs,
            AudioSender.revoked_at, Campus.id, Campus.slug, Campus.enabled,
        )
        .join(Campus, Campus.id == AudioSender.campus_id)
        .where(AudioSender.id == sender_uuid)
    )
    async with db.sessionmaker()() as s:
        row = (await s.execute(stmt)).first()
    auth: SenderAuth | None = None
    if row is not None:
        sid, name, token_hash, cidrs, revoked_at, campus_id, slug, enabled = row
        if revoked_at is None and enabled and constant_time_equal(token_hash, sha256_hex(secret)):
            auth = SenderAuth(str(sid), name, campus_id, slug, list(cidrs or []))
    state.auth_cache[cache_key] = (time.monotonic(), auth, sender_hex)
    return auth


async def _history(campus_id: int, event: str, **fields) -> None:
    entry = json.dumps({"at": time.time(), "event": event, **fields})
    async with state.redis.pipeline(transaction=False) as p:
        p.lpush(rkeys.audio_history(campus_id), entry)
        p.ltrim(rkeys.audio_history(campus_id), 0, HISTORY_LEN - 1)
        await p.execute()


@app.websocket("/ingest/v1/stream")
async def stream(ws: WebSocket):
    s = get_settings()
    ip = client_ip(ws)

    if state.failures.blocked(ip):
        security_event("ingest_rate_limited", ip=ip)
        await ws.close(code=1008)
        return

    auth_header = ws.headers.get("authorization", "")
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    auth = await authenticate(token) if token else None
    if auth is None or auth.sender_id in state.revoked:
        state.failures.add(ip)
        security_event("ingest_auth_failed", ip=ip)
        await ws.close(code=1008)  # before accept -> HTTP 403
        return
    if not ip_allowed(ip, auth.allowed_cidrs):
        state.failures.add(ip)
        security_event("ingest_ip_denied", ip=ip, sender=auth.sender_id, campus=auth.campus_slug)
        await ws.close(code=1008)
        return

    try:
        sample_rate = int(ws.query_params.get("sample_rate", "16000"))
        channels = int(ws.query_params.get("channels", "1"))
    except ValueError:
        await ws.close(code=1003)
        return
    if sample_rate not in s.allowed_sample_rates or channels != 1 or ws.query_params.get("format", "s16le") != "s16le":
        security_event("ingest_bad_format", ip=ip, sender=auth.sender_id, sample_rate=sample_rate, channels=channels)
        await ws.close(code=1003)
        return

    await ws.accept()
    campus_id = auth.campus_id
    previous = state.active.get(campus_id)
    state.active[campus_id] = ws
    if previous is not None:
        try:
            await previous.close(code=4009, reason="replaced by newer connection")
        except Exception:
            pass

    r, rb = state.redis, state.redis_bin
    status_key = rkeys.audio_status(campus_id)
    connected_at = time.time()
    await r.delete(status_key)
    await r.hset(
        status_key,
        mapping={
            "connected": "1", "sender_id": auth.sender_id, "sender_name": auth.sender_name,
            "connected_at": connected_at, "last_frame_at": 0, "last_signal_at": connected_at,
            "sample_rate": sample_rate, "format": "s16le", "channels": 1, "remote_ip": ip,
            "level_dbfs": -120, "peak_dbfs": -120, "bytes": 0, "live": 0,
        },
    )
    await r.expire(status_key, STATUS_TTL)
    await _history(campus_id, "connected", sender=auth.sender_name, ip=ip, sample_rate=sample_rate)
    log.info("sender connected", extra={"fields": {"campus": auth.campus_slug, "sender": auth.sender_name, "ip": ip}})

    expected_bps = sample_rate * 2
    window_start = time.monotonic()
    window_bytes = 0
    total_bytes = 0
    last_signal = connected_at
    last_status_push = 0.0
    live_occ: str | None = None
    last_live_check = 0.0
    reason = "closed"

    async def push_status() -> None:
        await ws.send_text(json.dumps({"type": "status", "live": live_occ is not None, "campus": auth.campus_slug, "server_time": time.time()}))

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=s.ingest_idle_timeout_seconds)
            except asyncio.TimeoutError:
                reason = "idle timeout"
                await ws.close(code=4008)
                break
            if msg["type"] == "websocket.disconnect":
                reason = "client disconnected"
                break
            pcm = msg.get("bytes")
            if pcm is None:
                continue  # text frames from the sender are ignored (no control channel)
            if len(pcm) > s.ingest_max_frame_bytes or len(pcm) % 2:
                security_event("ingest_bad_frame", ip=ip, sender=auth.sender_id, size=len(pcm))
                reason = "invalid frame"
                await ws.close(code=1009)
                break
            if auth.sender_id in state.revoked:
                reason = "revoked"
                await ws.close(code=4003)
                break

            now_mono = time.monotonic()
            window_bytes += len(pcm)
            total_bytes += len(pcm)
            if now_mono - window_start >= 5.0:
                # A real sender produces ~expected_bps; far more means injection or a bug.
                if window_bytes > expected_bps * (now_mono - window_start) * 3:
                    security_event("ingest_rate_exceeded", ip=ip, sender=auth.sender_id, bytes=window_bytes)
                    reason = "byte rate exceeded"
                    await ws.close(code=1008)
                    break
                window_start, window_bytes = now_mono, 0

            if now_mono - last_live_check >= 1.0:
                live_occ = await r.get(rkeys.campus_live_flag(campus_id))
                last_live_check = now_mono

            now = time.time()
            rms, peak, has_signal = pcm_levels(pcm)
            if has_signal:
                last_signal = now
            if live_occ is not None:
                await rb.xadd(
                    rkeys.audio_stream(campus_id),
                    {"pcm": pcm, "sr": sample_rate, "t": f"{now:.3f}"},
                    maxlen=STREAM_MAXLEN,
                    approximate=True,
                )
            async with r.pipeline(transaction=False) as p:
                p.hset(status_key, mapping={
                    "connected": "1", "last_frame_at": f"{now:.3f}", "last_signal_at": f"{last_signal:.3f}",
                    "level_dbfs": rms, "peak_dbfs": peak, "bytes": total_bytes, "live": 1 if live_occ else 0,
                })
                p.expire(status_key, STATUS_TTL)
                await p.execute()
            if now_mono - last_status_push >= 2.0:
                await push_status()
                last_status_push = now_mono
    except WebSocketDisconnect:
        reason = "client disconnected"
    except Exception as e:
        reason = f"error: {e!r}"
        log.exception("ingest stream failed")
    finally:
        if state.active.get(campus_id) is ws:
            state.active.pop(campus_id, None)
            await r.hset(status_key, mapping={"connected": "0", "disconnected_at": time.time()})
            await r.expire(status_key, 24 * 3600)
        await _history(campus_id, "disconnected", sender=auth.sender_name, reason=reason, duration=round(time.time() - connected_at))
        log.info("sender disconnected", extra={"fields": {"campus": auth.campus_slug, "reason": reason}})
