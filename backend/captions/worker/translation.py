"""Per-language translation channels.

One channel per (campus, target language) that has at least one viewer. All
viewers of that language share its output, so 100 Spanish viewers cost exactly
the same as one. Channels are isolated: a failing language never blocks the
others, and each has a small circuit breaker so a provider outage does not
pile up requests.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..providers.translate import TranslationError, TranslationProvider

log = logging.getLogger(__name__)

TRANSLATE_TIMEOUT = 6.0
FAILURES_TO_OPEN = 3
OPEN_COOLDOWN = 15.0


@dataclass
class SourceSegment:
    seq: int
    text: str
    final_at: float  # time.monotonic() when the source final was produced
    audio_wall: float | None = None  # wall clock time of the end of the audio


PublishFn = Callable[[str, int, str, bool, float | None], Awaitable[None]]
NoticeFn = Callable[[str, str], Awaitable[None]]
ErrorFn = Callable[[str], Awaitable[None]]
UsageFn = Callable[[str, int], None]
LatencyFn = Callable[[str, float, float | None], None]


class LanguageChannel:
    def __init__(
        self,
        lang: str,
        source: str,
        provider: TranslationProvider,
        provider_overrides: dict[str, str] | None,
        publish: PublishFn,
        notice: NoticeFn,
        on_error: ErrorFn,
        on_usage: UsageFn,
        on_latency: LatencyFn,
        translate_partials: bool = False,
        partial_interval: float = 1.5,
    ) -> None:
        self.lang = lang
        self.source = source
        self.provider = provider
        self.overrides = provider_overrides
        self.publish = publish
        self.notice = notice
        self.on_error = on_error
        self.on_usage = on_usage
        self.on_latency = on_latency
        self.translate_partials = translate_partials
        self.partial_interval = partial_interval

        self.queue: asyncio.Queue[SourceSegment] = asyncio.Queue(maxsize=20)
        self.state = "ok"  # ok | failing
        self.failures = 0
        self.opened_at = 0.0
        self.last_final_seq = 0
        self._partial: tuple[int, str] | None = None
        self._partial_event = asyncio.Event()
        self._last_partial_sent: tuple[int, str] | None = None
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._final_loop(), name=f"tr-final-{self.lang}"))
        if self.translate_partials:
            self._tasks.append(asyncio.create_task(self._partial_loop(), name=f"tr-partial-{self.lang}"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def submit_final(self, seg: SourceSegment) -> None:
        if self.queue.full():
            # Prefer live captions over completeness: drop the oldest backlog item.
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(seg)

    def submit_partial(self, seq: int, text: str) -> None:
        if self.translate_partials:
            self._partial = (seq, text)
            self._partial_event.set()

    async def _translate(self, text: str) -> str:
        """Translate with one quick retry; raises TranslationError."""
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await asyncio.wait_for(
                    self.provider.translate([text], self.source, self.lang, self.overrides), TRANSLATE_TIMEOUT
                )
                self.on_usage(self.lang, len(text))
                return result[0]
            except asyncio.TimeoutError as e:
                err = TranslationError("translation timed out")
                if attempt >= 2:
                    raise err from e
            except TranslationError as e:
                if not e.retryable or attempt >= 2:
                    raise
            await asyncio.sleep(0.4)

    def _circuit_open(self) -> bool:
        return self.state == "failing" and time.monotonic() - self.opened_at < OPEN_COOLDOWN

    async def _final_loop(self) -> None:
        while True:
            seg = await self.queue.get()
            if self._circuit_open():
                continue
            started = time.monotonic()
            try:
                translated = await self._translate(seg.text)
            except TranslationError as e:
                self.failures += 1
                await self.on_error(f"translation to {self.lang} failed: {e}")
                if self.failures >= FAILURES_TO_OPEN and self.state != "failing":
                    self.state = "failing"
                    await self.notice(self.lang, "translation_unavailable")
                if self.state == "failing":
                    self.opened_at = time.monotonic()
                continue
            except Exception as e:  # defensive: never kill the loop
                log.exception("unexpected translation error")
                await self.on_error(f"translation to {self.lang} crashed: {e!r}")
                continue
            now = time.monotonic()
            self.on_latency(self.lang, (now - started) * 1000, (time.time() - seg.audio_wall) * 1000 if seg.audio_wall else None)
            if self.state == "failing":
                self.state = "ok"
                await self.notice(self.lang, "translation_restored")
            self.failures = 0
            self.last_final_seq = max(self.last_final_seq, seg.seq)
            e2e = (time.time() - seg.audio_wall) * 1000 if seg.audio_wall else None
            await self.publish(self.lang, seg.seq, translated, True, e2e)

    async def _partial_loop(self) -> None:
        while True:
            await self._partial_event.wait()
            self._partial_event.clear()
            item = self._partial
            if item is None:
                continue
            seq, text = item
            prev = self._last_partial_sent
            # Skip tiny or barely changed partials: they cost money and cause flicker.
            if seq <= self.last_final_seq or len(text) < 15:
                continue
            if prev and prev[0] == seq and len(text) - len(prev[1]) < 12:
                continue
            if self._circuit_open():
                continue
            try:
                translated = await self._translate(text)
            except Exception:
                continue  # partial failures are silent; finals report errors
            if seq > self.last_final_seq:
                self._last_partial_sent = (seq, text)
                await self.publish(self.lang, seq, translated, False, None)
            await asyncio.sleep(self.partial_interval)
