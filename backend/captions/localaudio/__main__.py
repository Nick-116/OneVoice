"""Entry point: ``python -m captions.localaudio`` (the optional local-audio container)."""

from __future__ import annotations

import asyncio
import os
import signal

from ..config import get_settings
from ..logging_setup import setup_logging
from ..redisio import make_redis
from .service import CompositeBackend, LocalAudioService, SoundDeviceBackend, TestToneBackend


async def main() -> None:
    setup_logging("local-audio", get_settings().log_level)
    backends = [SoundDeviceBackend()]
    if os.environ.get("LOCAL_AUDIO_TEST_TONE", "").lower() in ("1", "true", "yes"):
        backends.append(TestToneBackend())
    service = LocalAudioService(make_redis(), CompositeBackend(*backends))
    task = asyncio.create_task(service.run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        await service.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
