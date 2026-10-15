"""Public service: read-only enforcement, caption distribution, campus isolation, reconnection."""

import asyncio
import json
import time

import httpx
import pytest

from captions import rkeys
from captions.public.app import create_app
from captions.worker.publisher import CaptionPublisher

from .conftest import needs_services

pytestmark = needs_services

LANGS = [{"code": "en", "name": "English", "rtl": False}, {"code": "es", "name": "Español", "rtl": False}]


def status(slug: str, phase: str = "live", captions: str | None = "live", key: str = "e1") -> dict:
    return {
        "slug": slug, "name": slug, "timezone": "America/New_York", "source_language": "en", "default_language": "en",
        "phase": phase, "captions": captions if phase == "live" else None,
        "service": {"key": key, "name": "Svc", "start": "2026-10-04T13:00:00Z", "end": "2026-10-04T14:30:00Z"} if phase == "live" else None,
        "next": None, "languages": LANGS, "server_time": time.time(),
    }


async def put_status(r, slug, **kw):
    st = status(slug, **kw)
    await r.set(rkeys.public_status(slug), json.dumps(st), ex=60)
    await r.publish(rkeys.status_channel(slug), json.dumps(st))
    return st


class SSEReader:
    """Minimal SSE parser over an httpx streaming response."""

    def __init__(self, response: httpx.Response) -> None:
        self.lines = response.aiter_lines()

    async def next_event(self, timeout: float = 5.0) -> tuple[str, str] | None:
        event, data = None, []

        async def read():
            nonlocal event
            async for line in self.lines:
                if line == "":
                    if event or data:
                        return event or "message", "\n".join(data)
                    continue
                if line.startswith(":"):
                    continue
                k, _, v = line.partition(":")
                v = v[1:] if v.startswith(" ") else v
                if k == "event":
                    event = v
                elif k == "data":
                    data.append(v)
            return None

        return await asyncio.wait_for(read(), timeout)

    async def until(self, name: str, timeout: float = 5.0) -> str:
        end = time.monotonic() + timeout
        while True:
            ev = await self.next_event(max(0.1, end - time.monotonic()))
            if ev is None:
                raise AssertionError("stream closed")
            if ev[0] == name:
                return ev[1]


async def test_mutating_methods_are_rejected(clean, run_server):
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            for path in ("/api/public/config", "/api/public/campus/x", "/api/campuses", "/"):
                r = await c.request(method, path)
                assert r.status_code == 405, (method, path)


async def test_no_admin_routes_on_public_service(clean, run_server):
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        for path in ("/api/overview", "/api/auth/me", "/api/campuses", "/api/users", "/ingest/v1/stream", "/docs", "/openapi.json"):
            r = await c.get(path)
            assert r.status_code in (404, 503), path  # 503 = SPA not built in test env
            assert "csrf" not in r.text


async def test_security_headers_present(clean, run_server):
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        r = await c.get("/api/public/config")
        assert r.status_code == 200
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store"


async def test_status_and_stream_gating(clean, redis_client, run_server):
    r = redis_client
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        await r.set(rkeys.PUBLIC_CAMPUSES, json.dumps([{"slug": "east", "name": "East"}]))
        assert (await c.get("/api/public/campus/nowhere")).status_code == 404
        assert (await c.get("/api/public/campus/east")).status_code == 503  # worker not publishing yet
        await put_status(r, "east", phase="upcoming")
        assert (await c.get("/api/public/campus/east")).json()["phase"] == "upcoming"
        # Backend-enforced: no stream outside a service window.
        resp = await c.get("/api/public/campus/east/stream", params={"lang": "es"})
        assert resp.status_code == 409
        await put_status(r, "east", phase="live")
        assert (await c.get("/api/public/campus/east/stream", params={"lang": "de"})).status_code == 404
        assert (await c.get("/api/public/campus/east/stream", params={"lang": "<script>"})).status_code == 422
        assert (await c.get("/api/public/campus/BAD SLUG/stream", params={"lang": "es"})).status_code == 404


