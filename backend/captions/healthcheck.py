"""Docker health checks: ``python -m captions.healthcheck http 8080`` or ``... worker``."""

from __future__ import annotations

import asyncio
import sys
import time
import urllib.request


def http(port: str) -> int:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=4) as r:
            return 0 if r.status == 200 else 1
    except Exception:
        return 1


def worker() -> int:
    from . import rkeys
    from .redisio import make_redis

    async def check() -> int:
        r = make_redis()
        try:
            hb = await r.get(rkeys.WORKER_HEARTBEAT)
            return 0 if hb and time.time() - float(hb) < 15 else 1
        finally:
            await r.aclose()

    try:
        return asyncio.run(check())
    except Exception:
        return 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "http"
    sys.exit(worker() if mode == "worker" else http(sys.argv[2] if len(sys.argv) > 2 else "8080"))
