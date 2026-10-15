"""In-process caption fan-out for the public service.

One Redis pattern subscription (``cap:*`` and ``status:*``) feeds every
connected viewer in this process. Each viewer has a small bounded queue; a
viewer that cannot keep up (frozen phone, dead connection) is disconnected
instead of slowing anyone else down. Viewer counts per campus/language are
written to Redis so the worker knows which languages to translate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections import defaultdict
from dataclasses import dataclass, field

import redis.asyncio as aioredis

from .. import rkeys

log = logging.getLogger(__name__)

QUEUE_SIZE = 200


@dataclass(eq=False)
class Subscriber:
    slug: str
    lang: str
    ip: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE))
    closed: bool = False

    def offer(self, item: tuple[str, str]) -> bool:
        if self.closed:
            return False
        try:
            self.queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            self.close()
            return False

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            # Wake the writer so it can exit; drop one item if needed to make room.
            try:
                self.queue.put_nowait(("close", ""))
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()
                    self.queue.put_nowait(("close", ""))
                except Exception:
                    pass


class CaptionHub:
    def __init__(self, r: aioredis.Redis) -> None:
        self.r = r
        self.subs: dict[tuple[str, str], set[Subscriber]] = defaultdict(set)
        self.by_ip: dict[str, int] = defaultdict(int)
        self.instance = f"{socket.gethostname()}-{os.getpid()}"
        self._tasks: list[asyncio.Task] = []
        self.redis_ok = False

    @property
    def total(self) -> int:
        return sum(len(s) for s in self.subs.values())

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._reader(), name="hub-reader"),
            asyncio.create_task(self._report_viewers(), name="hub-viewers"),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for subs in self.subs.values():
            for s in subs:
                s.close()
        try:
            await self.r.delete(rkeys.viewers_key(self.instance))
        except Exception:
            pass

    def add(self, sub: Subscriber) -> None:
        self.subs[(sub.slug, sub.lang)].add(sub)
        self.by_ip[sub.ip] += 1

    def remove(self, sub: Subscriber) -> None:
        group = self.subs.get((sub.slug, sub.lang))
        if group and sub in group:
            group.discard(sub)
            if not group:
                self.subs.pop((sub.slug, sub.lang), None)
            self.by_ip[sub.ip] -= 1
            if self.by_ip[sub.ip] <= 0:
                self.by_ip.pop(sub.ip, None)

    def dispatch(self, channel: str, data: str) -> None:
        kind, _, rest = channel.partition(":")
        if kind == "cap":
            slug, _, lang = rest.partition(":")
            for sub in list(self.subs.get((slug, lang), ())):
                sub.offer(("caption", data))
        elif kind == "status":
            slug = rest
            try:
                live = json.loads(data).get("phase") == "live"
            except ValueError:
                return
            for (s_slug, _lang), group in list(self.subs.items()):
                if s_slug != slug:
                    continue
                for sub in list(group):
                    sub.offer(("status", data))
                    if not live:
                        # Backend-enforced end of service: close every caption stream.
                        sub.close()

    async def _reader(self) -> None:
        backoff = 0.5
        while True:
            pubsub = self.r.pubsub(ignore_subscribe_messages=True)
            try:
                await pubsub.psubscribe("cap:*", "status:*")
                self.redis_ok = True
                backoff = 0.5
                while True:
                    msg = await pubsub.get_message(timeout=5.0)
                    if msg is None:
                        continue
                    if msg.get("type") == "pmessage":
                        self.dispatch(msg["channel"], msg["data"])
            except asyncio.CancelledError:
                await pubsub.aclose()
                raise
            except Exception as e:
                self.redis_ok = False
                log.warning("redis subscription lost; reconnecting", extra={"fields": {"error": repr(e)}})
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

    def counts(self) -> dict[str, int]:
        return {f"{slug}|{lang}": len(group) for (slug, lang), group in self.subs.items() if group}

    async def _report_viewers(self) -> None:
        key = rkeys.viewers_key(self.instance)
        while True:
            try:
                counts = self.counts()
                async with self.r.pipeline(transaction=False) as p:
                    p.delete(key)
                    if counts:
                        p.hset(key, mapping=counts)
                        p.expire(key, 15)
                    await p.execute()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("could not report viewer counts")
            await asyncio.sleep(2.0)
