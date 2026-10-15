#!/usr/bin/env python3
"""Simulated church audio sender for testing without a Yamaha console or Dante.

Streams real-time 16 kHz mono PCM to the ingest service using the same
protocol as the desktop sender app. Audio is either a WAV file (16-bit PCM,
any rate/channels; it is down-mixed and resampled linearly) or a synthetic
"speech-like" tone pattern. Combine with the `simulated` STT provider to test
the entire pipeline for free, or with Deepgram + a recorded sermon WAV to
measure real latency.

    python tools/simulate_sender.py --url ws://localhost:8082/ingest/v1/stream --token cs_... [--wav sermon.wav]

Requires: pip install websockets==13.1
"""

from __future__ import annotations

import argparse
import array
import asyncio
import json
import math
import random
import sys
import time
import wave

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

RATE = 16000
FRAME_MS = 100
FRAME_SAMPLES = RATE * FRAME_MS // 1000


def load_wav(path: str) -> array.array:
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            sys.exit("WAV must be 16-bit PCM")
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = array.array("h")
        raw.frombytes(w.readframes(n))
    mono = array.array("h", (sum(raw[i:i + ch]) // ch for i in range(0, len(raw), ch))) if ch > 1 else raw
    if rate == RATE:
        return mono
    ratio = rate / RATE
    out = array.array("h")
    for i in range(int(len(mono) / ratio)):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        a = mono[j]
        b = mono[j + 1] if j + 1 < len(mono) else a
        out.append(int(a + (b - a) * frac))
    return out


def synthetic_frames():
    """Endless speech-like signal: syllable bursts with short pauses."""
    phase = 0.0
    t = 0
    while True:
        frame = array.array("h")
        for _ in range(FRAME_SAMPLES):
            syllable = (t // 3200) % 5 != 4  # 200 ms bursts, every 5th is a pause
            amp = 6000 if syllable else 40
            freq = 140 + 60 * math.sin(t / 8000)
            phase += 2 * math.pi * freq / RATE
            frame.append(int(amp * math.sin(phase) + random.randint(-30, 30)))
            t += 1
        yield frame.tobytes()


def wav_frames(samples: array.array):
    while True:
        for i in range(0, len(samples) - FRAME_SAMPLES, FRAME_SAMPLES):
            yield samples[i:i + FRAME_SAMPLES].tobytes()


async def run(args) -> None:
    frames = wav_frames(load_wav(args.wav)) if args.wav else synthetic_frames()
    url = f"{args.url}?sample_rate={RATE}&channels=1&format=s16le"
    headers = {"Authorization": f"Bearer {args.token}"}
    for h in args.header or []:
        k, _, v = h.partition(":")
        headers[k.strip()] = v.strip()
    backoff = 1.0
    while True:
        try:
            async with connect(url, additional_headers=headers, ping_interval=10, max_size=2**16) as ws:
                print("connected", flush=True)
                backoff = 1.0

                async def reader():
                    async for msg in ws:
                        st = json.loads(msg)
                        print(f"server status: campus={st.get('campus')} live={st.get('live')}", flush=True)

                rtask = asyncio.create_task(reader())
                next_at = time.monotonic()
                try:
                    while True:
                        await ws.send(next(frames))
                        next_at += FRAME_MS / 1000
                        await asyncio.sleep(max(0, next_at - time.monotonic()))
                finally:
                    rtask.cancel()
        except InvalidStatus as e:
            print(f"rejected: HTTP {e.response.status_code} (bad token, revoked, or IP not allowed)", flush=True)
            backoff = 30.0
        except (ConnectionClosed, OSError) as e:
            print(f"connection lost: {e!r}", flush=True)
        await asyncio.sleep(backoff + random.random())
        backoff = min(backoff * 2, 30.0)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="ws://localhost:8082/ingest/v1/stream")
    p.add_argument("--token", required=True)
    p.add_argument("--wav")
    p.add_argument("--header", action="append", help="extra header 'Name: value' (e.g. Pangolin access token)")
    try:
        asyncio.run(run(p.parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
