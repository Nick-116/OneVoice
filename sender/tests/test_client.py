"""Client tests against a local fake ingest server. No audio device needed."""

import asyncio
import json
import time
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from church_sender.audio import DropOldestBuffer
from church_sender.client import AUTH_FAILED_MSG, REPLACED_MSG, REVOKED_MSG, ClientSettings, LinkState, SenderClient

TOKEN = "cs_0123456789abcdef0123456789abcdef_secret"  # gitleaks:allow (fake test token)


class FakeSource:
    """Real-time-ish 48 kHz sine generator feeding the client's buffer (stands in for AudioCapture)."""

    def __init__(self, rate=48000):
        self.sample_rate = rate
        self.buffer = DropOldestBuffer(rate, 2.0)
        self.forward = False
        self.last_callback = 0.0
        self._phase = 0

    async def produce(self):
        n = self.sample_rate // 50
        while True:
            t = (np.arange(n) + self._phase) / self.sample_rate
            self._phase += n
            chunk = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
            self.last_callback = time.monotonic()
            if self.forward:
                self.buffer.push(chunk, self.last_callback)
            await asyncio.sleep(0.02)


class FakeIngest:
    def __init__(self, *, reject=False, send_status=True, live=True, close_first_after=None, close_code=1011):
        self.reject = reject
        self.send_status = send_status
        self.live = live
        self.close_first_after = close_first_after
        self.close_code = close_code
        self.attempts = 0
        self.connections = []

    def process_request(self, connection, request):
        self.attempts += 1
        if self.reject:
            return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
        return None

    async def handler(self, ws):
        conn = {"path": ws.request.path, "headers": ws.request.headers, "frames": []}
        self.connections.append(conn)
        index = len(self.connections)

        async def status():
            while True:
                await ws.send(json.dumps({"type": "status", "live": self.live, "campus": "main", "server_time": time.time()}))
                await asyncio.sleep(0.2)

        task = asyncio.create_task(status()) if self.send_status else None
        try:
            async for msg in ws:
                conn["frames"].append(msg)
                if self.close_first_after and index == 1 and len(conn["frames"]) >= self.close_first_after:
                    await ws.close(code=self.close_code, reason="test")
                    break
        except ConnectionClosed:
            pass
        finally:
            if task:
                task.cancel()


async def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


class Harness:
    def __init__(self, fake, **settings):
        self.fake = fake
        self.settings = settings

    async def __aenter__(self):
        self.server = await serve(self.fake.handler, "127.0.0.1", 0, process_request=self.fake.process_request)
        port = self.server.sockets[0].getsockname()[1]
        defaults = dict(
            url=f"ws://127.0.0.1:{port}/ingest/v1/stream", token=TOKEN,
            extra_headers={"P-Access-Token": "pangolin-secret"}, initial_backoff=0.05, max_backoff=0.2,
            auth_backoff=30.0, status_timeout=2.0, open_timeout=2.0,
        )
        defaults.update(self.settings)
        self.source = FakeSource()
        self.producer = asyncio.create_task(self.source.produce())
        self.client = SenderClient(ClientSettings(**defaults), self.source)
        self.task = asyncio.create_task(self.client.run())
        return self

    async def __aexit__(self, *exc):
        self.client.stop()
        await asyncio.wait_for(self.task, 5)
        self.producer.cancel()
        self.server.close()
        await self.server.wait_closed()


