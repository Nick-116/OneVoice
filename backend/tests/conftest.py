"""Shared fixtures. Integration tests need PostgreSQL + Redis (see compose.test.yml);
pure unit tests (schedule, segmenter, translation channel) run anywhere."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys

import pytest

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ADMIN_ORIGIN", "http://admin.test")
os.environ.setdefault("TRUSTED_PROXY_HOPS", "0")

HAVE_SERVICES = bool(os.environ.get("DB_HOST"))
needs_services = pytest.mark.skipif(not HAVE_SERVICES, reason="needs PostgreSQL and Redis (run via compose.test.yml)")

TABLES = (
    "branding_assets, audit_log, transcripts, usage_records, provider_configs, admin_sessions, admin_users, audio_senders, "
    "schedule_exceptions, service_events, service_schedules, campus_languages, campuses, app_settings"
)


@pytest.fixture(scope="session")
def migrated():
    if not HAVE_SERVICES:
        pytest.skip("needs services")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    return True


@pytest.fixture
async def clean(migrated):
    from sqlalchemy import text

    from captions import db
    from captions.languages import CATALOG
    from captions.redisio import make_redis

    async with db.sessionmaker()() as s:
        await s.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        # Languages are seed data: restore the built-in catalog state.
        await s.execute(text("DELETE FROM languages WHERE code <> ALL(:codes)"), {"codes": [l.code for l in CATALOG]})
        await s.execute(text("UPDATE languages SET enabled = true"))
        await s.commit()
    r = make_redis()
    await r.flushdb()
    await r.aclose()
    yield


@pytest.fixture
async def redis_client(migrated):
    from captions.redisio import make_redis

    r = make_redis()
    yield r
    await r.aclose()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunningServer:
    def __init__(self, app, port: int) -> None:
        import uvicorn

        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws_max_size=65536, lifespan="on", timeout_graceful_shutdown=2)
        self.server = uvicorn.Server(config)
        self.task: asyncio.Task | None = None

    async def __aenter__(self):
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(200):
            if self.server.started:
                return self
            await asyncio.sleep(0.02)
        raise RuntimeError("server did not start")

    async def __aexit__(self, *exc):
        self.server.should_exit = True
        if self.task:
            await asyncio.wait_for(self.task, timeout=15)


@pytest.fixture
def run_server():
    def factory(app):
        return RunningServer(app, free_port())

    return factory


async def make_campus(slug: str = "east-hartford", languages=("en", "es", "fr"), **kw) -> int:
    from captions import db
    from captions import models as m

    async with db.sessionmaker()() as s:
        c = m.Campus(slug=slug, name=kw.pop("name", slug.replace("-", " ").title()), **kw)
        c.languages = [m.CampusLanguage(language_code=code) for code in languages]
        s.add(c)
        await s.commit()
        return c.id


def pytest_collection_modifyitems(items):
    # One event loop for the whole run: the DB engine and Redis pools are module globals.
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if asyncio.iscoroutinefunction(getattr(item, "function", None)):
            item.add_marker(marker, append=False)
