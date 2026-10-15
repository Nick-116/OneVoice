"""Translation provider failures stay isolated per language; circuit breaker + notices."""

import asyncio
import time

from captions.providers.translate.simulated import SimulatedTranslator
from captions.worker.translation import FAILURES_TO_OPEN, LanguageChannel, SourceSegment


def make_channel(lang, provider, published, notices):
    async def publish(code, seq, text, final, lat):
        published.append((code, seq, text, final))

    async def notice(code, what):
        notices.append((code, what))

    async def on_error(msg):
        pass

    return LanguageChannel(
        lang=lang, source="en", provider=provider, provider_overrides=None, publish=publish, notice=notice,
        on_error=on_error, on_usage=lambda *a: None, on_latency=lambda *a: None,
    )


async def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met")


async def test_one_language_failing_does_not_affect_others():
    provider = SimulatedTranslator({"fail_languages": ["fr"], "delay_ms": 0})
    published, notices = [], []
    es = make_channel("es", provider, published, notices)
    fr = make_channel("fr", provider, published, notices)
    es.start()
    fr.start()
    try:
        for i in range(1, FAILURES_TO_OPEN + 2):
            seg = SourceSegment(i, f"sentence {i}", time.monotonic())
            es.submit_final(seg)
            fr.submit_final(seg)
        await wait_for(lambda: len([p for p in published if p[0] == "es"]) == FAILURES_TO_OPEN + 1)
        await wait_for(lambda: ("fr", "translation_unavailable") in notices)
        assert not [p for p in published if p[0] == "fr"]
        assert es.state == "ok" and fr.state == "failing"
        assert published[0] == ("es", 1, "[es] sentence 1", True)
    finally:
        await es.stop()
        await fr.stop()


async def test_recovery_publishes_restored_notice():
    provider = SimulatedTranslator({"fail_languages": ["ko"], "delay_ms": 0})
    published, notices = [], []
    ko = make_channel("ko", provider, published, notices)
    ko.start()
    try:
        for i in range(1, FAILURES_TO_OPEN + 1):
            ko.submit_final(SourceSegment(i, "x", time.monotonic()))
        await wait_for(lambda: ko.state == "failing")
        provider.fail_languages.clear()
        ko.opened_at = 0  # skip cooldown
        ko.submit_final(SourceSegment(99, "back", time.monotonic()))
        await wait_for(lambda: ("ko", "translation_restored") in notices)
        assert ("ko", 99, "[ko] back", True) in published
    finally:
        await ko.stop()


async def test_backlog_is_bounded_and_drops_oldest():
    provider = SimulatedTranslator({"delay_ms": 0})
    ch = make_channel("es", provider, [], [])
    for i in range(100):
        ch.submit_final(SourceSegment(i, "x", time.monotonic()))
    assert ch.queue.qsize() == ch.queue.maxsize
    assert ch.queue.get_nowait().seq == 100 - ch.queue.maxsize