async def test_streams_with_auth_header_query_and_binary_frames():
    fake = FakeIngest()
    async with Harness(fake) as h:
        await wait_for(lambda: fake.connections and len(fake.connections[0]["frames"]) >= 5)
        await wait_for(lambda: h.client.snapshot().state == LinkState.LIVE)
        snap = h.client.snapshot()
        assert snap.campus == "main" and snap.live
        assert snap.bytes_sent >= 5 * 3200
    conn = fake.connections[0]
    assert conn["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert conn["headers"]["P-Access-Token"] == "pangolin-secret"
    url = urlsplit(conn["path"])
    assert url.path == "/ingest/v1/stream"
    assert parse_qs(url.query) == {"sample_rate": ["16000"], "channels": ["1"], "format": ["s16le"]}
    assert all(isinstance(f, bytes) and len(f) == 3200 for f in conn["frames"])
    pcm = np.frombuffer(b"".join(conn["frames"][1:]), "<i2")
    assert 0.25 * 32767 < np.abs(pcm).max() < 0.35 * 32767  # the sine got through, scaled correctly
    assert h.client.snapshot().state == LinkState.STOPPED


async def test_standby_when_not_live():
    fake = FakeIngest(live=False)
    async with Harness(fake) as h:
        await wait_for(lambda: h.client.snapshot().campus == "main")
        assert h.client.snapshot().state == LinkState.STANDBY


async def test_reconnects_after_server_drops_connection():
    fake = FakeIngest(close_first_after=3)
    async with Harness(fake) as h:
        await wait_for(lambda: len(fake.connections) >= 2 and len(fake.connections[1]["frames"]) >= 3)
        assert h.client.snapshot().reconnects >= 1
        assert h.client.snapshot().state in (LinkState.LIVE, LinkState.STANDBY)
    assert all(len(f) == 3200 for c in fake.connections for f in c["frames"])
    assert fake.connections[1]["headers"]["Authorization"] == f"Bearer {TOKEN}"


async def test_403_rejection_shows_auth_error_and_backs_off():
    fake = FakeIngest(reject=True)
    async with Harness(fake, auth_backoff=30.0) as h:
        await wait_for(lambda: h.client.snapshot().state == LinkState.RETRY_WAIT)
        snap = h.client.snapshot()
        assert AUTH_FAILED_MSG in snap.last_error
        assert snap.retry_at - time.time() > 25  # long auth backoff, not the 0.05 s normal one
        await asyncio.sleep(0.5)
        assert fake.attempts == 1
        t0 = time.monotonic()
    assert time.monotonic() - t0 < 2  # stop() interrupts the backoff sleep
    assert fake.connections == []


async def test_revoked_close_code_stops_client():
    fake = FakeIngest(close_first_after=2, close_code=4003)
    async with Harness(fake) as h:
        await asyncio.wait_for(h.task, 5)  # run() returns by itself
        snap = h.client.snapshot()
        assert snap.state == LinkState.REVOKED and snap.last_error.endswith(REVOKED_MSG)
        assert len(fake.connections) == 1


async def test_replaced_close_code_warns_and_reconnects():
    fake = FakeIngest(close_first_after=2, close_code=4009)
    async with Harness(fake) as h:
        await wait_for(lambda: (h.client.snapshot().last_error or "").endswith(REPLACED_MSG))
        await wait_for(lambda: len(fake.connections) >= 2)


async def test_policy_close_1008_treated_as_auth_failure():
    fake = FakeIngest(close_first_after=2, close_code=1008)
    async with Harness(fake, auth_backoff=30.0) as h:
        await wait_for(lambda: h.client.snapshot().state == LinkState.RETRY_WAIT)
        assert AUTH_FAILED_MSG in h.client.snapshot().last_error


async def test_status_watchdog_reconnects_when_server_is_silent():
    fake = FakeIngest(send_status=False)
    async with Harness(fake, status_timeout=0.4) as h:
        await wait_for(lambda: len(fake.connections) >= 2, timeout=5)
        assert "No status from server" in (h.client.snapshot().last_error or "")


async def test_backlog_older_than_one_second_discarded_on_connect():
    fake = FakeIngest()
    h = Harness(fake)
    h.server = await serve(fake.handler, "127.0.0.1", 0)
    port = h.server.sockets[0].getsockname()[1]
    src = FakeSource()
    now = time.monotonic()
    for i in range(100):  # 2 s backlog of 20 ms chunks, oldest 2 s ago
        src.buffer.push(np.zeros(960, np.float32), t=now - 2.0 + i * 0.02)
    client = SenderClient(ClientSettings(url=f"ws://127.0.0.1:{port}/ingest/v1/stream", token=TOKEN), src)
    task = asyncio.create_task(client.run())
    try:
        await wait_for(lambda: fake.connections and fake.connections[0]["frames"])
        await asyncio.sleep(0.3)
        sent = sum(len(f) for f in fake.connections[0]["frames"])
        assert sent <= 32000 + 3200  # at most ~1 s of 16 kHz audio, not 2 s
        assert src.buffer.dropped_samples >= 48000 * 0.9
    finally:
        client.stop()
        await asyncio.wait_for(task, 5)
        h.server.close()
        await h.server.wait_closed()
