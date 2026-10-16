"""Web mode for the Raspberry Pi appliance: the same UI as the desktop app, served over HTTP.

The browser talks to SenderController through POST /api/<method>, which mirrors
the desktop JsApi. Streaming runs in this process and starts at boot on its
own; the web page is only for setup and monitoring.

Sign-in uses the Pi's own account (the username and password set in Raspberry
Pi Imager), checked against /etc/shadow. Only members of ONEVOICE_LOGIN_GROUP (default
"sudo") may sign in. Sessions are in memory, so a restart signs everyone out.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import os
import secrets
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import APP_NAME, __version__
from .config import Config, config_path, save_config
from .controller import SenderController, UserError
from .webui import ui_dir

log = logging.getLogger(__name__)

SESSION_COOKIE = "ov_session"
SESSION_TTL = 12 * 3600
MAX_BODY = 64 * 1024
LOCKOUT_FAILURES = 10
LOCKOUT_SECONDS = 300
AUTOSTART_RETRY = 5.0
STATIC_FILES = {"app.css", "app.js", "icon.svg", "login.js"}
API_METHODS = {
    "initial_state", "refresh_devices", "poll", "url_warning", "save_settings",
    "set_gain", "toggle_test", "start_streaming", "stop_streaming",
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

Authenticator = Callable[[str, str], bool]


def system_authenticator(group: str) -> Authenticator:
    """Check a Linux account password against /etc/shadow; the user must be in ``group``.

    The service user is in the ``shadow`` group (read-only access). PAM can't be used:
    for a non-root caller it only verifies the caller's own password.
    """
    import grp
    import pwd
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # crypt/spwd: fine on Python 3.11 (Bookworm)
        import crypt
        import spwd

    def check(username: str, password: str) -> bool:
        try:
            user = pwd.getpwnam(username)
            g = grp.getgrnam(group)
            stored = spwd.getspnam(username).sp_pwdp
        except (KeyError, PermissionError):
            return False
        if user.pw_uid == 0 or (username not in g.gr_mem and user.pw_gid != g.gr_gid):
            return False
        if not stored or stored[0] in "!*":  # locked or no password
            return False
        return hmac.compare_digest(crypt.crypt(password, stored) or "", stored)

    return check


class WebSender:
    """Controller plus sessions, login throttling and the boot-time autostart loop."""

    def __init__(self, controller: SenderController, authenticate: Authenticator) -> None:
        self.c = controller
        self.authenticate = authenticate
        self.sessions: dict[str, float] = {}
        self.failures: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()
        self.user_stopped = False
        self._stop = threading.Event()

    # ------------------------------------------------------------ sessions
    def login(self, ip: str, username: str, password: str) -> str | None:
        with self.lock:
            count, since = self.failures.get(ip, (0, 0.0))
            if count >= LOCKOUT_FAILURES and time.time() - since < LOCKOUT_SECONDS:
                return None
        ok = bool(username) and bool(password) and self.authenticate(username, password)
        with self.lock:
            if not ok:
                count, since = self.failures.get(ip, (0, time.time()))
                if time.time() - since > LOCKOUT_SECONDS:
                    count, since = 0, time.time()
                self.failures[ip] = (count + 1, since)
                log.warning("web sign-in failed for %r from %s", username, ip)
                return None
            self.failures.pop(ip, None)
            sid = secrets.token_urlsafe(32)
            self.sessions[sid] = time.time() + SESSION_TTL
            log.info("web sign-in: %s from %s", username, ip)
            return sid

    def valid(self, sid: str | None) -> bool:
        if not sid:
            return False
        with self.lock:
            now = time.time()
            for k in [k for k, exp in self.sessions.items() if exp < now]:
                del self.sessions[k]
            return any(hmac.compare_digest(sid, k) for k in self.sessions)

    def logout(self, sid: str | None) -> None:
        with self.lock:
            self.sessions.pop(sid or "", None)

    # ------------------------------------------------------------ API
    def call(self, method: str, args: list) -> object:
        if method == "initial_state":
            state = self.c.initial_state()
            # The Pi streams on its own from boot; the page must not start it again.
            state.update(web=True, should_autostart=False, autostart_supported=False, vibrant=False)
            return state
        if method == "stop_streaming":
            self.user_stopped = True
        elif method == "start_streaming":
            self.user_stopped = False
        return getattr(self.c, method)(*args)

    # ------------------------------------------------------------ autostart
    def autostart_loop(self) -> None:
        """Start streaming at boot, and again whenever it isn't running (e.g. USB input plugged in late)."""
        last_error = ""
        while not self._stop.wait(AUTOSTART_RETRY):
            cfg = self.c.cfg
            if self.user_stopped or not cfg.auto_start_stream or self.c.client is not None or self.c.testing:
                continue
            if not (cfg.server_url and cfg.device_name):
                continue
            try:
                self.c.start_streaming()
                last_error = ""
            except Exception as e:
                if str(e) != last_error:
                    log.warning("autostart: %s", e)
                    last_error = str(e)

    def stop(self) -> None:
        self._stop.set()


