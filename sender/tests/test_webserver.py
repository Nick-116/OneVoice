"""Raspberry Pi web interface: sign-in, cross-site protection, API, file keyring."""

import http.client
import json
import os
import stat
import threading
from http.server import ThreadingHTTPServer

import pytest

from church_sender import webserver
from church_sender.filekeyring import FileKeyring
from church_sender.webserver import WebSender, make_handler
from church_sender.webui import ui_dir

from test_config import kr  # noqa: F401
from test_controller import TOKEN, ctl  # noqa: F401


@pytest.fixture
def server(ctl):  # noqa: F811
    app = WebSender(ctl, lambda u, p: (u, p) == ("pastor", "right-password"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, ui_dir()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield app, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def req(port, method, path, body=None, headers=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Content-Type": "application/json", "X-OneVoice": "1", "Host": f"127.0.0.1:{port}"}
    h.update(headers or {})
    if cookie:
        h["Cookie"] = cookie
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = conn.getresponse()
    data = r.read()
    return r, data


def login(port, user="pastor", pw="right-password"):
    r, _ = req(port, "POST", "/login", {"username": user, "password": pw})
    assert r.status == 200
    return r.getheader("Set-Cookie").split(";", 1)[0]


def test_page_requires_sign_in(server):
    _, port = server
    r, _ = req(port, "GET", "/")
    assert r.status == 303 and r.getheader("Location") == "/login"
    r, body = req(port, "GET", "/login")
    assert r.status == 200 and b"Sign in" in body
    assert "frame-ancestors 'none'" in r.getheader("Content-Security-Policy")


def test_sign_in_serves_the_app_in_http_mode(server):
    _, port = server
    cookie = login(port)
    assert "HttpOnly" in req(port, "POST", "/login", {"username": "pastor", "password": "right-password"})[0].getheader("Set-Cookie")
    r, body = req(port, "GET", "/", cookie=cookie)
    assert r.status == 200 and b'name="onevoice-backend" content="http"' in body


def test_wrong_password_and_lockout(server, monkeypatch):
    app, port = server
    monkeypatch.setattr(webserver.time, "sleep", lambda s: None)
    for _ in range(webserver.LOCKOUT_FAILURES):
        r, _ = req(port, "POST", "/login", {"username": "pastor", "password": "nope"})
        assert r.status == 401
    r, _ = req(port, "POST", "/login", {"username": "pastor", "password": "right-password"})
    assert r.status == 401  # locked out even with the right password


def test_api_needs_a_session(server):
    _, port = server
    r, _ = req(port, "POST", "/api/initial_state", {"args": []})
    assert r.status == 401


def test_cross_site_requests_are_refused(server):
    _, port = server
    cookie = login(port)
    r, _ = req(port, "POST", "/api/stop_streaming", {"args": []}, headers={"X-OneVoice": ""}, cookie=cookie)
    assert r.status == 403
    r, _ = req(port, "POST", "/api/stop_streaming", {"args": []}, headers={"Origin": "http://evil.example"}, cookie=cookie)
    assert r.status == 403


def test_api_initial_state_and_errors(server):
    app, port = server
    cookie = login(port)
    r, body = req(port, "POST", "/api/initial_state", {"args": []}, cookie=cookie)
    state = json.loads(body)["result"]
    assert r.status == 200 and state["web"] is True and state["should_autostart"] is False
    assert len(state["devices"]) == 2
    r, body = req(port, "POST", "/api/save_settings", {"args": [{"sample_rate": 44100}]}, cookie=cookie)
    assert r.status == 400 and "sample rate" in json.loads(body)["error"].lower()
    r, _ = req(port, "POST", "/api/shutdown", {"args": []}, cookie=cookie)
    assert r.status == 404  # only the UI's methods are exposed
    r, body = req(port, "POST", "/api/save_settings", {"args": [{"server_url": "192.168.1.20", "token": TOKEN}]}, cookie=cookie)
    assert r.status == 200 and TOKEN not in body.decode()


def test_stop_from_the_page_pauses_autostart(server):
    app, port = server
    cookie = login(port)
    req(port, "POST", "/api/stop_streaming", {"args": []}, cookie=cookie)
    assert app.user_stopped is True


def test_sign_out(server):
    _, port = server
    cookie = login(port)
    req(port, "POST", "/logout", {}, cookie=cookie)
    r, _ = req(port, "POST", "/api/poll", {"args": []}, cookie=cookie)
    assert r.status == 401


def test_static_files_are_whitelisted(server):
    _, port = server
    assert req(port, "GET", "/app.js")[0].status == 200
    assert req(port, "GET", "/../config.py")[0].status == 404
    assert req(port, "GET", "/webserver.py")[0].status == 404


def test_file_keyring_is_private(tmp_path):
    path = tmp_path / "secrets.json"
    k = FileKeyring(path)
    k.set_password("onevoice-sender", "sender-token", TOKEN)
    assert FileKeyring(path).get_password("onevoice-sender", "sender-token") == TOKEN
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    k.delete_password("onevoice-sender", "sender-token")
    assert k.get_password("onevoice-sender", "sender-token") is None
