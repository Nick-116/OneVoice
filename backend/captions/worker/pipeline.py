"""Live caption pipeline for one campus during one service occurrence.

audio (Redis stream from ingest) -> STT session -> Segmenter -> source captions
                                                         `-> LanguageChannel per viewed language

The pipeline only exists while the campus is inside a service window; the
supervisor creates and cancels it, so nothing is transcribed or translated
(or billed) outside scheduled services.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import redis.asyncio as aioredis

from .. import db, rkeys
from ..config_store import CampusConfig, LanguageConfig
from ..models import Transcript
from ..providers.stt import STTError, STTProvider, STTSession
from ..providers.translate import TranslationProvider
from ..redisio import record_error
from .metrics import CampusMetrics, UsageMeter
from .publisher import CaptionPublisher
from .segmenter import Segment, Segmenter
from .translation import LanguageChannel, SourceSegment

log = logging.getLogger(__name__)

# If the newest audio chunk is older than this, skip ahead (prefer live over backlog).
MAX_AUDIO_LAG = 2.0
# Close the STT session after this long without audio to stop billing.
CLOSE_STT_AFTER = 10.0
KEEPALIVE_EVERY = 4.0


@dataclass
class PipelineOptions:
    translate_partials: bool = False
    partial_interval: float = 1.5
    language_grace: float = 60.0
    stt_price_per_minute: float = 0.0
    translation_price_per_million: float = 0.0


@dataclass
class PipelineState:
    stt: str = "idle"  # idle | connecting | connected | error
    stt_error: str | None = None
    stt_error_since: float | None = None
    stt_connected_since: float | None = None
    first_result_at: float | None = None
    last_caption_at: float | None = None
    segments: int = 0
    languages: dict[str, str] = field(default_factory=dict)  # lang -> ok|failing


class CampusPipeline:
    def __init__(
        self,
        *,
        campus: CampusConfig,
        occurrence_key: str,
        languages: dict[str, LanguageConfig],
        r_text: aioredis.Redis,
        r_bin: aioredis.Redis,
        stt: STTProvider,
        translator: TranslationProvider,
        options: PipelineOptions,
        usage: UsageMeter,
        viewer_counts: Callable[[], dict[str, int]],
    ) -> None:
        self.campus = campus
        self.occ = occurrence_key
        self.languages = languages
        self.r = r_text
        self.rb = r_bin
        self.stt_provider = stt
        self.translator = translator
        self.opts = options
        self.usage = usage
        self.viewer_counts = viewer_counts
        self.publisher = CaptionPublisher(r_text, campus.slug, occurrence_key)
        self.metrics = CampusMetrics()
        self.state = PipelineState()
        self.channels: dict[str, LanguageChannel] = {}
        self._channel_last_viewed: dict[str, float] = {}
        self.segmenter = Segmenter(early_commit=stt.early_commit)
        self.recent_finals: deque[SourceSegment] = deque(maxlen=3)
        self._transcript_queue: asyncio.Queue[tuple[str, int, str]] = asyncio.Queue(maxsize=2000)
        self._task: asyncio.Task | None = None
        # Map STT audio offsets back to wall-clock receive time for latency metrics.
        self._offsets: deque[tuple[float, float]] = deque(maxlen=600)
        self._sent_seconds = 0.0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._main(), name=f"pipeline-{self.campus.slug}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        for ch in list(self.channels.values()):
            await ch.stop()
        self.channels.clear()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _main(self) -> None:
        await self.publisher.clear_buffers([self.campus.source_language, *self.languages.keys()])
        aux = [asyncio.create_task(self._language_manager())]
        if self.campus.retain_transcripts:
            aux.append(asyncio.create_task(self._transcript_writer()))
        try:
            await self._stt_loop()
        finally:
            for t in aux:
                t.cancel()
            await asyncio.gather(*aux, return_exceptions=True)

    # ------------------------------------------------------------------ audio / STT
    async def _audio_available(self) -> tuple[bool, int]:
        st = await self.r.hgetall(rkeys.audio_status(self.campus.id))
        if not st or st.get("connected") != "1":
            return False, 16000
        last = float(st.get("last_frame_at") or 0)
        return time.time() - last < 3.0, int(st.get("sample_rate") or 16000)

    async def _stt_loop(self) -> None:
        backoff = 1.0
        while True:
            ok, sample_rate = await self._audio_available()
            if not ok:
                self.state.stt = "idle" if self.state.stt != "error" else "error"
                await asyncio.sleep(0.5)
                continue
            self.state.stt = "connecting"
            try:
                session = await self.stt_provider.open(sample_rate=sample_rate, language=self.campus.source_language)
            except STTError as e:
                await self._stt_failed(str(e))
                await asyncio.sleep(backoff if e.retryable else 30.0)
                backoff = min(backoff * 2, 30.0)
                continue
            self.state.stt = "connected"
            self.state.stt_error = None
            self.state.stt_error_since = None
            self.state.stt_connected_since = time.time()
            backoff = 1.0
            log.info("stt session open", extra={"fields": {"campus": self.campus.slug, "provider": self.stt_provider.name}})
            try:
                await self._run_session(session, sample_rate)
                # Session ended because audio stopped; go back to waiting.
                self.state.stt = "idle"
            except STTError as e:
                await self._stt_failed(str(e))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # e.g. Redis connection blip: log, back off briefly and reopen.
                log.exception("caption session error")
                await record_error(self.r, "pipeline", f"session error: {e!r}", self.campus.id)
                await asyncio.sleep(min(backoff, 5.0))
                backoff = min(backoff * 2, 30.0)
            finally:
                await session.close()
                for seg in self.segmenter.flush():
                    await self._handle_segment(seg)

    async def _stt_failed(self, message: str) -> None:
        self.state.stt = "error"
        self.state.stt_error = message
        if self.state.stt_error_since is None:
            self.state.stt_error_since = time.time()
        log.warning("stt failure", extra={"fields": {"campus": self.campus.slug, "error": message}})
        await record_error(self.r, "stt", message, self.campus.id)

    async def _run_session(self, session: STTSession, sample_rate: int) -> None:
        self._sent_seconds = 0.0
        self._offsets.clear()
        pump = asyncio.create_task(self._pump_audio(session, sample_rate))
        consume = asyncio.create_task(self._consume(session))
        done, pending = await asyncio.wait({pump, consume}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        errors = [t.exception() for t in done if t.exception()]
        if errors:
            raise errors[0]

    async def _pump_audio(self, session: STTSession, sample_rate: int) -> None:
        key = rkeys.audio_stream(self.campus.id)
        last_id = "$"
        last_audio = time.monotonic()
        last_keepalive = time.monotonic()
        self._unbilled = 0.0
        try:
            while True:
                resp = await self.rb.xread({key: last_id}, block=1000, count=50)
                now = time.monotonic()
                if not resp:
                    if now - last_audio > CLOSE_STT_AFTER:
                        return
                    if now - last_keepalive > KEEPALIVE_EVERY:
                        await session.keepalive()
                        last_keepalive = now
                    continue
                entries = resp[0][1]
                last_id = entries[-1][0]
                wall_now = time.time()
                for _eid, fields in entries:
                    # Skip stale chunks (e.g. after a hiccup): live audio beats backlog.
                    if wall_now - float(fields[b"t"]) > MAX_AUDIO_LAG:
                        continue
                    if int(fields.get(b"sr", sample_rate)) != sample_rate:
                        return  # sample rate changed: reopen the session at the new rate
                    pcm = fields[b"pcm"]
                    await session.send_audio(pcm)
                    secs = len(pcm) / 2 / sample_rate
                    self._sent_seconds += secs
                    self._offsets.append((self._sent_seconds, float(fields[b"t"])))
                    self._unbilled += secs
                    last_audio = last_keepalive = now
                if self._unbilled >= 5.0:
                    self._bill_stt(self._unbilled)
                    self._unbilled = 0.0
        finally:
            if self._unbilled:
                self._bill_stt(self._unbilled)
                self._unbilled = 0.0

    def _bill_stt(self, seconds: float) -> None:
        cost = seconds / 60.0 * self.opts.stt_price_per_minute
        self.usage.add(self.campus.id, self.stt_provider.name, "stt_seconds", seconds, cost)

    def _wall_for_offset(self, audio_end: float | None) -> float | None:
        if not self._offsets:
            return None
        if audio_end is None:
            return self._offsets[-1][1]
        for sent, wall in self._offsets:
            if sent >= audio_end:
                return wall
        return self._offsets[-1][1]

    async def _consume(self, session: STTSession) -> None:
        async for ev in session.events():
            if self.state.first_result_at is None and ev.text:
                self.state.first_result_at = time.time()
            if ev.kind == "interim":
                segs = self.segmenter.on_interim(ev.text, ev.audio_end)
            elif ev.kind == "stable":
                segs = self.segmenter.on_stable(ev.text, ev.audio_end)
            else:
                segs = self.segmenter.on_endpoint(ev.audio_end)
            for seg in segs:
                await self._handle_segment(seg)

    # ------------------------------------------------------------------ captions
    async def _handle_segment(self, seg: Segment) -> None:
        src = self.campus.source_language
        wall = self._wall_for_offset(seg.audio_end)
        latency = (time.time() - wall) * 1000 if wall else None
        if latency is not None:
            (self.metrics.stt_final_ms if seg.final else self.metrics.stt_partial_ms).add(latency)
        await self.publisher.caption(src, seg.seq, seg.text, seg.final, latency)
        self.state.last_caption_at = time.time()
        if seg.final:
            self.state.segments += 1
            source = SourceSegment(seg.seq, seg.text, time.monotonic(), wall)
            self.recent_finals.append(source)
            self._queue_transcript(src, seg.seq, seg.text)
            for ch in self.channels.values():
                ch.submit_final(source)
        else:
            for ch in self.channels.values():
                ch.submit_partial(seg.seq, seg.text)

    async def _publish_translation(self, lang: str, seq: int, text: str, final: bool, latency: float | None) -> None:
        await self.publisher.caption(lang, seq, text, final, latency)
        if final:
            self._queue_transcript(lang, seq, text)

    def _queue_transcript(self, lang: str, seq: int, text: str) -> None:
        if self.campus.retain_transcripts:
            try:
                self._transcript_queue.put_nowait((lang, seq, text))
            except asyncio.QueueFull:
                pass

    async def _transcript_writer(self) -> None:
        while True:
            batch = [await self._transcript_queue.get()]
            await asyncio.sleep(2)
            while not self._transcript_queue.empty():
                batch.append(self._transcript_queue.get_nowait())
            try:
                async with db.sessionmaker()() as s:
                    s.add_all(
                        Transcript(campus_id=self.campus.id, occurrence_key=self.occ, language=lang, seq=seq, text=text)
                        for lang, seq, text in batch
                    )
                    await s.commit()
            except Exception as e:
                await record_error(self.r, "transcripts", f"could not store transcript: {e!r}", self.campus.id)

    # ------------------------------------------------------------------ languages
    def _make_channel(self, lang: str) -> LanguageChannel:
        price = self.opts.translation_price_per_million

        def on_usage(code: str, chars: int) -> None:
            self.usage.add(self.campus.id, self.translator.name, "translation_chars", chars, chars / 1_000_000 * price, code)

        def on_latency(code: str, tr_ms: float, e2e_ms: float | None) -> None:
            self.metrics.translate_ms[code].add(tr_ms)
            if e2e_ms is not None:
                self.metrics.end_to_end_ms[code].add(e2e_ms)

        async def on_error(message: str) -> None:
            await record_error(self.r, "translation", message, self.campus.id)

        return LanguageChannel(
            lang=lang,
            source=self.campus.source_language,
            provider=self.translator,
            provider_overrides=self.languages[lang].provider_codes if lang in self.languages else None,
            publish=self._publish_translation,
            notice=self.publisher.notice,
            on_error=on_error,
            on_usage=on_usage,
            on_latency=on_latency,
            translate_partials=self.opts.translate_partials,
            partial_interval=self.opts.partial_interval,
        )

    async def _language_manager(self) -> None:
        """Start translation only for languages someone is watching right now."""
        while True:
            counts = self.viewer_counts()
            now = time.monotonic()
            for lang in self.languages:
                if lang == self.campus.source_language:
                    continue
                if counts.get(lang, 0) > 0:
                    self._channel_last_viewed[lang] = now
                    if lang not in self.channels:
                        ch = self._make_channel(lang)
                        self.channels[lang] = ch
                        ch.start()
                        # Give late joiners context: translate the last few sentences.
                        # No audio timestamp: catch-up segments must not skew latency metrics.
                        for seg in list(self.recent_finals):
                            ch.submit_final(SourceSegment(seg.seq, seg.text, seg.final_at, None))
                        log.info("translation channel started", extra={"fields": {"campus": self.campus.slug, "lang": lang}})
            for lang in list(self.channels):
                idle = now - self._channel_last_viewed.get(lang, 0)
                if lang not in self.languages or idle > self.opts.language_grace:
                    ch = self.channels.pop(lang)
                    await ch.stop()
                    log.info("translation channel stopped", extra={"fields": {"campus": self.campus.slug, "lang": lang}})
            self.state.languages = {lang: ch.state for lang, ch in self.channels.items()}
            await asyncio.sleep(1.0)

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        return {
            "occurrence": self.occ,
            "stt": self.state.stt,
            "stt_error": self.state.stt_error,
            "stt_error_since": self.state.stt_error_since,
            "stt_connected_since": self.state.stt_connected_since,
            "first_result_at": self.state.first_result_at,
            "last_caption_at": self.state.last_caption_at,
            "segments": self.state.segments,
            "translation": self.state.languages,
            "metrics": self.metrics.snapshot(),
        }

    def to_json(self) -> str:
        return json.dumps(self.status())