def make_handler(app: WebSender, static_dir: Path) -> type[BaseHTTPRequestHandler]:
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    index_html = index_html.replace("<head>", '<head>\n  <meta name="onevoice-backend" content="http" />', 1)
    login_html = (static_dir / "login.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = "OneVoiceSender"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:  # quiet: poll runs 10x per second
            pass

        # -------------------------------------------------------- helpers
        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, data: object, extra: dict[str, str] | None = None) -> None:
            self._send(status, json.dumps(data).encode(), "application/json", extra)

        def _redirect(self, to: str) -> None:
            self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", {"Location": to})

        def _sid(self) -> str | None:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else None

        def _same_origin(self) -> bool:
            """POSTs need our custom header (no cross-site form can send it) and a matching Origin."""
            if self.headers.get("X-OneVoice") != "1":
                return False
            origin = self.headers.get("Origin")
            return origin is None or urlsplit(origin).netloc == self.headers.get("Host", "")

        def _body(self) -> dict | None:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if n > MAX_BODY:
                return None
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return None
            return data if isinstance(data, dict) else None

        # -------------------------------------------------------- routes
        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz":
                return self._send(200, b"ok", "text/plain")
            if path == "/login":
                return self._send(200, login_html.encode(), "text/html; charset=utf-8")
            name = path.lstrip("/")
            if name in STATIC_FILES:
                ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
                return self._send(200, (static_dir / name).read_bytes(), ctype)
            if path in ("/", "/index.html"):
                if not app.valid(self._sid()):
                    return self._redirect("/login")
                return self._send(200, index_html.encode(), "text/html; charset=utf-8")
            self._send(404, b"Not found", "text/plain")

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if not self._same_origin():
                return self._json(403, {"error": "Forbidden"})
            body = self._body()
            if body is None:
                return self._json(400, {"error": "Invalid request"})
            if path == "/login":
                sid = app.login(self.client_address[0], str(body.get("username", "")), str(body.get("password", "")))
                if not sid:
                    time.sleep(1)
                    return self._json(401, {"error": "Wrong username or password"})
                cookie = f"{SESSION_COOKIE}={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
                return self._json(200, {"ok": True}, {"Set-Cookie": cookie})
            if not app.valid(self._sid()):
                return self._json(401, {"error": "Signed out. Reload the page to sign in again."})
            if path == "/logout":
                app.logout(self._sid())
                return self._json(200, {"ok": True}, {"Set-Cookie": f"{SESSION_COOKIE}=; Path=/; Max-Age=0"})
            if path.startswith("/api/"):
                method = path[len("/api/"):]
                args = body.get("args", [])
                if method not in API_METHODS or not isinstance(args, list):
                    return self._json(404, {"error": "Not found"})
                try:
                    return self._json(200, {"result": app.call(method, args)})
                except UserError as e:
                    return self._json(400, {"error": str(e)})
                except Exception:
                    log.exception("web api %s failed", method)
                    return self._json(500, {"error": "Something went wrong (see the log)"})
            self._json(404, {"error": "Not found"})

    return Handler


def run_web(cfg: Config, host: str = "0.0.0.0", port: int = 80, authenticate: Authenticator | None = None) -> int:
    if not config_path().exists():
        cfg.auto_start_stream = True  # an appliance should stream after every boot
        save_config(cfg)
    controller = SenderController(cfg)
    auth = authenticate or system_authenticator(os.environ.get("ONEVOICE_LOGIN_GROUP", "sudo"))
    app = WebSender(controller, auth)
    threading.Thread(target=app.autostart_loop, name="autostart", daemon=True).start()
    server = ThreadingHTTPServer((host, port), make_handler(app, ui_dir()))
    server.daemon_threads = True
    log.info("%s %s web interface on http://%s:%d", APP_NAME, __version__, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        server.server_close()
        controller.shutdown()
    return 0


__all__ = ["run_web", "WebSender", "make_handler", "system_authenticator"]
