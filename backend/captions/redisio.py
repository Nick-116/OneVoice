from __future__ import annotations

import json
import logging
import time

import redis.asyncio as aioredis

from .config import get_settings
from . import rkeys

log = logging.getLogger(__name__)


def make_redis(decode: bool = True) -> aioredis.Redis:
    s = get_settings()
    return aioredis.Redis(
        host=s.redis_host,
        port=s.redis_port,
        username=s.redis_user if s.redis_password else None,
        password=s.redis_password,
        decode_responses=decode,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=15,
        retry_on_timeout=True,
    )


async def record_error(r: aioredis.Redis, component: str, message: str, campus_id: int | None = None) -> None:
    """Keep a short rolling list of recent errors for the admin dashboard (and log it for `docker logs`)."""
    log.warning("%s error%s: %s", component, f" (campus {campus_id})" if campus_id is not None else "", message[:500])
    entry = json.dumps({"at": time.time(), "component": component, "campus_id": campus_id, "message": message[:500]})
    try:
        async with r.pipeline(transaction=False) as p:
            p.lpush(rkeys.ERRORS_LIST, entry)
            p.ltrim(rkeys.ERRORS_LIST, 0, 199)
            await p.execute()
    except Exception:  # never let error reporting take a component down
        log.exception("could not record error")
