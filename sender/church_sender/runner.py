"""Glue between saved config, audio capture and the client: headless service + GUI background thread."""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
import time

from .audio import AudioCapture, find_device
from .client import STATE_LABELS, ClientSettings, SenderClient, validate_server_url
from .config import Config, get_extra_headers, get_token

log = logging.getLogger(__name__)


def build_client_settings(cfg: Config, token: str | None = None, headers: dict[str, str] | None = None) -> ClientSettings:
    validate_server_url(cfg.server_url)
    token = get_token() if token is None else token
    if not token:
        raise ValueError("No sender token saved — paste the token from Admin → Audio senders")
    return ClientSettings(
        url=cfg.server_url,
        token=token,
        extra_headers=get_extra_headers(cfg) if headers is None else headers,
        sample_rate=cfg.sample_rate,
        gain_db=cfg.gain_db,
    )


def open_capture(cfg: Config) -> AudioCapture:
    if not cfg.device_name:
        raise ValueError("No input device selected")
    device = find_device(cfg.device_name, cfg.device_hostapi)
    if device is None:
        raise RuntimeError(f"Input device '{cfg.device_name}' not found")
    capture = AudioCapture(device, cfg.channel)
    capture.start()
    return capture


class ClientThread(threading.Thread):
    """Runs a SenderClient's asyncio loop in the background (GUI)."""

    def __init__(self, client: SenderClient) -> None:
        super().__init__(name="sender-client", daemon=True)
        self.client = client

    def run(self) -> None:
        try:
            asyncio.run(self.client.run())
        except Exception:
            log.exception("client thread crashed")

    def stop(self, timeout: float = 5.0) -> None:
        self.client.stop()
        self.join(timeout)


def run_headless(cfg: Config) -> int:
    """Service mode: no GUI, saved config, waits for the audio device, runs until SIGINT/SIGTERM or revocation."""
    try:
        settings = build_client_settings(cfg)
    except ValueError as e:
        log.error("%s", e)
        return 2
    stop = threading.Event()

    def _signal(signum, frame):
        log.info("signal %s received, stopping", signum)
        stop.set()
        if client is not None:
            client.stop()

    client: SenderClient | None = None
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal)
        except (ValueError, OSError):
            pass

    capture = None
    while capture is None and not stop.is_set():
        try:
            capture = open_capture(cfg)
        except Exception as e:
            log.error("cannot open audio input (%s); retrying in 10 s", e)
            stop.wait(10)
    if capture is None:
        return 0

    client = SenderClient(settings, capture)
    status_thread = threading.Thread(target=_log_status, args=(client, stop), daemon=True)
    status_thread.start()
    try:
        snap = asyncio.run(client.run())
    finally:
        stop.set()
        capture.stop()
    return 3 if snap.state.value == "revoked" else 0


def _log_status(client: SenderClient, stop: threading.Event) -> None:
    """Periodic one-line status in headless logs."""
    while not stop.wait(60):
        s = client.snapshot()
        log.info(
            "status: %s campus=%s sent=%.1f MB reconnects=%d dropped=%.1fs%s",
            STATE_LABELS[s.state], s.campus or "-", s.bytes_sent / 1e6, s.reconnects, s.dropped_seconds,
            f" warning={s.warning}" if s.warning else "",
        )


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def connected_for(since: float | None) -> str:
    return format_duration(time.time() - since) if since else "—"
