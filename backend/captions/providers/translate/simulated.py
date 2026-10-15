"""Simulated translator for development/testing. Never used unless selected."""

from __future__ import annotations

import asyncio
from typing import Any

from .base import TranslationError, TranslationProvider
from .azure import AZURE_SUPPORTED


class SimulatedTranslator(TranslationProvider):
    name = "simulated"
    supported = AZURE_SUPPORTED

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__()
        self.fail_languages = set(settings.get("fail_languages") or [])
        self.delay = float(settings.get("delay_ms", 150)) / 1000.0

    async def translate(self, texts, source, target, target_overrides=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        if target in self.fail_languages:
            raise TranslationError(f"simulated failure for {target}")
        return [f"[{target}] {t}" for t in texts]
