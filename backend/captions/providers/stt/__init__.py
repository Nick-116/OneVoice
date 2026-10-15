from __future__ import annotations

from ...config_store import ProviderSelection
from .base import STTError, STTEvent, STTProvider, STTSession


def build_stt_provider(sel: ProviderSelection) -> STTProvider:
    if sel.provider == "deepgram":
        from .deepgram import DeepgramProvider

        return DeepgramProvider(sel.api_key or "", sel.settings)
    if sel.provider == "assemblyai":
        from .assemblyai import AssemblyAIProvider

        return AssemblyAIProvider(sel.api_key or "", sel.settings)
    if sel.provider == "simulated":
        from .simulated import SimulatedSTTProvider

        return SimulatedSTTProvider(sel.settings)
    raise ValueError(f"unknown STT provider {sel.provider!r}")


__all__ = ["STTError", "STTEvent", "STTProvider", "STTSession", "build_stt_provider"]
