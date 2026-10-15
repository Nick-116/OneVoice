"""UI-independent sender controller: settings, input test, streaming, status.

The desktop window (webui.py) calls these methods from JavaScript through
pywebview. Secrets never travel to the UI: it only learns whether a token is
saved, never its value.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import asdict

from . import APP_NAME, __version__, autostart
from .audio import AudioCapture, InputDevice, list_input_devices
from .client import LinkState, SenderClient, normalize_server_url, validate_server_url
from .config import Config, get_extra_headers, get_token, save_config, set_extra_headers, set_token, validate_header
from .logsetup import add_handler
from .runner import ClientThread, build_client_settings

log = logging.getLogger(__name__)
SUPPORTED_RATES = (16000, 24000, 48000)


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__(logging.INFO)
        self.q = q
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


class UserError(Exception):
    """A problem to show to the user as-is."""


class SenderController:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.devices: list[InputDevice] = []
        self.capture: AudioCapture | None = None
        self.client: SenderClient | None = None
        self.thread: ClientThread | None = None
        self.testing = False
        self.headers = get_extra_headers(cfg)
        self.lock = threading.RLock()
        self.logs: queue.Queue[str] = queue.Queue(maxsize=2000)
        add_handler(_QueueHandler(self.logs))

    # ------------------------------------------------------------ state for the UI
    def refresh_devices(self) -> list[dict]:
        try:
            self.devices = list_input_devices()
        except Exception as e:
            log.error("cannot list audio devices: %s", e)
            self.devices = []
        return [self._device_json(d) for d in self.devices]

    @staticmethod
    def _device_json(d: InputDevice) -> dict:
        return {
            "key": f"{d.hostapi}::{d.name}",
            "name": d.name,
            "hostapi": d.hostapi,
            "channels": d.max_input_channels,
            "rate": int(d.default_samplerate),
        }

    def initial_state(self) -> dict:
        devices = self.refresh_devices()
        c = self.cfg
        return {
            "app": {"name": APP_NAME, "version": __version__},
            "devices": devices,
            "config": {
                "server_url": c.server_url,
                "device_key": f"{c.device_hostapi}::{c.device_name}" if c.device_name else "",
                "channel": c.channel,
                "sample_rate": c.sample_rate,
                "gain_db": c.gain_db,
                "auto_start_stream": c.auto_start_stream,
                "launch_at_login": c.launch_at_login,
                "header_names": list(self.headers),
            },
            "has_token": bool(get_token()),
            "autostart_supported": autostart.is_supported(),
            "should_autostart": bool(c.auto_start_stream and get_token() and c.server_url and c.device_name),
        }

    def poll(self) -> dict:
        """Called ~10x per second by the UI: link status, levels and new log lines."""
        lines: list[str] = []
        while len(lines) < 200:
            try:
                lines.append(self.logs.get_nowait())
            except queue.Empty:
                break
        levels = None
        cap = self.capture
        if cap is not None:
            lv = cap.meter.read(self.cfg.gain_db)
            if lv is not None:
                levels = {"rms": round(lv.rms_db, 1), "peak": round(lv.peak_db, 1), "clipped": bool(lv.clipped)}
        status: dict = {"state": "stopped", "streaming": self.client is not None, "testing": self.testing}
        if self.client is not None:
            s = self.client.snapshot()
            status.update({k: v for k, v in asdict(s).items() if k != "state"})
            status["state"] = s.state.value
            if s.state == LinkState.REVOKED and self.thread is not None and not self.thread.is_alive():
                self.stop_streaming()
                status["state"] = "revoked"
        return {"status": status, "levels": levels, "capturing": cap is not None, "log": lines, "now": time.time()}

    # ------------------------------------------------------------ settings
    def _device(self, key: str) -> InputDevice | None:
        for d in self.devices:
            if f"{d.hostapi}::{d.name}" == key:
                return d
        return None

    def save_settings(self, data: dict) -> dict:
        with self.lock:
            url = str(data.get("server_url", "")).strip()
            if url:
                try:
                    validate_server_url(url)
                except ValueError as e:
                    raise UserError(str(e)) from e
            key = str(data.get("device_key", ""))
            device = self._device(key)
            if key and device is None:
                self.refresh_devices()  # list may be stale (device plugged in after start)
                device = self._device(key)
            try:
                rate = int(data.get("sample_rate") or 16000)
                channel = int(data.get("channel") or 1)
                gain = float(data.get("gain_db") or 0.0)
            except (TypeError, ValueError) as e:
                raise UserError("Invalid number in settings") from e
            if rate not in SUPPORTED_RATES:
                raise UserError("Unsupported sample rate")
            if device and not 1 <= channel <= device.max_input_channels:
                raise UserError(f"{device.name} has {device.max_input_channels} input channel(s)")
            headers = data.get("headers")
            if headers is not None:
                if not isinstance(headers, dict):
                    raise UserError("Invalid headers")
                clean: dict[str, str] = {}
                for k, v in headers.items():
                    k, v = str(k).strip(), str(v)
                    if not k:
                        continue
                    if not v and k in self.headers:
                        v = self.headers[k]  # blank value = keep the saved secret
                    try:
                        validate_header(k, v)
                    except ValueError as e:
                        raise UserError(str(e)) from e
                    clean[k] = v
            cfg = Config(
                server_url=url,
                device_name=device.name if device else self.cfg.device_name,
                device_hostapi=device.hostapi if device else self.cfg.device_hostapi,
                channel=channel,
                sample_rate=rate,
                gain_db=round(gain * 2) / 2,
                auto_start_stream=bool(data.get("auto_start_stream")),
                launch_at_login=self.cfg.launch_at_login,
                extra_header_names=list(self.cfg.extra_header_names),
            ).normalise()
            token = str(data.get("token") or "").strip()
            try:
                if token:
                    set_token(token)
                if headers is not None:
                    set_extra_headers(cfg, clean)
                    self.headers = clean
                save_config(cfg)
            except Exception as e:
                raise UserError(f"Could not save settings: {e}") from e
            self.cfg = cfg
            if self.client is not None:
                self.client.set_gain_db(cfg.gain_db)
            log.info("settings saved")
            return {"has_token": bool(get_token()), "header_names": list(self.headers)}

    def set_gain(self, gain_db: float) -> None:
        self.cfg.gain_db = max(-20.0, min(20.0, round(float(gain_db) * 2) / 2))
        if self.client is not None:
            self.client.set_gain_db(self.cfg.gain_db)

    def set_launch_at_login(self, enabled: bool) -> bool:
        try:
            autostart.set_enabled(bool(enabled))
        except Exception as e:
            raise UserError(f"Could not update the login item: {e}") from e
        self.cfg.launch_at_login = bool(enabled)
        save_config(self.cfg)
        return self.cfg.launch_at_login

    # ------------------------------------------------------------ audio
    def _open_capture(self) -> AudioCapture:
        device = self._device(f"{self.cfg.device_hostapi}::{self.cfg.device_name}")
        if device is None:
            raise UserError("Select an input device first, then save.")
        try:
            cap = AudioCapture(device, self.cfg.channel)
            cap.start()
        except Exception as e:
            raise UserError(f"Cannot open {device.name}: {e}") from e
        return cap

    def _close_capture(self) -> None:
        if self.capture is not None:
            self.capture.stop()
            self.capture = None

    def toggle_test(self) -> bool:
        with self.lock:
            if self.client is not None:
                return False
            if self.testing:
                self.testing = False
                self._close_capture()
                return False
            self.capture = self._open_capture()
            self.testing = True
            return True

    # ------------------------------------------------------------ streaming
    def start_streaming(self) -> None:
        with self.lock:
            if self.client is not None:
                return
            try:
                settings = build_client_settings(self.cfg, headers=dict(self.headers))
            except ValueError as e:
                raise UserError(str(e)) from e
            self.testing = False
            self._close_capture()
            self.capture = self._open_capture()
            self.client = SenderClient(settings, self.capture)
            self.thread = ClientThread(self.client)
            self.thread.start()
            log.info("streaming started")

    def stop_streaming(self) -> None:
        with self.lock:
            if self.thread is not None:
                self.thread.stop()
            self.thread = None
            self.client = None
            self._close_capture()
            log.info("streaming stopped")

    def shutdown(self) -> None:
        try:
            self.stop_streaming()
        finally:
            self._close_capture()

    @staticmethod
    def url_warning(url: str) -> dict | None:
        """Hint under the address field: where the app will connect, or what is wrong."""
        if not (url or "").strip():
            return None
        try:
            warning = validate_server_url(url)
        except ValueError as e:
            return {"text": str(e), "warn": True}
        text = f"Connects to {normalize_server_url(url)}"
        if warning:
            text += " (unencrypted; fine on your local network)"
        return {"text": text, "warn": False}
