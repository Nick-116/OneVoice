"""Local audio input: capture from an audio interface on the OneVoice server itself.

This is the default audio source for a campus. Instead of a OneVoice Sender app
streaming over the network, this service opens an input on the server (USB
audio interface, Dante AVIO adapter, Dante Virtual Soundcard on Linux...) and
feeds exactly the same pipeline: it writes 100 ms frames of 16 kHz mono PCM to
the campus's Redis audio stream (only while a service is live) and keeps the
same audio status the dashboard and caption-state logic already use.

The worker publishes which campuses use local input (and which device/channel)
to ``localaudio:config``; this service publishes the devices it can see to
``localaudio:devices`` so the dashboard can offer them.

Docker can only reach audio hardware on a Linux host (``/dev/snd``). On macOS or
Windows, run the OneVoice Sender app on the same computer instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Protocol

import numpy as np

from .. import rkeys
from ..audio_utils import pcm_levels

log = logging.getLogger(__name__)

OUT_RATE = 16000
FRAME_SAMPLES = OUT_RATE // 10  # 100 ms
STREAM_MAXLEN = 300
STATUS_TTL = 30
TEST_DEVICE = "Test tone (simulated)"

AudioCallback = Callable[[np.ndarray], None]


@dataclass(frozen=True)
class Device:
    name: str
    hostapi: str
    channels: int
    rate: int
    index: int = -1


class Stoppable(Protocol):
    def stop(self) -> None: ...


class SoundDeviceBackend:
    """Real audio hardware through PortAudio (ALSA on Linux)."""

    def list(self) -> list[Device]:
        import sounddevice as sd

        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                devices.append(Device(d["name"], sd.query_hostapis(d["hostapi"])["name"], int(d["max_input_channels"]),
                                      int(d.get("default_samplerate") or 48000), i))
        return devices

    def open(self, device: Device, channel: int, on_audio: AudioCallback) -> Stoppable:
        import sounddevice as sd

        col = channel - 1

        def callback(indata, frames, time_info, status):  # PortAudio thread: keep it tiny
            on_audio(indata[:, col].copy())

        stream = sd.InputStream(device=device.index, channels=channel, samplerate=device.rate, dtype="float32",
                                blocksize=device.rate // 50, callback=callback)
        stream.start()

        class _Handle:
            def stop(self) -> None:
                stream.stop()
                stream.close()

        return _Handle()


class TestToneBackend:
    """A simulated input (speech-like tone bursts) for testing without audio hardware."""

    def list(self) -> list[Device]:
        return [Device(TEST_DEVICE, "simulated", 2, 48000)]

    def open(self, device: Device, channel: int, on_audio: AudioCallback) -> Stoppable:
        stop = threading.Event()

        def run() -> None:
            rate, block = device.rate, device.rate // 50
            t, phase = 0, 0.0
            next_at = time.monotonic()
            while not stop.is_set():
                n = np.arange(block)
                syllable = ((t + n) // (rate // 5)) % 5 != 4  # 200 ms bursts with a pause every 5th
                freq = 140 + 60 * np.sin((t + n) / rate)
                phases = phase + np.cumsum(2 * np.pi * freq / rate)
                phase = float(phases[-1])
                on_audio((np.where(syllable, 0.2, 0.002) * np.sin(phases)).astype(np.float32))
                t += block
                next_at += block / rate
                stop.wait(max(0.0, next_at - time.monotonic()))

        threading.Thread(target=run, name="test-tone", daemon=True).start()

        class _Handle:
            def stop(self) -> None:
                stop.set()

        return _Handle()


class CompositeBackend:
    def __init__(self, *backends) -> None:
        self.backends = backends

    def list(self) -> list[Device]:
        out: list[Device] = []
        for b in self.backends:
            try:
                out.extend(b.list())
            except Exception as e:  # no PortAudio / no /dev/snd: just no hardware devices
                log.warning("cannot list audio devices: %s", e)
        return out

    def open(self, device: Device, channel: int, on_audio: AudioCallback) -> Stoppable:
        backend = self.backends[0] if len(self.backends) == 1 else None
        for b in self.backends:
            try:
                if any(d == device for d in b.list()):
                    backend = b
                    break
            except Exception:
                continue
        if backend is None:
            raise RuntimeError(f"no backend for {device.name}")
        return backend.open(device, channel, on_audio)


class Capture:
    """One campus: device callback -> bounded queue -> 16 kHz frames -> Redis."""

    def __init__(self, r, campus_id: int, slug: str, device: Device, channel: int, backend) -> None:
        self.r = r
        self.campus_id = campus_id
        self.slug = slug
        self.device = device
        self.channel = channel
        self.backend = backend
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=250)  # ~5 s of 20 ms blocks
        self.handle: Stoppable | None = None
        self.task: asyncio.Task | None = None
        self.connected_at = time.time()
        self.last_signal = self.connected_at

    @property
    def signature(self) -> tuple:
        return (self.device.name, self.channel)

    def on_audio(self, block: np.ndarray) -> None:
        try:
            self.q.put_nowait(block)
        except queue.Full:  # consumer stalled: keep the newest audio
            try:
                self.q.get_nowait()
                self.q.put_nowait(block)
            except queue.Empty:
                pass

    async def start(self) -> None:
        import soxr

        self.handle = self.backend.open(self.device, self.channel, self.on_audio)
        self.resampler = soxr.ResampleStream(self.device.rate, OUT_RATE, 1, dtype="float32")
        await self._history("connected")
        self.task = asyncio.create_task(self._run(), name=f"local-audio-{self.slug}")
        log.info("local capture started", extra={"fields": {"campus": self.slug, "device": self.device.name, "channel": self.channel}})

    async def stop(self) -> None:
        if self.handle:
            self.handle.stop()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.r.hset(rkeys.audio_status(self.campus_id), mapping={"connected": "0", "disconnected_at": time.time()})
        await self._history("disconnected", reason="local input stopped")

    async def _history(self, event: str, **fields) -> None:
        entry = json.dumps({"at": time.time(), "event": event, "sender": f"Local input: {self.device.name}", **fields})
        async with self.r.pipeline(transaction=False) as p:
            p.lpush(rkeys.audio_history(self.campus_id), entry)
            p.ltrim(rkeys.audio_history(self.campus_id), 0, 49)
            await p.execute()

    async def _run(self) -> None:
        pending = np.zeros(0, dtype=np.float32)
        live: str | None = None
        last_live_check = 0.0
        status_key = rkeys.audio_status(self.campus_id)
        while True:
            blocks = []
            while True:
                try:
                    blocks.append(self.q.get_nowait())
                except queue.Empty:
                    break
            if not blocks:
                await asyncio.sleep(0.02)
                continue
            out = self.resampler.resample_chunk(np.concatenate(blocks))
            pending = np.concatenate([pending, out])
            while len(pending) >= FRAME_SAMPLES:
                frame, pending = pending[:FRAME_SAMPLES], pending[FRAME_SAMPLES:]
                pcm = (np.clip(frame, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                now = time.time()
                if time.monotonic() - last_live_check >= 1.0:
                    live = await self.r.get(rkeys.campus_live_flag(self.campus_id))
                    last_live_check = time.monotonic()
                rms, peak, has_signal = pcm_levels(pcm)
                if has_signal:
                    self.last_signal = now
                async with self.r.pipeline(transaction=False) as p:
                    if live:
                        p.xadd(rkeys.audio_stream(self.campus_id), {"pcm": pcm, "sr": OUT_RATE, "t": f"{now:.3f}"},
                               maxlen=STREAM_MAXLEN, approximate=True)
                    p.hset(status_key, mapping={
                        "connected": "1", "source": "local", "sender_name": f"Local input: {self.device.name} (ch {self.channel})",
                        "connected_at": self.connected_at, "last_frame_at": f"{now:.3f}", "last_signal_at": f"{self.last_signal:.3f}",
                        "level_dbfs": rms, "peak_dbfs": peak, "sample_rate": OUT_RATE, "format": "s16le", "channels": 1,
                        "remote_ip": "local", "live": 1 if live else 0,
                    })
                    p.expire(status_key, STATUS_TTL)
                    await p.execute()


class LocalAudioService:
    def __init__(self, r, backend) -> None:
        self.r = r
        self.backend = backend
        self.captures: dict[int, Capture] = {}
        self.failures: dict[int, float] = {}

    async def publish_devices(self) -> list[Device]:
        devices = self.backend.list()
        payload = json.dumps([{k: v for k, v in asdict(d).items() if k != "index"} for d in devices])
        async with self.r.pipeline(transaction=False) as p:
            p.set(rkeys.LOCALAUDIO_DEVICES, payload, ex=30)
            p.set(rkeys.LOCALAUDIO_HEARTBEAT, str(time.time()), ex=30)
            await p.execute()
        return devices

    async def reconcile(self) -> None:
        devices = await self.publish_devices()
        raw = await self.r.get(rkeys.LOCALAUDIO_CONFIG)
        wanted = {int(c["campus_id"]): c for c in (json.loads(raw) if raw else [])}
        for cid in list(self.captures):
            cfg = wanted.get(cid)
            cap = self.captures[cid]
            if cfg is None or (cfg.get("device"), int(cfg.get("channel") or 1)) != cap.signature:
                await cap.stop()
                del self.captures[cid]
        for cid, cfg in wanted.items():
            if cid in self.captures or not cfg.get("device"):
                continue
            if time.monotonic() - self.failures.get(cid, 0) < 5:
                continue  # back off after a failed open
            device = next((d for d in devices if d.name == cfg["device"]), None)
            channel = int(cfg.get("channel") or 1)
            if device is None or channel > device.channels:
                self.failures[cid] = time.monotonic()
                await self.r.hset(rkeys.audio_status(cid), mapping={
                    "connected": "0", "source": "local",
                    "local_error": f"Device '{cfg['device']}' (channel {channel}) not found on the server"})
                await self.r.expire(rkeys.audio_status(cid), STATUS_TTL)
                continue
            cap = Capture(self.r, cid, cfg.get("slug", str(cid)), device, channel, self.backend)
            try:
                await cap.start()
                self.captures[cid] = cap
                await self.r.hdel(rkeys.audio_status(cid), "local_error")
            except Exception as e:
                self.failures[cid] = time.monotonic()
                log.warning("cannot open local input", extra={"fields": {"campus": cid, "error": repr(e)}})

    async def run(self) -> None:
        while True:
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("local audio reconcile failed")
            await asyncio.sleep(2)

    async def stop_all(self) -> None:
        for cap in list(self.captures.values()):
            await cap.stop()
        self.captures.clear()
