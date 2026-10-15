"""Deepgram streaming STT (https://developers.deepgram.com/docs/live-streaming-audio)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from .base import STTError, STTEvent, STTProvider, STTSession

log = logging.getLogger(__name__)

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"


class DeepgramSession(STTSession):
    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self._closed = False

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self.ws.send(pcm)
        except ConnectionClosed as e:
            raise STTError(f"deepgram connection closed: {e}") from e

    async def keepalive(self) -> None:
        try:
            await self.ws.send(json.dumps({"type": "KeepAlive"}))
        except ConnectionClosed as e:
            raise STTError(f"deepgram connection closed: {e}") from e

    async def events(self) -> AsyncIterator[STTEvent]:
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                msg: dict[str, Any] = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "Results":
                    alts = (msg.get("channel") or {}).get("alternatives") or [{}]
                    text = (alts[0].get("transcript") or "").strip()
                    end = float(msg.get("start", 0.0)) + float(msg.get("duration", 0.0))
                    if msg.get("is_final"):
                        if text:
                            yield STTEvent("stable", text, end)
                        else:
                            yield STTEvent("interim", "", end)
                        if msg.get("speech_final"):
                            yield STTEvent("endpoint", audio_end=end)
                    else:
                        yield STTEvent("interim", text, end)
                elif mtype == "UtteranceEnd":
                    yield STTEvent("endpoint", audio_end=msg.get("last_word_end"))
                elif mtype == "Error" or msg.get("err_code"):
                    raise STTError(f"deepgram error: {msg}")
        except ConnectionClosed as e:
            if not self._closed:
                raise STTError(f"deepgram connection closed: code={e.code}") from e

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.ws.send(json.dumps({"type": "CloseStream"}))
            await asyncio.wait_for(self.ws.close(), timeout=3)
        except Exception:
            pass


class DeepgramProvider(STTProvider):
    name = "deepgram"

    def __init__(self, api_key: str, settings: dict[str, Any]) -> None:
        self.api_key = api_key
        self.settings = settings

    def configured(self) -> bool:
        return bool(self.api_key)

    def build_url(self, sample_rate: int, language: str) -> str:
        params: list[tuple[str, str]] = [
            ("model", str(self.settings.get("model", "nova-3"))),
            ("language", language),
            ("encoding", "linear16"),
            ("sample_rate", str(sample_rate)),
            ("channels", "1"),
            ("interim_results", "true"),
            ("punctuate", "true"),
            ("smart_format", "true"),
            ("endpointing", str(int(self.settings.get("endpointing_ms", 300)))),
            ("utterance_end_ms", "1000"),
            ("vad_events", "false"),
        ]
        # Keyterm prompting (Nova-3) helps with names, places and scripture books.
        for term in self.settings.get("keyterms") or []:
            term = str(term).strip()
            if term:
                params.append(("keyterm", term[:100]))
        return f"{DEEPGRAM_URL}?{urlencode(params)}"

    async def open(self, *, sample_rate: int, language: str) -> STTSession:
        if not self.api_key:
            raise STTError("Deepgram API key is not configured", retryable=False)
        try:
            ws = await asyncio.wait_for(
                connect(
                    self.build_url(sample_rate, language),
                    additional_headers={"Authorization": f"Token {self.api_key}"},
                    open_timeout=10,
                    ping_interval=10,
                    ping_timeout=10,
                    max_size=2**20,
                ),
                timeout=12,
            )
        except InvalidStatus as e:
            status = e.response.status_code
            raise STTError(f"deepgram rejected connection: HTTP {status}", retryable=status not in (400, 401, 402, 403)) from e
        except (OSError, asyncio.TimeoutError) as e:
            raise STTError(f"deepgram connect failed: {e!r}") from e
        return DeepgramSession(ws)
