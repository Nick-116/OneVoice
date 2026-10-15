"""Asyncio WebSocket client for the ingest service (see docs/API.md section 3).

One persistent connection; automatic reconnection with exponential backoff and
jitter; a status watchdog; close-code handling. The audio source only needs
``sample_rate``, ``buffer`` (a DropOldestBuffer) and a ``forward`` flag;
``last_callback`` and ``restart()`` are used when present.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import random
import ssl
import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, InvalidURI

from . import __version__
from .audio import AudioPipeline

log = logging.getLogger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

AUTH_FAILED_MSG = "Authentication failed — check token / IP allowlist"
REVOKED_MSG = "This sender was revoked"
REPLACED_MSG = "Replaced by another sender for this campus (is a second computer streaming?)"
NO_AUDIO_MSG = "No audio from the input device"
LOCAL_SOURCE_MSG = "This campus is set to use the server's own audio input. To use this app, set the campus audio source to Remote in the admin dashboard."


class LinkState(str, Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    STANDBY = "standby"  # connected, server says not live
    LIVE = "live"  # connected, forwarding to captions
    RETRY_WAIT = "retry_wait"  # disconnected, waiting to reconnect
    REVOKED = "revoked"


STATE_LABELS = {
    LinkState.STOPPED: "Disconnected",
    LinkState.CONNECTING: "Connecting…",
    LinkState.STANDBY: "Connected – standby",
    LinkState.LIVE: "Connected – LIVE",
    LinkState.RETRY_WAIT: "Disconnected – retrying",
    LinkState.REVOKED: "Revoked",
}


# ---------------------------------------------------------------- URL helpers


def is_local_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip("[]").lower()
    if host in LOCAL_HOSTS or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


LAN_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal")


def is_private_network_host(host: str | None) -> bool:
    """Loopback, RFC 1918 / ULA addresses, link-local, or an obviously-local name."""
    if not host:
        return False
    if is_local_host(host):
        return True
    host = host.strip("[]").lower()
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_link_local
    except ValueError:
        return "." not in host or host.endswith(LAN_SUFFIXES)


def validate_server_url(url: str) -> str | None:
    """Raise ValueError if unusable; return a warning for unencrypted ws:// on a local network."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("wss", "ws") or not parts.hostname:
        raise ValueError("Server URL must start with wss:// or ws:// (e.g. wss://audio.example.com/ingest/v1/stream)")
    if parts.scheme == "ws":
        if not is_private_network_host(parts.hostname):
            raise ValueError("Unencrypted ws:// is only allowed on a local network; use wss:// over the internet")
        return "Unencrypted connection (ws://): fine on your own local network, use wss:// over the internet"
    return None


def build_stream_url(url: str, sample_rate: int) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("sample_rate", "channels", "format")]
    query += [("sample_rate", str(int(sample_rate))), ("channels", "1"), ("format", "s16le")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), ""))


def make_ssl_context() -> ssl.SSLContext:
    """System trust store plus certifi (frozen apps often lack system CA paths). Verification always on."""
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


# ---------------------------------------------------------------- settings / state


@dataclass
class ClientSettings:
    url: str
    token: str = field(repr=False)
    extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    sample_rate: int = 16000
    gain_db: float = 0.0
    frame_ms: int = 100
    initial_backoff: float = 1.0
    max_backoff: float = 30.0
    auth_backoff: float = 60.0
    stable_after: float = 60.0
    status_timeout: float = 10.0
    open_timeout: float = 10.0
    reconnect_max_age: float = 1.0
    audio_stall_seconds: float = 5.0


@dataclass(frozen=True)
class Snapshot:
    state: LinkState = LinkState.STOPPED
    live: bool = False
    campus: str | None = None
    connected_since: float | None = None  # wall clock
    bytes_sent: int = 0
    frames_sent: int = 0
    reconnects: int = 0
    last_error: str | None = None
    warning: str | None = None
    retry_at: float | None = None
    dropped_seconds: float = 0.0

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]


class Backoff:
    """Exponential backoff with jitter: base doubles from ``initial`` to ``maximum``; delay is 50-100 % of base."""

    def __init__(self, initial: float, maximum: float, rng=random.random) -> None:
        self.initial, self.maximum, self.rng = initial, maximum, rng
        self.attempt = 0

    def next(self) -> float:
        base = min(self.maximum, self.initial * (2 ** self.attempt))
        self.attempt += 1
        return base * (0.5 + 0.5 * self.rng())

    def reset(self) -> None:
        self.attempt = 0


@dataclass
class _Outcome:
    kind: str  # "stopped" | "auth" | "policy" | "revoked" | "error"
    message: str | None = None
    duration: float = 0.0


# ---------------------------------------------------------------- client


