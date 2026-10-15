"""Shared HTTP hardening: security headers, method allow-list, static SPA serving."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.types import ASGIApp

from .netutil import client_ip

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'; manifest-src 'self'"
)


class SecurityHeadersMiddleware:
    """Adds security headers to every HTTP response (pure ASGI: safe for SSE streams)."""

    def __init__(self, app: ASGIApp, csp: str = CSP, hsts: bool = True) -> None:
        self.app = app
        headers = {
            "content-security-policy": csp,
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
            "cross-origin-opener-policy": "same-origin",
            "cross-origin-resource-policy": "same-origin",
        }
        if hsts:
            headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        self.headers = [(k.encode(), v.encode()) for k, v in headers.items()]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"].startswith("/api/")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.headers if k not in existing]
                if is_api and b"cache-control" not in existing:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_wrapper)


class MethodAllowListMiddleware:
    """Rejects any HTTP method not in the allow-list before routing (pure ASGI)."""

    def __init__(self, app: ASGIApp, allowed: set[str]) -> None:
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in self.allowed:
            resp = JSONResponse({"detail": "Method not allowed"}, status_code=405, headers={"Allow": ", ".join(sorted(self.allowed))})
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RateLimiter:
    """Simple sliding-window limiter keyed by client IP (single-process)."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_gc = time.monotonic()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if now - self._last_gc > 300:
            self._gc(now)
        return True

    def _gc(self, now: float) -> None:
        self._last_gc = now
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window]:
            del self.hits[k]


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, limiter: RateLimiter, prefix: str = "/api/") -> None:
        self.app = app
        self.limiter = limiter
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(self.prefix):
            if not self.limiter.allow(client_ip(Request(scope))):
                resp = JSONResponse({"detail": "Too many requests"}, status_code=429, headers={"Retry-After": "10"})
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def spa_response(static_dir: Path, path: str) -> Response:
    """Serve a built Vite SPA: real files if they exist, otherwise index.html."""
    root = static_dir.resolve()
    if path:
        candidate = (root / path).resolve()
        # Path traversal guard: resolved file must stay inside the static root.
        if candidate.is_file() and root in candidate.parents:
            cache = "public, max-age=31536000, immutable" if "/assets/" in f"/{path}" else "public, max-age=300"
            return FileResponse(candidate, headers={"Cache-Control": cache})
    index = root / "index.html"
    if not index.is_file():
        return JSONResponse({"detail": "Frontend not built"}, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