async def test_shared_stream_per_language_and_campus_isolation(clean, redis_client, run_server):
    r = redis_client
    await put_status(r, "east", phase="live")
    await put_status(r, "west", phase="live", key="e2")
    east = CaptionPublisher(r, "east", "e1")
    west = CaptionPublisher(r, "west", "e2")
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        url = f"{srv.base}/api/public/campus/{{}}/stream"
        async with c.stream("GET", url.format("east"), params={"lang": "es"}) as r1, \
                   c.stream("GET", url.format("east"), params={"lang": "es"}) as r2, \
                   c.stream("GET", url.format("west"), params={"lang": "es"}) as r3:
            assert r1.headers["content-type"].startswith("text/event-stream")
            s1, s2, s3 = SSEReader(r1), SSEReader(r2), SSEReader(r3)
            for s in (s1, s2, s3):
                await s.until("backlog")
            await asyncio.sleep(0.2)  # let viewer counts settle
            await east.caption("es", 1, "Hola <b>iglesia</b>", True)
            await west.caption("es", 1, "Bienvenidos al oeste", True)
            m1 = json.loads(await s1.until("caption"))
            m2 = json.loads(await s2.until("caption"))
            m3 = json.loads(await s3.until("caption"))
            assert m1 == m2 and m1["text"] == "Hola <b>iglesia</b>"  # transported verbatim, rendered as text by client
            assert m3["text"] == "Bienvenidos al oeste"  # west never sees east's captions

            # Viewer counts are reported per campus/language for the worker.
            await asyncio.sleep(2.5)
            counts = {}
            async for key in r.scan_iter(match="viewers:*"):
                counts.update(await r.hgetall(key))
            assert counts.get("east|es") == "2" and counts.get("west|es") == "1"


async def test_reconnecting_client_gets_backlog(clean, redis_client, run_server):
    r = redis_client
    await put_status(r, "east", phase="live")
    pub = CaptionPublisher(r, "east", "e1")
    for i in range(1, 4):
        await pub.caption("es", i, f"frase {i}", True)
    await pub.caption("es", 4, "parcial", False)  # partials are not buffered
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        async with c.stream("GET", f"{srv.base}/api/public/campus/east/stream", params={"lang": "es"}) as resp:
            s = SSEReader(resp)
            first = json.loads(await s.until("status"))
            assert first["phase"] == "live"
            backlog = json.loads(await s.until("backlog"))
            assert [m["text"] for m in backlog] == ["frase 1", "frase 2", "frase 3"]


async def test_service_end_closes_streams(clean, redis_client, run_server):
    r = redis_client
    await put_status(r, "east", phase="live")
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        async with c.stream("GET", f"{srv.base}/api/public/campus/east/stream", params={"lang": "en"}) as resp:
            s = SSEReader(resp)
            await s.until("backlog")
            await put_status(r, "east", phase="ended")
            ended = json.loads(await s.until("status"))
            assert ended["phase"] == "ended"
            assert await s.next_event(timeout=5) is None  # server closed the stream


async def test_slow_client_does_not_block_others(clean, redis_client, run_server):
    from captions.public.hub import QUEUE_SIZE, CaptionHub, Subscriber

    hub = CaptionHub(redis_client)
    slow = Subscriber("east", "es", "1.1.1.1")
    fast = Subscriber("east", "es", "2.2.2.2")
    hub.add(slow)
    hub.add(fast)
    for i in range(QUEUE_SIZE + 5):
        hub.dispatch("cap:east:es", json.dumps({"id": i}))
        fast.queue.get_nowait()  # fast client keeps up
    assert slow.closed and not fast.closed


@pytest.mark.parametrize("n", [200])
async def test_many_concurrent_viewers(clean, redis_client, run_server, n):
    """Smoke-level load test: n concurrent SSE viewers all receive one caption."""
    r = redis_client
    await put_status(r, "east", phase="live")
    pub = CaptionPublisher(r, "east", "e1")
    got = 0
    ready = asyncio.Event()
    connected = 0

    async with run_server(create_app()) as srv:
        limits = httpx.Limits(max_connections=n + 10)
        async with httpx.AsyncClient(base_url=srv.base, timeout=20, limits=limits) as c:

            async def viewer():
                nonlocal got, connected
                async with c.stream("GET", "/api/public/campus/east/stream", params={"lang": "es"}) as resp:
                    s = SSEReader(resp)
                    await s.until("backlog", timeout=15)
                    connected += 1
                    if connected == n:
                        ready.set()
                    await s.until("caption", timeout=15)
                    got += 1

            tasks = [asyncio.create_task(viewer()) for _ in range(n)]
            await asyncio.wait_for(ready.wait(), 30)
            await pub.caption("es", 1, "hola a todos", True)
            await asyncio.wait_for(asyncio.gather(*tasks), 30)
    assert got == n
