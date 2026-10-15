"""Private administration API + dashboard (port 8081).

Every /api route except login/me requires an authenticated, MFA-verified
session; mutating routes additionally require a CSRF token. A reverse-proxy login in
front of this service is an additional layer, not a replacement.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from .. import db
from ..config import get_settings
from ..logging_setup import setup_logging
from ..redisio import make_redis
from ..web import CSP, MethodAllowListMiddleware, RateLimiter, RateLimitMiddleware, SecurityHeadersMiddleware, spa_response
from . import auth, branding_routes, operations, services, setup_routes, update_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging("admin", s.log_level)
    app.state.redis = make_redis(decode=True)
    try:
        async with db.sessionmaker()() as session:
            await setup_routes.ensure_setup_code(app.state.redis, session)
    except Exception:  # DB not migrated yet etc.; /api/setup/status retries later
        logging.getLogger(__name__).exception("could not prepare first-run setup")
    yield
    await app.state.redis.aclose()
    await db.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(600))
    app.add_middleware(MethodAllowListMiddleware, allowed={"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
    # The MFA enrolment QR is an inline SVG string rendered via <img src="data:...">, covered by img-src data:.
    app.add_middleware(SecurityHeadersMiddleware, csp=CSP, hsts=s.cookie_secure)

    app.include_router(auth.router)
    app.include_router(services.router)
    app.include_router(operations.router)
    app.include_router(branding_routes.router)
    app.include_router(update_routes.router)
    app.include_router(setup_routes.router)

    @app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
    async def healthz():
        try:
            await app.state.redis.ping()
        except Exception:
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def api_not_found(rest: str):
        raise HTTPException(404, "Not found")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str) -> Response:
        return spa_response(Path(s.static_dir or "/app/static"), path)

    return app


app = create_app()
