"""Audio capture, channel selection, level metering, resampling and framing.

Threading model: PortAudio calls :meth:`AudioCapture._callback` on its own
real-time thread. The callback only copies the selected channel, records a
tiny level summary and appends the chunk to a bounded :class:`DropOldestBuffer`.
Everything heavier (resampling, int16 conversion, framing) happens on the
asyncio side in :class:`AudioPipeline`.

``sounddevice`` is imported lazily so that the rest of the package (and the
tests) work on machines without PortAudio.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

SILENCE_DB = -120.0
CLIP_LEVEL = 0.999  # |sample| at or above this (~ -0.01 dBFS) counts as clipping
SUPPORTED_RATES = (16000, 24000, 48000)


def _sd():
    import sounddevice as sd  # lazy: needs the PortAudio shared library

    return sd


# ---------------------------------------------------------------- devices


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    default_samplerate: float

    @property
    def label(self) -> str:
        return f"{self.name}  [{self.hostapi}, {self.max_input_channels} ch, {int(self.default_samplerate)} Hz]"


def list_input_devices() -> list[InputDevice]:
    sd = _sd()
    hostapis = sd.query_hostapis()
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if int(d["max_input_channels"]) > 0:
            devices.append(
                InputDevice(
                    index=i,
                    name=str(d["name"]),
                    hostapi=str(hostapis[d["hostapi"]]["name"]),
                    max_input_channels=int(d["max_input_channels"]),
                    default_samplerate=float(d["default_samplerate"]),
                )
            )
    return devices


def find_device(name: str, hostapi: str | None = None, devices: list[InputDevice] | None = None) -> InputDevice | None:
    """Resolve a saved device by name (+ host API). Indices change between boots; names don't."""
    if not name:
        return None
    devices = list_input_devices() if devices is None else devices
    for d in devices:
        if d.name == name and (not hostapi or d.hostapi == hostapi):
            return d
    for d in devices:  # same device under a different host API
        if d.name == name:
            return d
    return None


# ---------------------------------------------------------------- levels


def to_db(value: float) -> float:
    return 20.0 * math.log10(value) if value > 1e-6 else SILENCE_DB


@dataclass(frozen=True)
class Levels:
    rms_db: float
    peak_db: float
    clipped: bool


def compute_levels(x, gain_db: float = 0.0) -> Levels:
    """RMS / peak in dBFS (full-scale sine peak = 0 dBFS, RMS = -3 dBFS) after an optional gain."""
    a = np.asarray(x, dtype=np.float32).reshape(-1)
    if a.size == 0:
        return Levels(SILENCE_DB, SILENCE_DB, False)
    g = 10.0 ** (gain_db / 20.0)
    peak = float(np.max(np.abs(a))) * g
    rms = math.sqrt(float(np.mean(np.square(a, dtype=np.float64)))) * g
    return Levels(round(to_db(rms), 1), round(to_db(peak), 1), peak >= CLIP_LEVEL)


class LevelMeter:
    """Lock-free level accumulator: the audio thread appends block summaries, the GUI drains them."""

    def __init__(self) -> None:
        self._blocks: deque[tuple[float, float, int]] = deque(maxlen=1000)
        self.last_update = 0.0

    def push(self, x: np.ndarray) -> None:  # audio thread: O(n) numpy, no locks
        if x.size == 0:
            return
        self._blocks.append((float(np.max(np.abs(x))), float(np.dot(x, x)), int(x.size)))
        self.last_update = time.monotonic()

    def read(self, gain_db: float = 0.0) -> Levels | None:
        """Levels over everything pushed since the last read, or None if nothing arrived."""
        peak, ss, n = 0.0, 0.0, 0
        while True:
            try:
                p, s, k = self._blocks.popleft()
            except IndexError:
                break
            peak, ss, n = max(peak, p), ss + s, n + k
        if n == 0:
            return None
        g = 10.0 ** (gain_db / 20.0)
        return Levels(round(to_db(math.sqrt(ss / n) * g), 1), round(to_db(peak * g), 1), peak * g >= CLIP_LEVEL)


# ---------------------------------------------------------------- buffering


class DropOldestBuffer:
    """Bounded, thread-safe FIFO of (timestamp, float32 chunk).

    When full, the *oldest* audio is discarded: for live captions current audio
    is always worth more than a backlog.
    """

    def __init__(self, sample_rate: int, max_seconds: float = 2.0) -> None:
        self.sample_rate = int(sample_rate)
        self.max_samples = max(1, int(sample_rate * max_seconds))
        self._chunks: deque[tuple[float, np.ndarray]] = deque()
        self._samples = 0
        self._lock = threading.Lock()
        self.dropped_samples = 0
        self.pushed_samples = 0

    def __len__(self) -> int:
        return self._samples

    def push(self, chunk: np.ndarray, t: float | None = None) -> None:
        t = time.monotonic() if t is None else t
        n = len(chunk)
        with self._lock:
            self.pushed_samples += n
            if n > self.max_samples:
                self.dropped_samples += n - self.max_samples
                chunk = chunk[-self.max_samples:]
                n = self.max_samples
            self._chunks.append((t, chunk))
            self._samples += n
            while self._samples > self.max_samples:
                ot, oc = self._chunks[0]
                excess = self._samples - self.max_samples
                if len(oc) <= excess:
                    self._chunks.popleft()
                    self._samples -= len(oc)
                    self.dropped_samples += len(oc)
                else:
                    self._chunks[0] = (ot, oc[excess:])
                    self._samples -= excess
                    self.dropped_samples += excess

    def pop_all(self) -> list[tuple[float, np.ndarray]]:
        with self._lock:
            items = list(self._chunks)
            self._chunks.clear()
            self._samples = 0
        return items

    def discard_older_than(self, max_age: float, now: float | None = None) -> int:
        """Drop chunks captured more than ``max_age`` seconds ago; returns samples dropped."""
        now = time.monotonic() if now is None else now
        dropped = 0
        with self._lock:
            while self._chunks and now - self._chunks[0][0] > max_age:
                _, c = self._chunks.popleft()
                self._samples -= len(c)
                dropped += len(c)
            self.dropped_samples += dropped
        return dropped

    def clear(self) -> None:
        self.pop_all()


