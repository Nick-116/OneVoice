"""Local audio input on the server: capture, status, worker config, ingest exclusivity, admin fields."""

import asyncio
import json
import uuid

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from captions import db, rkeys
from captions import models as m
from captions.localaudio.service import TEST_DEVICE, LocalAudioService, TestToneBackend
from captions.security import new_sender_token

from .conftest import make_campus, needs_services

pytestmark = needs_services


async def wait_until(cond, timeout=8.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if await cond():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("condition not met in time")


async def test_test_tone_capture_feeds_the_pipeline_only_while_live(clean, redis_client):
    r = redis_client
    cid = await make_campus("east", audio_source="local", local_device=TEST_DEVICE, local_channel=1)
    await r.set(rkeys.LOCALAUDIO_CONFIG, json.dumps([{"campus_id": cid, "slug": "east", "device": TEST_DEVICE, "channel": 1}]))
    svc = LocalAudioService(r, TestToneBackend())
    try:
        await svc.reconcile()
        devices = json.loads(await r.get(rkeys.LOCALAUDIO_DEVICES))
        assert devices[0]["name"] == TEST_DEVICE and await r.get(rkeys.LOCALAUDIO_HEARTBEAT)

        async def connected():
            st = await r.hgetall(rkeys.audio_status(cid))
            return st.get("connected") == "1" and st.get("source") == "local"
        await wait_until(connected)
        assert await r.xlen(rkeys.audio_stream(cid)) == 0  # not live: level meter only, nothing forwarded

        await r.set(rkeys.campus_live_flag(cid), "e1", ex=30)

        async def forwarding():
            return await r.xlen(rkeys.audio_stream(cid)) >= 5
        await wait_until(forwarding)
        st = await r.hgetall(rkeys.audio_status(cid))
        assert st["live"] == "1" and float(st["level_dbfs"]) > -40 and st["sample_rate"] == "16000"
        from captions.redisio import make_redis

        rb = make_redis(decode=False)  # audio frames are binary
        entry = (await rb.xrange(rkeys.audio_stream(cid), count=1))[0][1]
        await rb.aclose()
        assert len(entry[b"pcm"]) == 3200  # 100 ms of 16 kHz s16le

        # Switching the campus away from local input stops the capture.
        await r.set(rkeys.LOCALAUDIO_CONFIG, "[]")
        await svc.reconcile()
        assert cid not in svc.captures
        assert (await r.hgetall(rkeys.audio_status(cid)))["connected"] == "0"
    finally:
        await svc.stop_all()


async def test_missing_device_is_reported(clean, redis_client):
    r = redis_client
    cid = await make_campus("east", audio_source="local", local_device="USB Audio CODEC", local_channel=1)
    await r.set(rkeys.LOCALAUDIO_CONFIG, json.dumps([{"campus_id": cid, "slug": "east", "device": "USB Audio CODEC", "channel": 1}]))
    svc = LocalAudioService(r, TestToneBackend())
    await svc.reconcile()
    st = await r.hgetall(rkeys.audio_status(cid))
    assert st["connected"] == "0" and "not found" in st["local_error"]


async def test_worker_publishes_local_inputs_only(clean, redis_client):
    from captions.redisio import make_redis
    from captions.worker.supervisor import Supervisor

    local = await make_campus("east", audio_source="local", local_device=TEST_DEVICE, local_channel=2)
    await make_campus("west", audio_source="remote")
    sup = Supervisor(make_redis(), make_redis(decode=False))
    try:
        await sup.reload_config()
        await sup.tick()
    finally:
        await sup.stop_all()
    cfg = json.loads(await redis_client.get(rkeys.LOCALAUDIO_CONFIG))
    assert cfg == [{"campus_id": local, "slug": "east", "device": TEST_DEVICE, "channel": 2}]


async def test_sender_is_refused_for_a_local_audio_campus(clean, run_server):
    from captions.ingest import app as ingest_mod

    cid = await make_campus("east", audio_source="local")
    sid = uuid.uuid4()
    token, token_hash = new_sender_token(sid.hex)
    async with db.sessionmaker()() as s:
        s.add(m.AudioSender(id=sid, campus_id=cid, name="Booth", token_hash=token_hash, allowed_cidrs=[]))
        await s.commit()
    ingest_mod.state.__init__()
    async with run_server(ingest_mod.app) as srv:
        url = f"ws://127.0.0.1:{srv.port}/ingest/v1/stream?sample_rate=16000&channels=1&format=s16le"
        async with connect(url, additional_headers={"Authorization": f"Bearer {token}"}) as ws:
            with pytest.raises(ConnectionClosed) as e:
                await asyncio.wait_for(ws.recv(), 3)
            assert e.value.rcvd.code == 4010


async def test_admin_campus_audio_source_fields(clean, redis_client, run_server):
    from captions.admin.app import create_app

    from .test_admin_api import Admin, create_user

    await create_user()
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        a = Admin(c)
        await a.login()
        await a.enrol_mfa()
        r = await a.post("/api/campuses", json={"slug": "east", "name": "East"})
        campus = r.json()
        assert campus["audio_source"] == "local" and campus["local_channel"] == 1  # local input is the default
        r = await a.patch(f"/api/campuses/{campus['id']}", json={"local_device": TEST_DEVICE, "local_channel": 3})
        assert r.json()["local_device"] == TEST_DEVICE and r.json()["local_channel"] == 3
        r = await a.patch(f"/api/campuses/{campus['id']}", json={"audio_source": "remote"})
        assert r.json()["audio_source"] == "remote"
        assert (await a.patch(f"/api/campuses/{campus['id']}", json={"audio_source": "usb"})).status_code == 422

        assert (await a.get("/api/audio/local")).json() == {"online": False, "devices": []}
        await redis_client.set(rkeys.LOCALAUDIO_HEARTBEAT, str(asyncio.get_running_loop().time() * 0 + __import__("time").time()))
        await redis_client.set(rkeys.LOCALAUDIO_DEVICES, json.dumps([{"name": TEST_DEVICE, "hostapi": "simulated", "channels": 2, "rate": 48000}]))
        local = (await a.get("/api/audio/local")).json()
        assert local["online"] is True and local["devices"][0]["name"] == TEST_DEVICE
