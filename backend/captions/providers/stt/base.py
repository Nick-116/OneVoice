"""Provider-independent streaming speech-to-text interface.

Providers translate their wire protocol into three event kinds:

* ``interim``  - unstable hypothesis for the not-yet-finalized tail of speech.
                 Replaces the previous interim.
* ``stable``   - text the provider will not revise any more. Appended.
* ``endpoint`` - the speaker paused; good place to end a caption segment.

The pipeline's Segmenter turns these into partial/final caption lines, so
segmentation behaviour is identical regardless of provider.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import AsyncIterator


class STTError(Exception):
    """Provider failure. ``retryable`` False means configuration is wrong (e.g. bad key)."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class STTEvent:
    kind: str  # interim | stable | endpoint
    text: str = ""
    # Seconds since the session's first audio sample, when the provider reports it.
    audio_end: float | None = None


class STTSession(abc.ABC):
    @abc.abstractmethod
    async def send_audio(self, pcm: bytes) -> None:
        """Send 16-bit little-endian mono PCM."""

    @abc.abstractmethod
    async def keepalive(self) -> None:
        """Called periodically while audio is briefly paused."""

    @abc.abstractmethod
    def events(self) -> AsyncIterator[STTEvent]:
        """Yield events until the session closes. Raises STTError on failure."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Flush and close; safe to call more than once."""


class STTProvider(abc.ABC):
    name: str = "base"
    # True when each interim covers the whole not-yet-stable stretch in the same wording the
    # stable text will use, so the segmenter may take agreed words early (see segmenter.py).
    early_commit: bool = False

    @abc.abstractmethod
    async def open(self, *, sample_rate: int, language: str) -> STTSession: ...

    def configured(self) -> bool:
        return True
