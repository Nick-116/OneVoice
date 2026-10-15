"""Desktop window: native webview (WKWebView on macOS, WebView2 on Windows) running ui/index.html.

JavaScript calls the methods of ``JsApi``; each delegates to SenderController.
Errors meant for the user are raised as UserError and shown as a toast.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config import Config
from .controller import SenderController, UserError

log = logging.getLogger(__name__)


def ui_dir() -> Path:
    # PyInstaller unpacks data files under sys._MEIPASS.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    candidate = base / "church_sender" / "ui"
    return candidate if candidate.exists() else Path(__file__).resolve().parent / "ui"


class JsApi:
    """Methods callable from JavaScript (pywebview js_api). Keep arguments JSON-simple."""

    def __init__(self, controller: SenderController, vibrant: bool) -> None:
        self._c = controller
        self._vibrant = vibrant

    def initial_state(self) -> dict:
        state = self._c.initial_state()
        state["vibrant"] = self._vibrant
        return state

    def refresh_devices(self) -> list[dict]:
        return self._c.refresh_devices()

    def poll(self) -> dict:
        return self._c.poll()

    def url_warning(self, url: str) -> dict | None:
        return self._c.url_warning(url)

    def save_settings(self, data: dict) -> dict:
        return self._c.save_settings(data)

    def set_gain(self, gain_db: float) -> None:
        self._c.set_gain(gain_db)

    def set_launch_at_login(self, enabled: bool) -> bool:
        return self._c.set_launch_at_login(enabled)

    def toggle_test(self) -> bool:
        return self._c.toggle_test()

    def start_streaming(self) -> None:
        self._c.start_streaming()

    def stop_streaming(self) -> None:
        self._c.stop_streaming()


def run_gui(cfg: Config, minimized: bool = False) -> int:
    import webview  # pywebview

    controller = SenderController(cfg)
    vibrant = sys.platform == "darwin"
    api = JsApi(controller, vibrant)
    window = webview.create_window(
        f"{APP_NAME} {__version__}",
        url=str(ui_dir() / "index.html"),
        js_api=api,
        width=1000,
        height=760,
        min_size=(760, 640),
        background_color="#120E2B",
        transparent=vibrant,
        vibrancy=vibrant,  # macOS: real translucent "glass" window
        text_select=False,
        minimized=minimized,
    )
    window.events.closing += lambda: controller.shutdown()
    webview.start(debug=False, private_mode=True)
    return 0


__all__ = ["run_gui", "JsApi", "UserError"]
