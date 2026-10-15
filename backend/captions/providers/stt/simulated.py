"""Simulated STT for development and testing (no API key, no cost).

It is driven by the *actual* audio it receives: words are released in
proportion to seconds of audio streamed, so stopping the sender stops
captions, exactly like a real provider. Interim results grow word by word,
chunks of words become stable, and sentence ends produce endpoints.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from .base import STTEvent, STTProvider, STTSession

SCRIPT = (
    "Good morning, church, and welcome. We're so glad you're here with us today. "
    "If you're visiting for the first time, we would love to meet you after the service. "
    "Please open your Bibles with me to Psalm twenty-three. "
    "The Lord is my shepherd; I shall not want. "
    "He maketh me to lie down in green pastures: he leadeth me beside the still waters. "
    "He restoreth my soul: he leadeth me in the paths of righteousness for his name's sake. "
    "Yea, though I walk through the valley of the shadow of death, I will fear no evil, for thou art with me. "
    "This morning we are going to talk about what it means to be led. "
    "Sometimes the path in front of us is not the path we would have chosen. "
    "But the shepherd knows the way, and he never leaves the flock behind. "
    "Let's take a moment and pray together before we continue."
)


class SimulatedSession(STTSession):
    def __init__(self, sample_rate: int, words_per_minute: float, stable_every: int = 6) -> None:
        self.sample_rate = sample_rate
        self.words = SCRIPT.split()
        self.idx = 0
        self.seconds_per_word = 60.0 / max(30.0, words_per_minute)
        self.audio_seconds = 0.0
        self.released = 0.0
        self.stable_every = stable_every
        self.pending: list[str] = []
        self.queue: asyncio.Queue[STTEvent | None] = asyncio.Queue(maxsize=1000)
        self._closed = False

    def _next_word(self) -> str:
        w = self.words[self.idx % len(self.words)]
        self.idx += 1
        return w

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed:
            return
        self.audio_seconds += len(pcm) / 2 / self.sample_rate
        while self.audio_seconds - self.released >= self.seconds_per_word:
            self.released += self.seconds_per_word
            word = self._next_word()
            self.pending.append(word)
            sentence_end = word.endswith((".", "?", "!"))
            if sentence_end or len(self.pending) >= self.stable_every:
                await self.queue.put(STTEvent("stable", " ".join(self.pending), self.released))
                self.pending = []
                if sentence_end:
                    await self.queue.put(STTEvent("endpoint", audio_end=self.released))
            else:
                await self.queue.put(STTEvent("interim", " ".join(self.pending), self.released))

    async def keepalive(self) -> None:
        return None

    async def events(self) -> AsyncIterator[STTEvent]:
        while True:
            ev = await self.queue.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self.queue.put(None)


class SimulatedSTTProvider(STTProvider):
    name = "simulated"

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    async def open(self, *, sample_rate: int, language: str) -> STTSession:
        return SimulatedSession(sample_rate, float(self.settings.get("words_per_minute", 150)))
