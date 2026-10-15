"""Publishes caption messages to Redis for the public fan-out service."""

from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as aioredis

from .. import rkeys

BUFFER_LEN = 50
BUFFER_TTL = 6 * 3600


class CaptionPublisher:
    def __init__(self, r: aioredis.Redis, slug: str, occurrence_key: str) -> None:
        self.r = r
        self.slug = slug
        self.occ = occurrence_key

    def message(self, lang: str, seq: int, text: str, final: bool, latency_ms: float | None = None) -> dict[str, Any]:
        return {
            "t": "caption",
            "occ": self.occ,
            "id": seq,
            "final": final,
            "lang": lang,
            "text": text,
            "ts": round(time.time(), 3),
            "lat": round(latency_ms) if latency_ms is not None else None,
        }

    async def caption(self, lang: str, seq: int, text: str, final: bool, latency_ms: float | None = None) -> None:
        payload = json.dumps(self.message(lang, seq, text, final, latency_ms), ensure_ascii=False)
        async with self.r.pipeline(transaction=False) as p:
            p.publish(rkeys.caption_channel(self.slug, lang), payload)
            if final:
                key = rkeys.caption_buffer(self.slug, lang)
                p.rpush(key, payload)
                p.ltrim(key, -BUFFER_LEN, -1)
                p.expire(key, BUFFER_TTL)
            await p.execute()

    async def notice(self, lang: str, code: str) -> None:
        payload = json.dumps({"t": "notice", "occ": self.occ, "lang": lang, "code": code, "ts": time.time()})
        await self.r.publish(rkeys.caption_channel(self.slug, lang), payload)

    async def clear_buffers(self, langs: list[str]) -> None:
        if langs:
            await self.r.delete(*[rkeys.caption_buffer(self.slug, lang) for lang in langs])
