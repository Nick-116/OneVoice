"""Public caption service (port 8080, the ONLY public Pangolin resource).

Strictly read-only:
  * only GET/HEAD are accepted (405 for everything else, before routing),
  * no database credentials at all - data comes from Redis via an ACL user
    that can only read public keys, write viewer counts and subscribe to
    caption/status channels,
  * no admin routes exist in this process.

Routes:
  GET /api/public/config                 church name + list of campuses
  GET /api/public/campus/{slug}          status, languages, next service
  GET /api/public/campus/{slug}/stream   SSE caption stream (only while live)
  GET /branding/logo                     church logo
  GET /healthz                           container health
  GET /*                                 the React app
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .. import rkeys
from ..config import get_settings
from ..logging_setup import security_event, setup_logging
from ..netutil import client_ip
from ..redisio import make_redis
from ..web import MethodAllowListMiddleware, RateLimiter, RateLimitMiddleware, SecurityHeadersMiddleware, spa_response
from .hub import CaptionHub, Subscriber

log = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
KEEPALIVE_SECONDS = 15
LOGO_NAMES = ("logo.svg", "logo.png", "logo.webp", "logo.jpg")


class PublicState:
    redis = None
    hub: CaptionHub | None = None


state = PublicState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging("public", s.log_level)
    state.redis = make_redis(decode=True)
    state.hub = CaptionHub(state.redis)
    state.hub.start()
    yield
    await state.hub.stop()
    await state.redis.aclose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    # Last added = outermost: headers wrap everything, including 405/429 responses.
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(s.public_requests_per_minute_per_ip))
    app.add_middleware(MethodAllowListMiddleware, allowed={"GET", "HEAD"})
    app.add_middleware(SecurityHeadersMiddleware, hsts=s.cookie_secure)
    register_routes(app)
    return app


def _valid_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise HTTPException(404, "Not found")
    return slug


async def _status(slug: str) -> dict | None:
    raw = await state.redis.get(rkeys.public_status(slug))
    if not raw:
        return None
    data = json.loads(raw)
    data["server_time"] = time.time()
    return data


def sse(event: str, data: str, event_id: str | None = None) -> bytes:
    # Each line of data must be prefixed; JSON produced here never contains raw newlines.
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event}\ndata: {data}\n\n".encode()


def register_routes(app: FastAPI) -> None:
    s = get_settings()

    @app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
    async def healthz():
        ok = state.hub is not None and state.hub.redis_ok
        return JSONResponse({"ok": ok, "viewers": state.hub.total if state.hub else 0}, status_code=200 if ok else 503)

    @app.get("/api/public/config")
    async def public_config():
        campuses = await state.redis.get(rkeys.PUBLIC_CAMPUSES)
        branding = await state.redis.get(rkeys.PUBLIC_BRANDING)
        b = json.loads(branding) if branding else {}
        return {
            "church_name": b.get("church_name", ""),
            "theme": b.get("theme"),
            "fonts": b.get("fonts"),
            "logo_version": b.get("logo_version"),
            "campuses": json.loads(campuses) if campuses else [],
        }

    @app.get("/api/public/campus/{slug}")
    async def campus_status(slug: str):
        data = await _status(_valid_slug(slug))
        if data is None:
            campuses = json.loads(await state.redis.get(rkeys.PUBLIC_CAMPUSES) or "null")
            if campuses is not None and slug not in {c["slug"] for c in campuses}:
                raise HTTPException(404, "Not found")
            # Worker hasn't published (starting up or down): degrade gracefully.
            return JSONResponse({"slug": slug, "phase": "unavailable", "server_time": time.time()}, status_code=503)
        return data

    @app.get("/api/public/campus/{slug}/stream")
    async def campus_stream(request: Request, slug: str, lang: str = Query(..., max_length=16)):
        _valid_slug(slug)
        if not LANG_RE.match(lang):
            raise HTTPException(422, "Invalid language")
        hub = state.hub
        assert hub is not None
        status = await _status(slug)
        if status is None:
            raise HTTPException(503, "Captions are temporarily unavailable")
        # Backend-enforced schedule: no caption stream outside a live service window.
        if status.get("phase") != "live":
            return JSONResponse(status, status_code=409)
        if lang not in {l["code"] for l in status.get("languages", [])}:
            raise HTTPException(404, "Language not available")

        ip = client_ip(request)
        if hub.total >= s.public_max_streams:
            security_event("public_stream_capacity", ip=ip)
            raise HTTPException(503, "Server busy", headers={"Retry-After": "5"})
        if hub.by_ip.get(ip, 0) >= s.public_max_streams_per_ip:
            security_event("public_stream_per_ip_limit", ip=ip)
            raise HTTPException(429, "Too many connections", headers={"Retry-After": "10"})

        sub = Subscriber(slug=slug, lang=lang, ip=ip)
        hub.add(sub)
        backlog = await state.redis.lrange(rkeys.caption_buffer(slug, lang), -30, -1)

        async def events():
            try:
                yield b"retry: 3000\n\n"
                yield sse("status", json.dumps(status, ensure_ascii=False))
                yield sse("backlog", "[" + ",".join(backlog) + "]")
                while True:
                    try:
                        kind, data = await asyncio.wait_for(sub.queue.get(), timeout=KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield b": keepalive\n\n"
                        continue
                    if kind == "close":
                        break
                    yield sse(kind, data)
            finally:
                sub.closed = True
                hub.remove(sub)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.api_route("/branding/logo", methods=["GET", "HEAD"], include_in_schema=False)
    async def logo(request: Request):
        # 1) Logo uploaded in the admin dashboard (relayed by the worker via Redis).
        encoded = await state.redis.get(rkeys.PUBLIC_LOGO)
        if encoded:
            png = base64.b64decode(encoded)
            etag = '"' + hashlib.sha256(png).hexdigest()[:16] + '"'
            # Versioned URLs (?v=<hash>) never change, so they can be cached for a long time.
            cache = "public, max-age=31536000, immutable" if request.query_params.get("v") else "public, max-age=300"
            headers = {"Cache-Control": cache, "ETag": etag}
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers=headers)
            return Response(png, media_type="image/png", headers=headers)
        # 2) Fallback: a file placed in the branding/ folder on the server.
        base = Path(s.branding_dir)
        for name in LOGO_NAMES:
            p = base / name
            if p.is_file():
                return FileResponse(p, headers={"Cache-Control": "public, max-age=300"})  # short: logo swaps show up quickly
        raise HTTPException(404, "No logo configured")

    @app.get("/api/{rest:path}", include_in_schema=False)
    async def api_not_found(rest: str):
        raise HTTPException(404, "Not found")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str) -> Response:
        return spa_response(Path(s.static_dir or "/app/static"), path)


app = create_app()
