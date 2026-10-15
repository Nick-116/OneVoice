"""Google Cloud Translation, Basic edition v2 (API key auth)."""

from __future__ import annotations

import html
from typing import Any

import httpx

from .base import TranslationError, TranslationProvider

GOOGLE_SUPPORTED = frozenset(
    {
        "en", "es", "pt", "fr", "ht", "zh", "ko", "ar", "ru", "uk", "vi", "hi",
        "de", "it", "ja", "pl", "tl", "fa", "sw", "am", "so", "ne", "ur", "bn",
        "pa", "ta", "te", "th", "tr", "he", "el", "ro", "nl", "id", "ms",
    }
)


class GoogleTranslator(TranslationProvider):
    name = "google"
    supported = GOOGLE_SUPPORTED
    url = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, api_key: str, settings: dict[str, Any]) -> None:
        super().__init__()
        self.api_key = api_key

    def configured(self) -> bool:
        return bool(self.api_key)

    async def translate(self, texts, source, target, target_overrides=None):
        if not self.api_key:
            raise TranslationError("Google Translate API key is not configured", retryable=False)
        body = {
            "q": texts,
            "source": self.code_for(source),
            "target": self.code_for(target, target_overrides),
            "format": "text",
        }
        try:
            # Key goes in a header, not the URL, so it never lands in proxy logs.
            resp = await self.client.post(self.url, json=body, headers={"X-goog-api-key": self.api_key})
        except httpx.HTTPError as e:
            raise TranslationError(f"google request failed: {e!r}") from e
        if resp.status_code != 200:
            retryable = resp.status_code in (408, 429) or resp.status_code >= 500
            raise TranslationError(f"google HTTP {resp.status_code}: {resp.text[:200]}", retryable=retryable)
        try:
            return [html.unescape(t["translatedText"]) for t in resp.json()["data"]["translations"]]
        except (KeyError, TypeError) as e:
            raise TranslationError("unexpected google response") from e
