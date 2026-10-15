"""Entry point: ``python -m captions.worker``."""

from __future__ import annotations

import asyncio
import signal

from ..config import get_settings
from ..logging_setup import setup_logging
from ..redisio import make_redis
from .supervisor import Supervisor


async def main() -> None:
    s = get_settings()
    setup_logging("worker", s.log_level)
    sup = Supervisor(make_redis(decode=True), make_redis(decode=False))
    task = asyncio.create_task(sup.run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
