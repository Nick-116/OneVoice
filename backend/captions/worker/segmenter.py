"""Turns provider STT events into stable caption lines.

Strategy for low flicker without showing unstable text as final:

* Everything the provider has marked stable is accumulated in ``committed``.
* Complete sentences are cut off ``committed`` and emitted as **final**
  segments; only finals are translated (unless partial translation is on).
* The remaining stable text plus the provider's current interim hypothesis is
  emitted as a single **partial** line with the *next* sequence number. When
  the final for that number arrives, clients replace the partial in place.
* A pause (endpoint) flushes the remaining stable text as a final even
  without punctuation.
* Long sentences don't wait for their period: once enough stable text has
  built up, it is cut at the last clause break (comma, semicolon, colon, dash)
  so translation can start mid-sentence. Same characters, so no extra cost.
* A run-on with no clause break is split at a word boundary.
* Early commit: providers like Deepgram only mark words stable every few
  seconds during continuous speech. Words at the start of the interim that two
  interims in a row agree on (never the last, possibly cut-off word) are
  treated as stable right away, so sentences and clauses can be finalized
  and translated seconds sooner. When the provider's own stable text for that
  stretch arrives, the words already taken are skipped. Only for providers
  whose interims use the same wording as their stable text (Deepgram).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SENTENCE_END = re.compile(r"(?<=[.!?。！？؟])[\"'”’)\]]*\s+")
CLAUSE_BREAK = re.compile(r"[,;:，；：、]\s+|\s+[—–-]{1,2}\s+")
TERMINAL = re.compile(r"[.!?。！？؟][\"'”’)\]]*$")
# Abbreviations that end in a period but rarely end a sentence.
ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "st.", "rev.", "vs.", "jr.", "sr.", "ch.", "vv.", "v."}


@dataclass(frozen=True)
class Segment:
    seq: int
    text: str
    final: bool
    audio_end: float | None = None


class Segmenter:
    def __init__(self, max_chars: int = 140, clause_chars: int = 60, start_seq: int = 1, early_commit: bool = True) -> None:
        self.max_chars = max_chars
        self.early_commit = early_commit
        self.clause_chars = clause_chars
        self.seq = start_seq
        self.committed = ""
        self.interim = ""
        self._prev_interim: list[str] = []  # previous interim, as words
        self._taken = 0  # words of the current interim stretch already moved into committed
        self._last_partial: tuple[int, str] | None = None

    # -- provider events -------------------------------------------------
    def on_interim(self, text: str, audio_end: float | None = None) -> list[Segment]:
        if not self.early_commit:
            self.interim = text.strip()
            return self._partial(audio_end)
        words = text.split()
        agreed = 0
        for a, b in zip(self._prev_interim, words[:-1]):
            if a != b:
                break
            agreed += 1
        self._prev_interim = words
        out: list[Segment] = []
        if agreed > self._taken:
            self._append(" ".join(words[self._taken : agreed]))
            self._taken = agreed
            out = self._cut_sentences(audio_end)
        self.interim = " ".join(words[self._taken :])
        out.extend(self._partial(audio_end))
        return out

    def on_stable(self, text: str, audio_end: float | None = None) -> list[Segment]:
        # Skip the words already taken early from this stretch's interims.
        self._append(" ".join(text.split()[self._taken :]))
        self._taken = 0
        self._prev_interim = []
        self.interim = ""
        out = self._cut_sentences(audio_end)
        out.extend(self._partial(audio_end))
        return out

    def on_endpoint(self, audio_end: float | None = None) -> list[Segment]:
        out: list[Segment] = []
        if self.committed:
            out.append(self._final(self.committed, audio_end))
            self.committed = ""
        out.extend(self._partial(audio_end))
        return out

    def _append(self, text: str) -> None:
        text = text.strip()
        if text:
            self.committed = f"{self.committed} {text}" if self.committed else text

    def flush(self) -> list[Segment]:
        """End of stream: finalize whatever is stable; drop unstable interim."""
        self.interim = ""
        return self.on_endpoint()

    # -- internals -----------------------------------------------------------
    def _final(self, text: str, audio_end: float | None) -> Segment:
        seg = Segment(self.seq, text.strip(), True, audio_end)
        self.seq += 1
        return seg

    def _cut_sentences(self, audio_end: float | None) -> list[Segment]:
        out: list[Segment] = []
        while True:
            cut = self._find_sentence_cut(self.committed)
            if cut is None:
                break
            sentence, self.committed = self.committed[:cut].strip(), self.committed[cut:].strip()
            if sentence:
                out.append(self._final(sentence, audio_end))
        while len(self.committed) >= self.clause_chars:
            cut = self._clause_cut(self.committed)
            if cut is None:
                break
            piece, self.committed = self.committed[:cut].strip(), self.committed[cut:].strip()
            out.append(self._final(piece, audio_end))
        while len(self.committed) > self.max_chars:
            split = self._soft_split(self.committed)
            piece, self.committed = self.committed[:split].strip(), self.committed[split:].strip()
            out.append(self._final(piece, audio_end))
        return out

    def _find_sentence_cut(self, text: str) -> int | None:
        for match in SENTENCE_END.finditer(text):
            before = text[: match.start()].rsplit(" ", 1)[-1].lower()
            if before in ABBREVIATIONS:
                continue
            return match.end()
        stripped = text.rstrip()
        if stripped and TERMINAL.search(stripped):
            last_word = stripped.rsplit(" ", 1)[-1].lower()
            if last_word not in ABBREVIATIONS:
                return len(text)
        return None

    def _clause_cut(self, text: str) -> int | None:
        """End of the last clause break that leaves a piece of at least clause_chars // 2."""
        best = None
        for m in CLAUSE_BREAK.finditer(text):
            if m.start() >= self.clause_chars // 2:
                best = m.end()
        return best

    def _soft_split(self, text: str) -> int:
        window = text[: self.max_chars]
        for sep in ("; ", ", ", " "):
            idx = window.rfind(sep)
            if idx > self.max_chars // 2:
                return idx + len(sep)
        return self.max_chars

    def _partial(self, audio_end: float | None) -> list[Segment]:
        text = f"{self.committed} {self.interim}".strip()
        key = (self.seq, text)
        if key == self._last_partial:
            return []
        self._last_partial = key
        return [Segment(self.seq, text, False, audio_end)]
