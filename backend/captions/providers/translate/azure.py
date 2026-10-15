"""Azure AI Translator v3 (https://learn.microsoft.com/azure/ai-services/translator/)."""

from __future__ import annotations

from typing import Any

import httpx

from .base import TranslationError, TranslationProvider

# Internal codes Azure Translator supports as targets. Extend as languages are added.
AZURE_SUPPORTED = frozenset(
    {
        "en", "es", "pt", "fr", "ht", "zh", "ko", "ar", "ru", "uk", "vi", "hi",
        "de", "it", "ja", "pl", "tl", "fa", "sw", "am", "so", "ne", "ur", "bn",
        "pa", "ta", "te", "th", "tr", "he", "el", "ro", "nl", "id", "ms",
    }
)


class AzureTranslator(TranslationProvider):
    name = "azure"
    supported = AZURE_SUPPORTED

    def __init__(self, api_key: str, settings: dict[str, Any]) -> None:
        super().__init__()
        self.api_key = api_key
        self.region = str(settings.get("region") or "")
        self.endpoint = str(settings.get("endpoint") or "https://api.cognitive.microsofttranslator.com").rstrip("/")

    def configured(self) -> bool:
        return bool(self.api_key)

    async def translate(self, texts, source, target, target_overrides=None):
        if not self.api_key:
            raise TranslationError("Azure Translator key is not configured", retryable=False)
        headers = {"Ocp-Apim-Subscription-Key": self.api_key, "Content-Type": "application/json"}
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region
        params = {
            "api-version": "3.0",
            "from": self.code_for(source),
            "to": self.code_for(target, target_overrides),
            "textType": "plain",
        }
        try:
            resp = await self.client.post(
                f"{self.endpoint}/translate", params=params, headers=headers, json=[{"Text": t} for t in texts]
            )
        except httpx.HTTPError as e:
            raise TranslationError(f"azure request failed: {e!r}") from e
        if resp.status_code != 200:
            retryable = resp.status_code in (408, 429) or resp.status_code >= 500
            raise TranslationError(f"azure HTTP {resp.status_code}: {resp.text[:200]}", retryable=retryable)
        data = resp.json()
        try:
            return [item["translations"][0]["text"] for item in data]
        except (KeyError, IndexError, TypeError) as e:
            raise TranslationError(f"unexpected azure response: {str(data)[:200]}") from e
