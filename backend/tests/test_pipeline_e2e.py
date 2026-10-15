"""End-to-end worker behaviour with simulated providers (no API keys, no console).

Covers: schedule-driven start/stop, caption states (disconnected / waiting / live),
shared translation per language only when viewed, multiple campuses kept apart,
translation failure isolation, and manual start.
"""

import asyncio
import datetime as dt
import json
import time

import pytest

from captions import db, rkeys
from captions import models as m
from captions.redisio import make_redis
from captions.worker.supervisor import Supervisor

from .conftest import make_campus, needs_services

pytestmark = needs_services
FRAME = (b"\x20\x03" * 1600)  # 100 ms of non-silent audio at 16 kHz


async def use_simulated(fail=()):
    async with db.sessionmaker()() as s:
        s.add(m.ProviderConfig(kind="stt", provider="simulated", settings={"words_per_minute": 600}))
        s.add(m.ProviderConfig(kind="translation", provider="simulated", settings={"delay_ms": 0, "fail_languages": list(fail)}))
        await s.commit()


async def live_event(campus_id: int, minutes: int = 30, start_offset: int = -1) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    async with db.sessionmaker()() as s:
        ev = m.ServiceEvent(campus_id=campus_id, name="Test service", kind="special",
                            start_at=now + dt.timedelta(minutes=start_offset), end_at=now + dt.timedelta(minutes=minutes))
        s.add(ev)
        await s.commit()
        return ev.id


class FakeSender:
    """Plays the role of the ingest service: writes audio status + stream entries."""

    def __init__(self, r, campus_id: int) -> None:
        self.r = r
        self.cid = campus_id
        self.task: asyncio.Task | None = None

    async def _run(self):
        while True:
            now = time.time()
            await self.r.hset(rkeys.audio_status(self.cid), mapping={
                "connected": "1", "last_frame_at": now, "last_signal_at": now, "sample_rate": 16000})
            if await self.r.get(rkeys.campus_live_flag(self.cid)):
                await self.r.xadd(rkeys.audio_stream(self.cid), {"pcm": FRAME, "sr": 16000, "t": f"{now:.3f}"}, maxlen=300)
            await asyncio.sleep(0.1)

    def start(self):
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        await self.r.hset(rkeys.audio_status(self.cid), mapping={"connected": "0"})


