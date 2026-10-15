"""AssemblyAI Universal-Streaming v3 (https://www.assemblyai.com/docs/speech-to-text/universal-streaming)."""

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

AAI_URL = "wss://streaming.assemblyai.com/v3/ws"


class AssemblyAISession(STTSession):
    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self._closed = False
        self._silence = b"\x00\x00" * 1600  # 100 ms @ 16 kHz

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self.ws.send(pcm)
        except ConnectionClosed as e:
            raise STTError(f"assemblyai connection closed: {e}") from e

    async def keepalive(self) -> None:
        # v3 has no keepalive message; a short burst of silence keeps the session alive.
        await self.send_audio(self._silence)

    async def events(self) -> AsyncIterator[STTEvent]:
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                msg: dict[str, Any] = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "Turn":
                    text = (msg.get("transcript") or "").strip()
                    words = msg.get("words") or []
                    end = (words[-1].get("end") / 1000.0) if words and words[-1].get("end") else None
                    if msg.get("end_of_turn"):
                        # With format_turns=true AssemblyAI sends the formatted turn last.
                        if msg.get("turn_is_formatted"):
                            if text:
                                yield STTEvent("stable", text, end)
                            yield STTEvent("endpoint", audio_end=end)
                    else:
                        yield STTEvent("interim", text, end)
                elif mtype == "Termination":
                    return
                elif mtype == "Error" or "error" in msg:
                    raise STTError(f"assemblyai error: {msg}")
        except ConnectionClosed as e:
            if not self._closed:
                raise STTError(f"assemblyai connection closed: code={e.code} {e.reason}", retryable=e.code not in (1008, 4001, 4002, 4003)) from e

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.ws.send(json.dumps({"type": "Terminate"}))
            await asyncio.wait_for(self.ws.close(), timeout=3)
        except Exception:
            pass


class AssemblyAIProvider(STTProvider):
    name = "assemblyai"

    def __init__(self, api_key: str, settings: dict[str, Any]) -> None:
        self.api_key = api_key
        self.settings = settings

    def configured(self) -> bool:
        return bool(self.api_key)

    async def open(self, *, sample_rate: int, language: str) -> STTSession:
        if not self.api_key:
            raise STTError("AssemblyAI API key is not configured", retryable=False)
        if not language.startswith("en"):
            raise STTError("AssemblyAI Universal-Streaming English model only supports English source audio", retryable=False)
        params: dict[str, str] = {
            "sample_rate": str(sample_rate),
            "encoding": "pcm_s16le",
            "format_turns": "true",
        }
        terms = [str(t)[:50] for t in (self.settings.get("keyterms") or []) if str(t).strip()]
        if terms:
            params["keyterms_prompt"] = json.dumps(terms[:100])
        try:
            ws = await asyncio.wait_for(
                connect(
                    f"{AAI_URL}?{urlencode(params)}",
                    additional_headers={"Authorization": self.api_key},
                    open_timeout=10,
                    ping_interval=10,
                    ping_timeout=10,
                ),
                timeout=12,
            )
        except InvalidStatus as e:
            status = e.response.status_code
            raise STTError(f"assemblyai rejected connection: HTTP {status}", retryable=status not in (400, 401, 403)) from e
        except (OSError, asyncio.TimeoutError) as e:
            raise STTError(f"assemblyai connect failed: {e!r}") from e
        return AssemblyAISession(ws)