class SenderClient:
    def __init__(self, settings: ClientSettings, source) -> None:
        self.settings = settings
        self.source = source
        self.pipeline = AudioPipeline(source.sample_rate, settings.sample_rate, settings.gain_db, settings.frame_ms)
        self._lock = threading.Lock()
        self._snap = Snapshot()
        self._link_warning: str | None = None
        self._audio_warning: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = False
        self._last_status = 0.0
        self.connect_attempts = 0

    # -------- thread-safe API for the GUI / service

    def snapshot(self) -> Snapshot:
        with self._lock:
            snap = self._snap
        warning = self._audio_warning or self._link_warning
        dropped = getattr(self.source.buffer, "dropped_samples", 0) / max(1, self.source.sample_rate)
        return replace(snap, warning=warning, dropped_seconds=round(dropped, 1))

    def stop(self) -> None:
        self._stop_requested = True
        loop, ev = self._loop, self._stop_event
        if loop is not None and ev is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:
                pass

    def set_gain_db(self, gain_db: float) -> None:
        self.pipeline.gain_db = gain_db  # simple attribute swap; safe across threads

    # -------- internals

    def _set(self, **kw) -> None:
        with self._lock:
            old = self._snap
            self._snap = replace(old, **kw)
        if "state" in kw and kw["state"] != old.state:
            log.info("state: %s", STATE_LABELS[kw["state"]])

    def _error(self, message: str) -> None:
        log.warning("%s", message)
        self._set(last_error=f"{time.strftime('%H:%M:%S')}  {message}")

    @property
    def _stopping(self) -> bool:
        return self._stop_requested or (self._stop_event is not None and self._stop_event.is_set())

    async def _sleep_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def run(self) -> Snapshot:
        """Run until :meth:`stop` is called or the sender is revoked."""
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        if self._stop_requested:
            self._stop_event.set()
        s = self.settings
        backoff = Backoff(s.initial_backoff, s.max_backoff)
        self.source.forward = True
        watchdog = asyncio.create_task(self._audio_watchdog())
        try:
            first = True
            while not self._stopping:
                if not first:
                    self._set(reconnects=self._snap.reconnects + 1)
                first = False
                outcome = await self._connect_once()
                if outcome.kind == "stopped" or self._stopping:
                    break
                if outcome.kind == "revoked":
                    self._set(state=LinkState.REVOKED, live=False, connected_since=None, retry_at=None)
                    self._error(REVOKED_MSG)
                    return self.snapshot()
                if outcome.message:
                    self._error(outcome.message)
                if outcome.duration >= s.stable_after:
                    backoff.reset()
                delay = s.auth_backoff if outcome.kind in ("auth", "policy") else backoff.next()
                log.info("reconnecting in %.1f s", delay)
                self._set(state=LinkState.RETRY_WAIT, live=False, connected_since=None, retry_at=time.time() + delay)
                await self._sleep_or_stop(delay)
        finally:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
            self.source.forward = False
            if self._snap.state != LinkState.REVOKED:
                self._set(state=LinkState.STOPPED, live=False, connected_since=None, retry_at=None)
        return self.snapshot()

    async def _connect_once(self) -> _Outcome:
        s = self.settings
        url = build_stream_url(s.url, s.sample_rate)
        headers = {k: v for k, v in s.extra_headers.items() if k.lower() != "authorization"}
        headers["Authorization"] = f"Bearer {s.token}"
        kwargs = dict(
            additional_headers=headers,
            open_timeout=s.open_timeout,
            close_timeout=2,
            ping_interval=20,
            ping_timeout=20,
            compression=None,
            max_size=2 ** 16,
            user_agent_header=f"onevoice-sender/{__version__}",
        )
        if url.startswith("wss://"):
            kwargs["ssl"] = make_ssl_context()
        self._set(state=LinkState.CONNECTING, retry_at=None)
        self.connect_attempts += 1
        log.info("connecting to %s", url)

        connect_task = asyncio.ensure_future(connect(url, **kwargs))
        stop_task = asyncio.ensure_future(self._stop_event.wait())
        try:
            await asyncio.wait({connect_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
        if not connect_task.done():
            connect_task.cancel()
            await asyncio.gather(connect_task, return_exceptions=True)
            return _Outcome("stopped")
        try:
            ws = connect_task.result()
        except InvalidStatus as e:
            code = e.response.status_code
            if code in (401, 403):
                return _Outcome("auth", f"{AUTH_FAILED_MSG} (HTTP {code})")
            return _Outcome("error", f"Server rejected connection: HTTP {code}")
        except ssl.SSLCertVerificationError as e:
            return _Outcome("error", f"TLS certificate verification failed: {e.verify_message or e}")
        except (InvalidHandshake, InvalidURI) as e:
            return _Outcome("error", f"Handshake failed: {e}")
        except asyncio.TimeoutError:
            return _Outcome("error", "Connection timed out")
        except OSError as e:
            return _Outcome("error", f"Connection failed: {e.strerror or e}")

        started = time.monotonic()
        self._link_warning = None
        self._set(state=LinkState.STANDBY, live=False, connected_since=time.time())
        log.info("connected")
        # Live beats backlog: drop audio older than ~1 s and any partial frame.
        self.source.buffer.discard_older_than(s.reconnect_max_age)
        self.pipeline.reset()
        self._last_status = time.monotonic()

        sender = asyncio.create_task(self._send_loop(ws))
        receiver = asyncio.create_task(self._recv_loop(ws))
        stopper = asyncio.create_task(self._stop_event.wait())
        done, pending = await asyncio.wait({sender, receiver, stopper}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        duration = time.monotonic() - started

        if stopper in done:
            await ws.close(code=1000, reason="sender stopped")
            return _Outcome("stopped", duration=duration)

        closed: ConnectionClosed | None = None
        message: str | None = None
        for t in done:
            exc = t.exception()
            if isinstance(exc, ConnectionClosed):
                closed = exc
            elif exc is not None:
                message = f"Connection error: {exc!r}"
            elif t.result() == "watchdog":
                message = f"No status from server for {s.status_timeout:g} s — reconnecting"
        if closed is None or message:
            await ws.close()
            return _Outcome("error", message or "Connection lost", duration)
        return self._classify_close(closed, duration)

    def _classify_close(self, exc: ConnectionClosed, duration: float) -> _Outcome:
        code = exc.rcvd.code if exc.rcvd else None
        reason = exc.rcvd.reason if exc.rcvd else ""
        log.info("connection closed (code=%s reason=%r)", code, reason)
        if code == 4003:
            return _Outcome("revoked", REVOKED_MSG, duration)
        if code == 1008:
            return _Outcome("auth", AUTH_FAILED_MSG, duration)
        if code == 1003:
            return _Outcome("policy", f"Server rejected the audio format ({self.settings.sample_rate} Hz s16le mono)", duration)
        if code == 4009:
            self._link_warning = REPLACED_MSG
            return _Outcome("error", REPLACED_MSG, duration)
        if code == 4010:
            # Same long back-off as a policy rejection: retrying quickly can't help until an admin changes it.
            return _Outcome("policy", LOCAL_SOURCE_MSG, duration)
        if code == 4008:
            return _Outcome("error", "Server closed the link: no audio received for 15 s", duration)
        if code == 1009:
            return _Outcome("error", "Server rejected an oversized frame", duration)
        if code is None:
            return _Outcome("error", "Connection lost", duration)
        return _Outcome("error", f"Server closed the connection (code {code}{': ' + reason if reason else ''})", duration)

    async def _send_loop(self, ws) -> None:
        buf = self.source.buffer
        while True:
            chunks = buf.pop_all()
            if not chunks:
                await asyncio.sleep(0.02)
                continue
            for _, chunk in chunks:
                for frame in self.pipeline.process(chunk):
                    await ws.send(frame)
                    with self._lock:
                        self._snap = replace(self._snap, bytes_sent=self._snap.bytes_sent + len(frame), frames_sent=self._snap.frames_sent + 1)

    async def _recv_loop(self, ws) -> str:
        timeout = self.settings.status_timeout
        while True:
            remaining = timeout - (time.monotonic() - self._last_status)
            if remaining <= 0:
                return "watchdog"
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                continue
            if not isinstance(msg, str):
                continue
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("type") != "status":
                continue
            self._last_status = time.monotonic()
            live = bool(data.get("live"))
            campus = data.get("campus") if isinstance(data.get("campus"), str) else self._snap.campus
            self._set(live=live, campus=campus, state=LinkState.LIVE if live else LinkState.STANDBY)

    async def _audio_watchdog(self) -> None:
        """Warn (and try to reopen the device) when the capture callback stops firing."""
        stall = self.settings.audio_stall_seconds
        last_restart = 0.0
        while True:
            await asyncio.sleep(1.0)
            last = getattr(self.source, "last_callback", None)
            if not last:
                continue
            now = time.monotonic()
            if now - last > stall:
                if self._audio_warning is None:
                    log.warning("%s for %.0f s", NO_AUDIO_MSG, now - last)
                self._audio_warning = NO_AUDIO_MSG
                restart = getattr(self.source, "restart", None)
                if restart is not None and now - last_restart > 10.0:
                    last_restart = now
                    try:
                        await asyncio.to_thread(restart)
                        log.info("audio device reopened")
                    except Exception as e:
                        log.warning("could not reopen audio device: %s", e)
            elif self._audio_warning is not None:
                log.info("audio input resumed")
                self._audio_warning = None
