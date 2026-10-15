"""Audio ingest: sender authentication, IP allowlist, payload limits, forwarding only while live."""

import asyncio
import json
import uuid

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from captions import db, rkeys
from captions import models as m
from captions.ingest import app as ingest_mod
from captions.security import new_sender_token

from .conftest import make_campus, needs_services

pytestmark = needs_services
FRAME = b"\x10\x00" * 1600  # 100 ms of quiet non-zero audio at 16 kHz


async def make_sender(campus_id: int, cidrs=None) -> tuple[str, str]:
    sid = uuid.uuid4()
    token, token_hash = new_sender_token(sid.hex)
    async with db.sessionmaker()() as s:
        s.add(m.AudioSender(id=sid, campus_id=campus_id, name="Booth", token_hash=token_hash, allowed_cidrs=cidrs or []))
        await s.commit()
    return str(sid), token


@pytest.fixture
async def ingest(clean, run_server):
    ingest_mod.state.__init__()  # fresh caches/limiter per test
    async with run_server(ingest_mod.app) as srv:
        yield srv


def ws_url(srv, rate=16000):
    return f"ws://127.0.0.1:{srv.port}/ingest/v1/stream?sample_rate={rate}&channels=1&format=s16le"


async def expect_rejected(url, headers=None):
    with pytest.raises(InvalidStatus) as e:
        async with connect(url, additional_headers=headers or {}):
            pass
    assert e.value.response.status_code == 403


async def test_rejects_missing_bad_and_forged_tokens(ingest):
    cid = await make_campus("east")
    _, token = await make_sender(cid)
    await expect_rejected(ws_url(ingest))
    await expect_rejected(ws_url(ingest), {"Authorization": "Bearer nope"})
    forged = token[:-4] + "AAAA"
    await expect_rejected(ws_url(ingest), {"Authorization": f"Bearer {forged}"})
    fake = "cs_" + uuid.uuid4().hex + "_" + "x" * 43
    await expect_rejected(ws_url(ingest), {"Authorization": f"Bearer {fake}"})


async def test_rejects_bad_audio_format(ingest):
    cid = await make_campus("east")
    _, token = await make_sender(cid)
    await expect_rejected(ws_url(ingest, rate=12345), {"Authorization": f"Bearer {token}"})


async def test_ip_allowlist(ingest):
    cid = await make_campus("east")
    _, token = await make_sender(cid, cidrs=["203.0.113.0/24"])
    await expect_rejected(ws_url(ingest), {"Authorization": f"Bearer {token}"})
    _, token_ok = await make_sender(cid, cidrs=["127.0.0.0/8"])
    async with connect(ws_url(ingest), additional_headers={"Authorization": f"Bearer {token_ok}"}) as ws:
        await ws.send(FRAME)


async def test_audio_forwarded_only_while_live(ingest, redis_client):
    r = redis_client
    cid = await make_campus("east")
    _, token = await make_sender(cid)
    rb = r  # stream entries are small; decoded client is fine for length checks
    async with connect(ws_url(ingest), additional_headers={"Authorization": f"Bearer {token}"}) as ws:
        for _ in range(5):
            await ws.send(FRAME)
        await asyncio.sleep(0.3)
        st = await r.hgetall(rkeys.audio_status(cid))
        assert st["connected"] == "1" and st["live"] == "0"
        assert float(st["level_dbfs"]) < -60
        assert await rb.xlen(rkeys.audio_stream(cid)) == 0  # outside a window: never forwarded

        await r.set(rkeys.campus_live_flag(cid), "e1", ex=30)
        await asyncio.sleep(1.1)  # ingest re-checks the live flag every second
        for _ in range(5):
            await ws.send(FRAME)
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        assert await rb.xlen(rkeys.audio_stream(cid)) >= 4
        msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
        assert msg["type"] == "status" and msg["campus"] == "east"
    await asyncio.sleep(0.2)
    st = await r.hgetall(rkeys.audio_status(cid))
    assert st["connected"] == "0"
    history = [json.loads(h)["event"] for h in await r.lrange(rkeys.audio_history(cid), 0, -1)]
    assert history[:2] == ["disconnected", "connected"]


async def test_oversized_frame_disconnects(ingest):
    cid = await make_campus("east")
    _, token = await make_sender(cid)
    async with connect(ws_url(ingest), additional_headers={"Authorization": f"Bearer {token}"}) as ws:
        await ws.send(b"\x00\x01" * 20000)  # 40 KB > 32 KB limit
        with pytest.raises(ConnectionClosed):
            for _ in range(20):
                await ws.send(FRAME)
                await asyncio.sleep(0.05)


async def test_newer_connection_replaces_older(ingest):
    cid = await make_campus("east")
    _, token = await make_sender(cid)
    hdr = {"Authorization": f"Bearer {token}"}
    async with connect(ws_url(ingest), additional_headers=hdr) as old:
        await old.send(FRAME)
        async with connect(ws_url(ingest), additional_headers=hdr) as new:
            await new.send(FRAME)
            with pytest.raises(ConnectionClosed) as e:
                await asyncio.wait_for(old.recv(), 3)
                await asyncio.wait_for(old.recv(), 3)
            assert e.value.rcvd.code == 4009


async def test_revoked_sender_cannot_connect(ingest, redis_client):
    cid = await make_campus("east")
    sid, token = await make_sender(cid)
    async with db.sessionmaker()() as s:
        sender = await s.get(m.AudioSender, uuid.UUID(sid))
        sender.revoked_at = m.utcnow()
        await s.commit()
    await redis_client.publish(rkeys.INGEST_REVOKED_CHANNEL, sid)
    await asyncio.sleep(0.2)
    await expect_rejected(ws_url(ingest), {"Authorization": f"Bearer {token}"})


async def test_disabled_campus_rejects_sender(ingest):
    cid = await make_campus("east", enabled=False)
    _, token = await make_sender(cid)
    await expect_rejected(ws_url(ingest), {"Authorization": f"Bearer {token}"})


async def test_repeated_auth_failures_are_rate_limited(ingest):
    for _ in range(12):
        try:
            async with connect(ws_url(ingest), additional_headers={"Authorization": "Bearer bad"}):
                pass
        except InvalidStatus:
            pass
    assert ingest_mod.state.failures.blocked("127.0.0.1")
