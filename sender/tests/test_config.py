import json
import sys

import keyring
import pytest
from pathlib import Path
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from church_sender import autostart, config
from church_sender.client import build_stream_url, normalize_server_url, validate_server_url


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError("missing")
        del self.store[(service, username)]


@pytest.fixture
def kr():
    old = keyring.get_keyring()
    mem = MemoryKeyring()
    keyring.set_keyring(mem)
    yield mem
    keyring.set_keyring(old)


TOKEN = "cs_0123456789abcdef0123456789abcdef_s3cretValue"


def test_config_round_trip_secrets_in_keyring(tmp_path, kr):
    path = tmp_path / "cfg" / "config.json"
    cfg = config.Config(server_url="wss://audio.example.com/ingest/v1/stream", device_name="Dante Virtual Soundcard",
                        device_hostapi="Core Audio", channel=17, sample_rate=24000, gain_db=4.5,
                        auto_start_stream=True, launch_at_login=True)
    config.set_token(TOKEN)
    config.set_extra_headers(cfg, {"P-Access-Token-Id": "id123", "P-Access-Token": "tok456"})
    config.save_config(cfg, path)

    raw = path.read_text()
    assert TOKEN not in raw and "tok456" not in raw and "id123" not in raw
    assert json.loads(raw)["extra_header_names"] == ["P-Access-Token-Id", "P-Access-Token"]

    loaded = config.load_config(path)
    assert loaded == cfg
    assert config.get_token() == TOKEN
    assert config.get_extra_headers(loaded) == {"P-Access-Token-Id": "id123", "P-Access-Token": "tok456"}

    config.set_extra_headers(loaded, {"P-Access-Token": "new"})
    assert (config.KEYRING_SERVICE, "header:P-Access-Token-Id") not in kr.store
    assert config.get_extra_headers(loaded) == {"P-Access-Token": "new"}
    config.set_token("")
    assert config.get_token() == ""


def test_config_defaults_and_normalisation(tmp_path, kr):
    assert config.load_config(tmp_path / "missing.json") == config.Config()
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"sample_rate": 11025, "gain_db": 99, "channel": 0, "unknown": 1}))
    cfg = config.load_config(p)
    assert cfg.sample_rate == 16000 and cfg.gain_db == 20.0 and cfg.channel == 1
    p.write_text("{not json")
    assert config.load_config(p) == config.Config()


def test_header_validation(kr):
    cfg = config.Config()
    for bad in ({"Authorization": "x"}, {"Bad Name": "x"}, {"X-Ok": "a\r\nb"}):
        with pytest.raises(ValueError):
            config.set_extra_headers(cfg, bad)


def test_url_validation_and_query():
    assert validate_server_url("wss://audio.example.com/ingest/v1/stream") is None
    assert "local network" in validate_server_url("ws://127.0.0.1:8082/ingest/v1/stream")
    for lan in ("ws://192.168.1.20:8082/ingest/v1/stream", "ws://10.0.0.5/x", "ws://captions.local/x", "ws://onevoice-server/x"):
        assert "local network" in validate_server_url(lan)
    assert validate_server_url("ws://localhost/x")
    for bad in ("ws://audio.example.com/ingest", "ftp://audio.example.com", ""):
        with pytest.raises(ValueError):
            validate_server_url(bad)
    url = build_stream_url("wss://a.example.com/ingest/v1/stream?x=1&sample_rate=8000", 16000)
    assert url == "wss://a.example.com/ingest/v1/stream?x=1&sample_rate=16000&channels=1&format=s16le"


def test_launch_agent_plist():
    import plistlib

    data = plistlib.loads(autostart.mac_plist_bytes(["/Applications/OneVoice Sender.app/Contents/MacOS/OneVoiceSender", "--minimized"]))
    assert data["Label"] == "org.onevoice.sender"
    assert data["RunAtLoad"] is True
    assert data["ProgramArguments"][-1] == "--minimized"
    assert autostart.mac_plist_path().name == "org.onevoice.sender.plist"
    cmd = autostart.launch_command(["--minimized"])
    # From source on Windows the windowless pythonw.exe is used so no console appears at login.
    expected = sys.executable
    if sys.platform == "win32" and expected.lower().endswith("python.exe"):
        expected = expected[: -len("python.exe")] + "pythonw.exe"
    assert cmd[-1] == "--minimized" and cmd[0].lower() == expected.lower()
    assert autostart.windows_command_line([r"C:\Program Files\App\app.exe", "--minimized"]) == r'"C:\Program Files\App\app.exe" --minimized'


def test_log_redaction():
    from church_sender.logsetup import redact

    assert TOKEN not in redact(f"header Authorization: Bearer {TOKEN}")
    assert "s3cret" not in redact(f"token={TOKEN}")


@pytest.mark.parametrize(
    "typed, url",
    [
        ("192.168.1.20", "ws://192.168.1.20:8082/ingest/v1/stream"),
        ("192.168.1.20:9000", "ws://192.168.1.20:9000/ingest/v1/stream"),
        ("onevoice.local", "ws://onevoice.local:8082/ingest/v1/stream"),
        ("onevoice-server", "ws://onevoice-server:8082/ingest/v1/stream"),
        ("captions.example.org", "wss://captions.example.org/ingest/v1/stream"),
        ("https://captions.example.org/", "wss://captions.example.org/ingest/v1/stream"),
        ("http://192.168.1.20:8082", "ws://192.168.1.20:8082/ingest/v1/stream"),
        ("wss://a.example.com/custom/path", "wss://a.example.com/custom/path"),
        ("  ws://10.0.0.5/x  ", "ws://10.0.0.5/x"),
    ],
)
def test_short_server_addresses_are_completed(typed, url):
    assert normalize_server_url(typed) == url
    assert build_stream_url(typed, 16000).startswith(url + "?sample_rate=16000")


def test_ui_allows_pywebview_bridge():
    """pywebview connects the page to the app with eval(); a CSP without 'unsafe-eval' leaves the UI empty."""
    html = (Path(__file__).resolve().parents[1] / "church_sender" / "ui" / "index.html").read_text()
    csp = html.split('http-equiv="Content-Security-Policy" content="', 1)[1].split('"', 1)[0]
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert "'unsafe-eval'" in script_src
