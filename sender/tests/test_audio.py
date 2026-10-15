import threading

import numpy as np
import pytest

from church_sender.audio import (
    SILENCE_DB,
    AudioPipeline,
    DropOldestBuffer,
    LevelMeter,
    compute_levels,
    float_to_s16le,
)


def sine(freq, rate, seconds, amp=0.5):
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def run_pipeline(pipeline, signal, chunk):
    frames = []
    for i in range(0, len(signal), chunk):
        frames += pipeline.process(signal[i:i + chunk])
    return frames


# ---------------------------------------------------------------- conversion / framing

def test_float_to_s16le_values_and_clipping():
    data = float_to_s16le(np.array([0.0, 1.0, -1.0, 2.0, -2.0, 0.5], dtype=np.float32))
    assert np.frombuffer(data, "<i2").tolist() == [0, 32767, -32767, 32767, -32767, 16384]
    assert data[2:4] == b"\xff\x7f"  # little endian


def test_48k_to_16k_frames_are_exactly_3200_bytes():
    p = AudioPipeline(48000, 16000)
    assert p.frame_bytes == 3200
    frames = run_pipeline(p, sine(1000, 48000, 2.0), 960)  # 20 ms callback blocks
    assert len(frames) >= 19  # 2 s => 20 frames minus resampler group delay
    assert all(isinstance(f, bytes) and len(f) == 3200 for f in frames)
    pcm = np.frombuffer(b"".join(frames[2:]), "<i2").astype(np.float64) / 32767
    rms = np.sqrt(np.mean(pcm ** 2))
    assert rms == pytest.approx(0.5 / np.sqrt(2), rel=0.02)
    # dominant frequency survives resampling
    spec = np.abs(np.fft.rfft(pcm))
    assert np.fft.rfftfreq(len(pcm), 1 / 16000)[spec.argmax()] == pytest.approx(1000, abs=5)


def test_irregular_chunks_still_frame_exactly():
    p = AudioPipeline(48000, 16000)
    sig = sine(440, 48000, 1.5)
    frames, i, rng = [], 0, np.random.default_rng(1)
    while i < len(sig):
        n = int(rng.integers(1, 3000))
        frames += p.process(sig[i:i + n])
        i += n
    assert frames and all(len(f) == 3200 for f in frames)


@pytest.mark.parametrize("out_rate,frame_bytes", [(24000, 4800), (48000, 9600)])
def test_other_rates(out_rate, frame_bytes):
    p = AudioPipeline(48000, out_rate)
    frames = run_pipeline(p, sine(500, 48000, 1.0), 960)
    assert frames and all(len(f) == frame_bytes for f in frames)
    if out_rate == 48000:  # passthrough: exact sample count
        assert len(frames) == 10


def test_gain_applied():
    p = AudioPipeline(16000, 16000, gain_db=6.0206)
    frames = p.process(np.full(1600, 0.25, dtype=np.float32))
    assert np.frombuffer(frames[0], "<i2")[0] == pytest.approx(16384, abs=2)


def test_reset_discards_partial_frame():
    p = AudioPipeline(16000, 16000)
    assert p.process(np.zeros(1000, np.float32)) == []
    p.reset()
    assert p.process(np.zeros(1000, np.float32)) == []
    assert len(p.process(np.zeros(600, np.float32))) == 1


# ---------------------------------------------------------------- drop-oldest buffer

def test_buffer_drops_oldest():
    b = DropOldestBuffer(sample_rate=1000, max_seconds=2.0)
    for i in range(30):  # 3 s of 100-sample chunks, values = chunk index
        b.push(np.full(100, i, np.float32), t=float(i))
    assert len(b) == 2000
    assert b.dropped_samples == 1000
    chunks = b.pop_all()
    assert chunks[0][1][0] == 10 and chunks[-1][1][0] == 29  # oldest gone, newest kept
    assert len(b) == 0


def test_buffer_partial_trim_and_oversized_chunk():
    b = DropOldestBuffer(sample_rate=100, max_seconds=1.0)
    b.push(np.arange(80, dtype=np.float32), t=0)
    b.push(np.arange(50, dtype=np.float32), t=1)
    assert len(b) == 100 and b.dropped_samples == 30
    assert b.pop_all()[0][1][0] == 30
    b.push(np.arange(250, dtype=np.float32), t=2)
    data = b.pop_all()
    assert len(data[0][1]) == 100 and data[0][1][0] == 150


def test_buffer_discard_older_than():
    b = DropOldestBuffer(sample_rate=1000, max_seconds=2.0)
    for i in range(20):
        b.push(np.zeros(100, np.float32), t=10.0 + i * 0.1)
    dropped = b.discard_older_than(1.0, now=12.0)
    assert dropped == 1000 and len(b) == 1000
    assert min(t for t, _ in b.pop_all()) >= 11.0


def test_buffer_thread_safety():
    b = DropOldestBuffer(sample_rate=48000, max_seconds=0.5)
    got = []
    stop = threading.Event()

    def producer():
        for _ in range(2000):
            b.push(np.ones(48, np.float32))
        stop.set()

    def consumer():
        while not stop.is_set() or len(b):
            got.extend(len(c) for _, c in b.pop_all())

    threads = [threading.Thread(target=producer), threading.Thread(target=consumer)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(got) + b.dropped_samples == 2000 * 48
    assert len(b) == 0


# ---------------------------------------------------------------- levels

def test_levels_full_scale_sine():
    lv = compute_levels(sine(1000, 48000, 0.5, amp=1.0))
    assert lv.peak_db == pytest.approx(0.0, abs=0.05)
    assert lv.rms_db == pytest.approx(-3.01, abs=0.05)
    assert lv.clipped


def test_levels_silence_and_gain():
    assert compute_levels(np.zeros(480, np.float32)).rms_db == SILENCE_DB
    assert compute_levels(np.zeros(0, np.float32)).peak_db == SILENCE_DB
    lv = compute_levels(sine(1000, 48000, 0.5, amp=0.1))
    assert lv.peak_db == pytest.approx(-20.0, abs=0.05) and not lv.clipped
    boosted = compute_levels(sine(1000, 48000, 0.5, amp=0.1), gain_db=20)
    assert boosted.peak_db == pytest.approx(0.0, abs=0.05) and boosted.clipped


def test_level_meter_aggregates_blocks():
    m = LevelMeter()
    assert m.read() is None
    m.push(np.full(100, 0.5, np.float32))
    m.push(np.full(100, -0.25, np.float32))
    lv = m.read()
    assert lv.peak_db == pytest.approx(-6.02, abs=0.05)
    assert lv.rms_db == pytest.approx(20 * np.log10(np.sqrt((0.25 + 0.0625) / 2)), abs=0.05)
    assert m.read() is None  # drained
    m.push(np.full(10, 0.6, np.float32))
    assert m.read(gain_db=6.0).clipped