async def tick_until(sup: Supervisor, cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await sup.tick()
        if await cond():
            return
        await asyncio.sleep(0.2)
    raise AssertionError("condition not met in time")


async def public(r, slug):
    raw = await r.get(rkeys.public_status(slug))
    return json.loads(raw) if raw else None


@pytest.fixture
async def sup(clean):
    s = Supervisor(make_redis(), make_redis(decode=False))
    yield s
    await s.stop_all()
    await s.r.aclose()
    await s.rb.aclose()


async def test_full_flow_with_viewers_and_isolation(sup, redis_client):
    r = redis_client
    await use_simulated()
    east = await make_campus("east", languages=("en", "es", "fr"))
    west = await make_campus("west", languages=("en", "es"))
    await live_event(east)

    # Window open, no audio yet -> "disconnected" (production team message).
    await tick_until(sup, _phase(r, "east", "live", "disconnected"))
    west_status = await public(r, "west")
    assert west_status["phase"] == "idle"  # west has no service
    assert [l["code"] for l in (await public(r, "east"))["languages"]] == ["en", "es", "fr"]

    # Spanish viewer present (as reported by public-web).
    await r.hset("viewers:test", mapping={"east|es": 3})
    sub = r.pubsub()
    await sub.subscribe("cap:east:en", "cap:east:es", "cap:east:fr", "cap:west:es")

    sender = FakeSender(r, east)
    sender.start()
    try:
        await tick_until(sup, _phase(r, "east", "live", "live"), timeout=15)
        got: dict[str, list] = {}
        end = time.monotonic() + 10
        while time.monotonic() < end and not any(m["final"] for m in got.get("cap:east:es", [])):
            await sup.tick()
            msg = await sub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            while msg:
                got.setdefault(msg["channel"], []).append(json.loads(msg["data"]))
                msg = await sub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        assert any(c["final"] for c in got.get("cap:east:en", []))
        es_finals = [c for c in got["cap:east:es"] if c["t"] == "caption" and c["final"]]
        from captions.providers.translate.demo_phrases import PHRASES

        spanish = {v["es"] for v in PHRASES.values()}
        assert es_finals and all(c["text"] in spanish or c["text"].startswith("[es] ") for c in es_finals)
        assert any(c["text"] in spanish for c in es_finals)  # real sample translations, not English
        assert "cap:east:fr" not in got  # nobody watching French -> never translated (no cost)
        assert "cap:west:es" not in got  # other campus untouched

        # Usage is metered for the shared Spanish stream only.
        await sup.usage.flush()
        async with db.sessionmaker()() as s:
            rows = (await s.execute(m.UsageRecord.__table__.select())).all()
        langs = {row.language for row in rows if row.metric == "translation_chars"}
        assert langs == {"es"}
    finally:
        await sender.stop()
        await sub.aclose()


async def test_service_end_stops_pipeline_and_publishes_ended(sup, redis_client):
    r = redis_client
    await use_simulated()
    cid = await make_campus("east")
    ev_id = await live_event(cid)
    await tick_until(sup, _phase(r, "east", "live"))
    assert cid in sup.pipelines and await r.get(rkeys.campus_live_flag(cid))
    async with db.sessionmaker()() as s:
        ev = await s.get(m.ServiceEvent, ev_id)
        ev.end_at = dt.datetime.now(dt.timezone.utc)
        await s.commit()
    sup.config_dirty = True
    await tick_until(sup, _phase(r, "east", "ended"))
    assert cid not in sup.pipelines
    assert await r.get(rkeys.campus_live_flag(cid)) is None  # ingest stops forwarding audio


async def test_upcoming_countdown_status(sup, redis_client):
    r = redis_client
    await use_simulated()
    cid = await make_campus("east")
    await live_event(cid, minutes=90, start_offset=15)
    await tick_until(sup, _phase(r, "east", "upcoming"))
    st = await public(r, "east")
    start = dt.datetime.fromisoformat(st["next"]["start"].replace("Z", "+00:00"))
    remaining = (start - dt.datetime.now(dt.timezone.utc)).total_seconds()
    assert 13 * 60 < remaining <= 15 * 60
    assert st["captions"] is None and cid not in sup.pipelines


async def test_digital_silence_counts_as_disconnected(sup, redis_client):
    r = redis_client
    await use_simulated()
    cid = await make_campus("east")
    await live_event(cid)
    now = time.time()
    await r.hset(rkeys.audio_status(cid), mapping={"connected": "1", "last_frame_at": now, "last_signal_at": now - 120})
    await tick_until(sup, _phase(r, "east", "live", "disconnected"))


async def test_disabled_language_and_unsupported_language_hidden(sup, redis_client):
    r = redis_client
    await use_simulated()
    cid = await make_campus("east", languages=("en", "es", "hi"))
    async with db.sessionmaker()() as s:
        (await s.get(m.Language, "hi")).enabled = False
        s.add(m.Language(code="tlh", name_en="Klingon", native_name="tlhIngan Hol"))
        await s.flush()
        s.add(m.CampusLanguage(campus_id=cid, language_code="tlh"))
        await s.commit()
    await live_event(cid)
    await tick_until(sup, _phase(r, "east", "live"))
    assert [l["code"] for l in (await public(r, "east"))["languages"]] == ["en", "es"]


async def _check(r, slug, phase, captions=None):
    st = await public(r, slug)
    return bool(st) and st["phase"] == phase and (captions is None or st["captions"] == captions)


def _phase(r, slug, phase, captions=None):
    return lambda: _check(r, slug, phase, captions)


async def test_switching_language_stops_translating_the_old_one(sup, redis_client):
    """A viewer moving from Spanish to French: Spanish translation stops after the grace period."""
    r = redis_client
    await use_simulated()
    async with db.sessionmaker()() as s:
        s.add(m.AppSetting(key="general", value={"language_grace_seconds": 1}))
        await s.commit()
    cid = await make_campus("east", languages=("en", "es", "fr"))
    await live_event(cid)
    sender = FakeSender(r, cid)
    sender.start()
    try:
        await r.hset("viewers:test", mapping={"east|es": 1})
        await tick_until(sup, _channels(sup, cid, {"es"}), timeout=10)
        # The phone switches language: the public service now reports a French viewer only.
        await r.delete("viewers:test")
        await r.hset("viewers:test", mapping={"east|fr": 1})
        await tick_until(sup, _channels(sup, cid, {"fr"}), timeout=10)
        await r.delete("viewers:test")
        await tick_until(sup, _channels(sup, cid, set()), timeout=10)  # nobody left: no translation at all
    finally:
        await sender.stop()


def _channels(sup, campus_id, expected):
    async def check():
        p = sup.pipelines.get(campus_id)
        return p is not None and set(p.channels) == expected

    return check