# ---------------------------------------------------------------- conversion


def float_to_s16le(x: np.ndarray) -> bytes:
    """float32 [-1, 1] -> signed 16-bit little-endian PCM (clipped, rounded)."""
    a = np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0)
    return np.rint(a * 32767.0).astype("<i2").tobytes()


class AudioPipeline:
    """Gain -> soxr resample (streaming, stateful) -> int16 LE -> fixed-size frames."""

    def __init__(self, in_rate: int, out_rate: int, gain_db: float = 0.0, frame_ms: int = 100, quality: str = "HQ") -> None:
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self.quality = quality
        self.frame_samples = self.out_rate * frame_ms // 1000
        self.frame_bytes = self.frame_samples * 2
        self.gain_db = gain_db
        self._resampler = None
        self._pending = bytearray()
        self.reset()

    @property
    def gain_db(self) -> float:
        return self._gain_db

    @gain_db.setter
    def gain_db(self, value: float) -> None:
        self._gain_db = max(-20.0, min(20.0, float(value)))
        self._gain = 10.0 ** (self._gain_db / 20.0)

    def reset(self) -> None:
        """Forget resampler history and any partial frame (used on reconnect)."""
        if self.in_rate != self.out_rate:
            import soxr

            self._resampler = soxr.ResampleStream(self.in_rate, self.out_rate, 1, dtype="float32", quality=self.quality)
        else:
            self._resampler = None
        self._pending = bytearray()

    def process(self, chunk: np.ndarray) -> list[bytes]:
        x = np.ascontiguousarray(np.asarray(chunk, dtype=np.float32).reshape(-1))
        if self._gain != 1.0:
            x = x * np.float32(self._gain)
        y = self._resampler.resample_chunk(x) if self._resampler is not None else x
        if len(y):
            self._pending += float_to_s16le(y)
        fb = self.frame_bytes
        frames = []
        while len(self._pending) >= fb:
            frames.append(bytes(self._pending[:fb]))
            del self._pending[:fb]
        return frames


# ---------------------------------------------------------------- capture


class AudioCapture:
    """Captures one channel of an input device into a DropOldestBuffer + LevelMeter.

    ``forward`` controls whether audio goes into the buffer (streaming) or only
    feeds the meter ("Test input").
    """

    def __init__(self, device: InputDevice, channel: int, buffer_seconds: float = 2.0, block_ms: int = 20) -> None:
        if not 1 <= channel <= device.max_input_channels:
            raise ValueError(f"Channel {channel} not available on '{device.name}' (1..{device.max_input_channels})")
        self.device = device
        self.channel = channel
        self.sample_rate = int(device.default_samplerate)
        self.block_ms = block_ms
        self.buffer = DropOldestBuffer(self.sample_rate, buffer_seconds)
        self.meter = LevelMeter()
        self.forward = False
        self.last_callback = 0.0
        self.status_events = 0
        self._col = channel - 1
        self._stream = None

    # PortAudio real-time thread: keep it tiny and never block.
    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self.status_events += 1
        x = indata[:, self._col].copy()
        now = time.monotonic()
        self.last_callback = now
        self.meter.push(x)
        if self.forward:
            self.buffer.push(x, now)

    @property
    def running(self) -> bool:
        return self._stream is not None and bool(self._stream.active)

    def start(self) -> None:
        if self._stream is not None:
            return
        sd = _sd()
        extra = None
        channels = self.channel
        self._col = self.channel - 1
        if "ASIO" in self.device.hostapi.upper():
            # ASIO can open a single selected channel instead of all 64 DVS channels.
            extra = sd.AsioSettings(channel_selectors=[self.channel - 1])
            channels, self._col = 1, 0
        stream = sd.InputStream(
            device=self.device.index,
            channels=channels,
            samplerate=self.sample_rate,
            dtype="float32",
            blocksize=max(1, self.sample_rate * self.block_ms // 1000),
            callback=self._callback,
            extra_settings=extra,
        )
        stream.start()
        self._stream = stream
        self.last_callback = time.monotonic()
        log.info("audio capture started: %s ch %d @ %d Hz", self.device.label, self.channel, self.sample_rate)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("error closing audio stream")
            log.info("audio capture stopped")

    def restart(self) -> None:
        """Reopen the stream, re-resolving the device by name (indices change after hot-plug)."""
        self.stop()
        try:
            _sd()._terminate()
            _sd()._initialize()
        except Exception:
            pass
        dev = find_device(self.device.name, self.device.hostapi)
        if dev is None:
            raise RuntimeError(f"Input device '{self.device.name}' not found")
        self.device = dev
        self.start()
