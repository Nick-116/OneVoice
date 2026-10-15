from __future__ import annotations

from ...config_store import ProviderSelection
from .base import TranslationError, TranslationProvider


def build_translation_provider(sel: ProviderSelection) -> TranslationProvider:
    if sel.provider == "azure":
        from .azure import AzureTranslator

        return AzureTranslator(sel.api_key or "", sel.settings)
    if sel.provider == "google":
        from .google import GoogleTranslator

        return GoogleTranslator(sel.api_key or "", sel.settings)
    if sel.provider == "simulated":
        from .simulated import SimulatedTranslator

        return SimulatedTranslator(sel.settings)
    raise ValueError(f"unknown translation provider {sel.provider!r}")


__all__ = ["TranslationError", "TranslationProvider", "build_translation_provider"]
