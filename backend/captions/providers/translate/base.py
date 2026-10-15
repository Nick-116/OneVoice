"""Provider-independent translation interface."""

from __future__ import annotations

import abc

import httpx

from ...languages import provider_code


class TranslationError(Exception):
    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class TranslationProvider(abc.ABC):
    name: str = "base"
    # Internal language codes this provider can translate *into*.
    supported: frozenset[str] = frozenset()

    def __init__(self) -> None:
        # One pooled client per provider: keeps TLS connections warm between
        # caption segments, which saves ~100 ms per request.
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(6.0, connect=4.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def configured(self) -> bool:
        return True

    def supports(self, code: str) -> bool:
        return code in self.supported

    def code_for(self, code: str, overrides: dict[str, str] | None = None) -> str:
        return provider_code(code, self.name, overrides)

    @abc.abstractmethod
    async def translate(
        self, texts: list[str], source: str, target: str, target_overrides: dict[str, str] | None = None
    ) -> list[str]:
        """Translate ``texts`` from ``source`` into ``target`` (internal codes)."""
