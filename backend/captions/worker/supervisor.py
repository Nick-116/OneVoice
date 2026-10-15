"""Worker supervisor: enforces the schedule and publishes public status.

Every second it:
  * evaluates each campus's schedule (DST-aware) to decide live / upcoming / ended / idle,
  * starts or stops that campus's caption pipeline (nothing runs outside a window),
  * sets the ``campus:live`` flag the ingest service checks before forwarding audio,
  * derives the caption state (live / waiting / disconnected / unavailable),
  * publishes a public status snapshot that the public site reads.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import logging
import time
from collections import defaultdict
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import text

from .. import db, rkeys
from ..branding import build_palette
from ..config_store import CampusConfig, ConfigSnapshot, LanguageConfig, load_snapshot
from ..providers.stt import STTProvider, build_stt_provider
from ..providers.translate import TranslationProvider, build_translation_provider
from ..redisio import record_error
from ..schedule import PHASE_LIVE, CampusSchedule, Occurrence, compute_campus_schedule, occurrences_between
from .metrics import UsageMeter
from .pipeline import CampusPipeline, PipelineOptions

log = logging.getLogger(__name__)
UTC = dt.timezone.utc

CONFIG_REFRESH_SECONDS = 30
STT_UNAVAILABLE_AFTER = 8.0  # seconds of continuous STT failure before telling viewers


def iso(d: dt.datetime | None) -> str | None:
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z") if d else None


class Supervisor:
    def __init__(self, r_text: aioredis.Redis, r_bin: aioredis.Redis) -> None:
        self.r = r_text
        self.rb = r_bin
        self.snapshot: ConfigSnapshot | None = None
        self.snapshot_at = 0.0
        self.config_dirty = True
        self.pipelines: dict[int, CampusPipeline] = {}
        self.stt: STTProvider | None = None
        self.translator: TranslationProvider | None = None
        self._provider_fingerprint: str | None = None
        self.usage = UsageMeter()
        self.viewers: dict[str, dict[str, int]] = defaultdict(dict)  # slug -> lang -> count
        self._last_public: dict[str, str] = {}
        self._last_public_at: dict[str, float] = {}
        self._was_live: dict[int, bool] = {}
        self.logo_sha: str | None = None

    # ------------------------------------------------------------------ config
    async def reload_config(self) -> None:
        try:
            async with db.sessionmaker()() as s:
                snap = await load_snapshot(s)
        except Exception as e:
            log.exception("config load failed")
            await record_error(self.r, "worker", f"config load failed: {e!r}")
            return
        self.snapshot = snap
        self.snapshot_at = time.monotonic()
        self.config_dirty = False
        await self.sync_logo()
        fp = json.dumps(
            [snap.stt.provider, snap.stt.settings, snap.stt.api_key, snap.translation.provider,
             snap.translation.settings, snap.translation.api_key, snap.general],
            sort_keys=True, default=str,
        )
        if fp != self._provider_fingerprint:
            if self._provider_fingerprint is not None:
                log.info("provider configuration changed; restarting pipelines")
                await self.stop_all()
            if self.translator:
                await self.translator.aclose()
            self.stt = build_stt_provider(snap.stt)
            self.translator = build_translation_provider(snap.translation)
            self._provider_fingerprint = fp

    async def sync_logo(self) -> None:
        """Copy the uploaded logo to Redis for the public service (which has no DB access)."""
        try:
            async with db.sessionmaker()() as s:
                sha = (await s.execute(text("SELECT sha256 FROM branding_assets WHERE key = 'logo'"))).scalar_one_or_none()
                if sha is None:
                    await self.r.delete(rkeys.PUBLIC_LOGO)
                elif sha != self.logo_sha or not await self.r.exists(rkeys.PUBLIC_LOGO):
                    content = (await s.execute(text("SELECT content FROM branding_assets WHERE key = 'logo'"))).scalar_one()
                    await self.r.set(rkeys.PUBLIC_LOGO, base64.b64encode(content).decode(), ex=3600)
                else:
                    await self.r.expire(rkeys.PUBLIC_LOGO, 3600)
            self.logo_sha = sha
        except Exception as e:
            log.exception("logo sync failed")
            await record_error(self.r, "worker", f"logo sync failed: {e!r}")

    async def listen_config_changes(self) -> None:
        while True:
            try:
                pubsub = self.r.pubsub()
                await pubsub.subscribe(rkeys.CONFIG_CHANGED_CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") == "message":
                        self.config_dirty = True
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("config listener failed; retrying")
                await asyncio.sleep(2)

    # ------------------------------------------------------------------ viewers
    async def refresh_viewers(self) -> None:
        totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        async for key in self.r.scan_iter(match=rkeys.VIEWERS_PATTERN, count=100):
            for field, value in (await self.r.hgetall(key)).items():
                slug, _, lang = field.partition("|")
                totals[slug][lang] += int(value)
        self.viewers = defaultdict(dict, {k: dict(v) for k, v in totals.items()})

    # ------------------------------------------------------------------ helpers
    def effective_languages(self, campus: CampusConfig, occ: Occurrence | None) -> dict[str, LanguageConfig]:
        assert self.snapshot and self.translator
        wanted = list(occ.languages) if occ and occ.languages else list(campus.languages)
        if campus.source_language not in wanted:
            wanted.insert(0, campus.source_language)
        out: dict[str, LanguageConfig] = {}
        for code in wanted:
            lang = self.snapshot.languages.get(code)
            if not lang or not lang.enabled:
                continue
            if code != campus.source_language and not self.translator.supports(code):
                continue  # only offer languages the provider can actually produce
            out[code] = lang
        return dict(sorted(out.items(), key=lambda kv: (kv[1].sort_order, kv[0])))

    async def caption_state(self, campus: CampusConfig, pipeline: CampusPipeline | None) -> str:
        assert self.snapshot
        g = self.snapshot.general
        st = await self.r.hgetall(rkeys.audio_status(campus.id))
        now = time.time()
        audio_ok = (
            st.get("connected") == "1"
            and now - float(st.get("last_frame_at") or 0) < float(g["audio_timeout_seconds"])
            # Pure digital silence usually means a broken Dante route, not a quiet room.
            and now - float(st.get("last_signal_at") or 0) < float(g["digital_silence_seconds"])
        )
        if not audio_ok:
            return "disconnected"
        if pipeline is None:
            return "waiting"
        ps = pipeline.state
        if ps.stt == "error" and ps.stt_error_since and now - ps.stt_error_since > STT_UNAVAILABLE_AFTER:
            return "unavailable"
        if ps.stt == "connected" and ps.first_result_at:
            return "live"
        return "waiting"

    def schedule_for(self, campus: CampusConfig, now: dt.datetime) -> tuple[CampusSchedule, list[Occurrence]]:
        assert self.snapshot
        g = self.snapshot.general
        grace = dt.timedelta(minutes=int(g["ended_grace_minutes"]))
        occs = occurrences_between(
            [s for s in self.snapshot.recurring if s.campus_id == campus.id],
            [e for e in self.snapshot.events if e.campus_id == campus.id],
            self.snapshot.exceptions,
            now - grace - dt.timedelta(hours=12),
            now + dt.timedelta(days=int(g["lookahead_days"])),
        )
        return compute_campus_schedule(occs, now, ended_grace=grace), occs

    # ------------------------------------------------------------------ main tick
    async def tick(self) -> None:
        if self.config_dirty or time.monotonic() - self.snapshot_at > CONFIG_REFRESH_SECONDS:
            await self.reload_config()
        if not self.snapshot or not self.stt or not self.translator:
            return
        await self.refresh_viewers()
        now = dt.datetime.now(UTC)
        g = self.snapshot.general
        public_campuses = []
        seen: set[int] = set()

        for campus in self.snapshot.campuses:
            seen.add(campus.id)
            if not campus.enabled:
                await self.stop_pipeline(campus.id)
                await self.r.delete(rkeys.public_status(campus.slug), rkeys.campus_live_flag(campus.id))
                continue
            public_campuses.append({"slug": campus.slug, "name": campus.name})
            sched, _ = self.schedule_for(campus, now)
            current = sched.current if sched.phase == PHASE_LIVE else None
            langs = self.effective_languages(campus, current or sched.next)

            pipeline = self.pipelines.get(campus.id)
            if current is not None:
                await self.r.set(rkeys.campus_live_flag(campus.id), current.key, ex=5)
                if pipeline is None or pipeline.occ != current.key or not pipeline.running:
                    await self.stop_pipeline(campus.id)
                    pipeline = self.start_pipeline(campus, current, langs)
                else:
                    pipeline.languages = langs
            else:
                await self.stop_pipeline(campus.id)
                pipeline = None
                await self.r.delete(rkeys.campus_live_flag(campus.id))

            cap_state = await self.caption_state(campus, pipeline) if current else None
            status = self.public_status(campus, sched, langs, cap_state)
            await self.publish_status(campus, status, force=self._was_live.get(campus.id) != bool(current))
            self._was_live[campus.id] = bool(current)

            internal = {
                "phase": sched.phase,
                "captions": cap_state,
                "service": status["service"],
                "next": status["next"],
                "viewers": self.viewers.get(campus.slug, {}),
                "pipeline": pipeline.status() if pipeline else None,
                "stt_provider": self.stt.name,
                "stt_configured": self.stt.configured(),
                "translation_provider": self.translator.name,
                "translation_configured": self.translator.configured(),
                "updated": time.time(),
            }
            await self.r.set(rkeys.campus_internal_status(campus.id), json.dumps(internal), ex=30)

        for cid in list(self.pipelines):
            if cid not in seen:
                await self.stop_pipeline(cid)

        await self.r.set(rkeys.PUBLIC_CAMPUSES, json.dumps(public_campuses), ex=120)
        branding = {
            "church_name": g["church_name"],
            "theme": build_palette(str(g.get("accent_color") or "")),
            "logo_version": self.logo_sha[:16] if self.logo_sha else None,
        }
        await self.r.set(rkeys.PUBLIC_BRANDING, json.dumps(branding), ex=120)
        await self.r.set(rkeys.WORKER_HEARTBEAT, str(time.time()), ex=30)

    def public_status(
        self, campus: CampusConfig, sched: CampusSchedule, langs: dict[str, LanguageConfig], cap_state: str | None
    ) -> dict[str, Any]:
        cur, nxt = sched.current, sched.next
        return {
            "slug": campus.slug,
            "name": campus.name,
            "timezone": campus.timezone,
            "source_language": campus.source_language,
            "default_language": campus.default_language if campus.default_language in langs else campus.source_language,
            "phase": sched.phase,
            "captions": cap_state,
            "service": {"key": cur.key, "name": cur.name, "start": iso(cur.start), "end": iso(cur.end)} if cur else None,
            "next": {"name": nxt.name, "start": iso(nxt.start), "window_start": iso(nxt.window_start)} if nxt else None,
            "languages": [{"code": lang.code, "name": lang.native_name, "rtl": lang.rtl} for lang in langs.values()],
        }

    async def publish_status(self, campus: CampusConfig, status: dict[str, Any], force: bool = False) -> None:
        body = json.dumps(status, sort_keys=True, ensure_ascii=False)
        changed = body != self._last_public.get(campus.slug)
        stale = time.monotonic() - self._last_public_at.get(campus.slug, 0) > 5
        if not (changed or stale or force):
            return
        full = dict(status, server_time=time.time())
        payload = json.dumps(full, ensure_ascii=False)
        async with self.r.pipeline(transaction=False) as p:
            p.set(rkeys.public_status(campus.slug), payload, ex=30)
            if changed or force:
                p.publish(rkeys.status_channel(campus.slug), payload)
            await p.execute()
        self._last_public[campus.slug] = body
        self._last_public_at[campus.slug] = time.monotonic()

    # ------------------------------------------------------------------ pipelines
    def start_pipeline(self, campus: CampusConfig, occ: Occurrence, langs: dict[str, LanguageConfig]) -> CampusPipeline:
        assert self.snapshot and self.stt and self.translator
        g = self.snapshot.general
        opts = PipelineOptions(
            translate_partials=bool(g["translate_partials"]),
            partial_interval=int(g["partial_min_interval_ms"]) / 1000.0,
            language_grace=float(g["language_grace_seconds"]),
            stt_price_per_minute=float(self.snapshot.stt.settings.get("price_per_minute", 0) or 0),
            translation_price_per_million=float(self.snapshot.translation.settings.get("price_per_million_chars", 0) or 0),
        )
        slug = campus.slug
        pipeline = CampusPipeline(
            campus=campus,
            occurrence_key=occ.key,
            languages=langs,
            r_text=self.r,
            r_bin=self.rb,
            stt=self.stt,
            translator=self.translator,
            options=opts,
            usage=self.usage,
            viewer_counts=lambda: self.viewers.get(slug, {}),
        )
        pipeline.start()
        self.pipelines[campus.id] = pipeline
        log.info("service window opened", extra={"fields": {"campus": slug, "occurrence": occ.key}})
        return pipeline

    async def stop_pipeline(self, campus_id: int) -> None:
        pipeline = self.pipelines.pop(campus_id, None)
        if pipeline:
            await pipeline.stop()
            log.info("service window closed", extra={"fields": {"campus": pipeline.campus.slug, "occurrence": pipeline.occ}})

    async def stop_all(self) -> None:
        for cid in list(self.pipelines):
            await self.stop_pipeline(cid)

    # ------------------------------------------------------------------ housekeeping
    async def purge_transcripts(self) -> None:
        if not self.snapshot:
            return
        days = int(self.snapshot.general["transcript_retention_days"])
        try:
            async with db.sessionmaker()() as s:
                await s.execute(
                    text("DELETE FROM transcripts WHERE created_at < now() - make_interval(days => :d)"), {"d": days}
                )
                await s.commit()
        except Exception as e:
            await record_error(self.r, "worker", f"transcript purge failed: {e!r}")

    async def run(self) -> None:
        listener = asyncio.create_task(self.listen_config_changes())
        last_usage_flush = time.monotonic()
        last_purge = 0.0
        try:
            while True:
                started = time.monotonic()
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.exception("supervisor tick failed")
                    await record_error(self.r, "worker", f"tick failed: {e!r}")
                if time.monotonic() - last_usage_flush > 60:
                    await self.usage.flush()
                    last_usage_flush = time.monotonic()
                if time.monotonic() - last_purge > 6 * 3600:
                    await self.purge_transcripts()
                    last_purge = time.monotonic()
                await asyncio.sleep(max(0.1, 1.0 - (time.monotonic() - started)))
        finally:
            listener.cancel()
            await self.stop_all()
            await self.usage.flush()
