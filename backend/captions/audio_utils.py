"""Audio helpers shared by the ingest service and the local-audio service."""

from __future__ import annotations

import array
import math
import sys


def pcm_levels(pcm: bytes) -> tuple[float, float, bool]:
    """Return (rms dBFS, peak dBFS, has_signal) for s16le mono PCM."""
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return -120.0, -120.0, False
    peak = max(abs(min(samples)), abs(max(samples)))
    # Subsample for RMS: plenty accurate for a meter, cheap on CPU.
    step = max(1, len(samples) // 400)
    sub = samples[::step]
    rms = math.sqrt(sum(s * s for s in sub) / len(sub))

    def to_db(v: float) -> float:
        return 20 * math.log10(v / 32768.0) if v > 0 else -120.0

    # Any non-zero sample counts as signal; true digital silence is exactly zero.
    return round(to_db(rms), 1), round(to_db(peak), 1), peak > 1
