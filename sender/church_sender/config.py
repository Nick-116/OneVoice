"""Settings: non-secret values in a JSON file (platformdirs), secrets in the OS keyring.

The sender token and every extra-header *value* live only in the macOS
Keychain / Windows Credential Manager. The JSON file stores header *names*.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import keyring
import keyring.errors
import platformdirs

from .audio import SUPPORTED_RATES

log = logging.getLogger(__name__)

APP_DIR_NAME = "ChurchCaptionsSender"
APP_AUTHOR = "ChurchCaptions"
KEYRING_SERVICE = "church-captions-sender"
TOKEN_KEY = "sender-token"
HEADER_KEY_PREFIX = "header:"

_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_RESERVED_HEADERS = {
    "authorization", "host", "connection", "upgrade", "content-length", "transfer-encoding",
    "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol",
}


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_DIR_NAME, APP_AUTHOR, roaming=False))


def log_dir() -> Path:
    return Path(platformdirs.user_log_dir(APP_DIR_NAME, APP_AUTHOR))


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class Config:
    server_url: str = ""
    device_name: str = ""
    device_hostapi: str = ""
    channel: int = 1
    sample_rate: int = 16000
    gain_db: float = 0.0
    auto_start_stream: bool = False
    launch_at_login: bool = False
    extra_header_names: list[str] = field(default_factory=list)

    def normalise(self) -> "Config":
        self.server_url = str(self.server_url or "").strip()
        self.channel = max(1, int(self.channel or 1))
        self.sample_rate = int(self.sample_rate) if int(self.sample_rate or 0) in SUPPORTED_RATES else 16000
        self.gain_db = max(-20.0, min(20.0, float(self.gain_db or 0.0)))
        self.auto_start_stream = bool(self.auto_start_stream)
        self.launch_at_login = bool(self.launch_at_login)
        names: list[str] = []
        for n in self.extra_header_names or []:
            if isinstance(n, str) and n and n not in names:
                names.append(n)
        self.extra_header_names = names
        return self


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    except (OSError, ValueError):
        log.exception("config file unreadable, using defaults: %s", path)
        return Config()
    known = {f.name for f in fields(Config)}
    cfg = Config(**{k: v for k, v in raw.items() if k in known})
    try:
        return cfg.normalise()
    except (TypeError, ValueError):
        log.warning("invalid values in config file, using defaults")
        return Config()


def save_config(cfg: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(asdict(cfg.normalise()), indent=2)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


# ---------------------------------------------------------------- secrets


def get_token() -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, TOKEN_KEY) or ""
    except Exception:
        log.exception("could not read sender token from keyring")
        return ""


def set_token(token: str) -> None:
    token = (token or "").strip()
    if token:
        _store_secret(TOKEN_KEY, token)
    else:
        _delete_secret(TOKEN_KEY)


def _store_secret(key: str, value: str) -> None:
    """Write a keyring secret, tolerating items another program created.

    macOS refuses to modify a Keychain item owned by a different binary
    (errSecInvalidOwnerEdit, -25244), e.g. one saved by a source checkout and
    then edited by the packaged app. Unchanged values are not rewritten; on
    failure the item is deleted and recreated so this app owns it.
    """
    try:
        if keyring.get_password(KEYRING_SERVICE, key) == value:
            return
    except Exception:
        pass
    try:
        keyring.set_password(KEYRING_SERVICE, key, value)
        return
    except Exception as first:
        log.warning("keyring write failed (%s); recreating the entry", first)
    _delete_secret(key)
    keyring.set_password(KEYRING_SERVICE, key, value)


def _delete_secret(key: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        log.exception("could not delete keyring entry")


def validate_header(name: str, value: str) -> None:
    if not _HEADER_NAME_RE.match(name or ""):
        raise ValueError(f"Invalid header name: {name!r}")
    if name.lower() in _RESERVED_HEADERS:
        raise ValueError(f"Header {name!r} cannot be overridden")
    if any(c in (value or "") for c in "\r\n\0"):
        raise ValueError(f"Invalid characters in value of header {name!r}")


def get_extra_headers(cfg: Config) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name in cfg.extra_header_names:
        try:
            value = keyring.get_password(KEYRING_SERVICE, HEADER_KEY_PREFIX + name)
        except Exception:
            log.exception("could not read header %s from keyring", name)
            value = None
        if value is not None:
            headers[name] = value
    return headers


def set_extra_headers(cfg: Config, headers: dict[str, str]) -> None:
    """Store header values in the keyring, record names in ``cfg`` (caller saves cfg)."""
    for name, value in headers.items():
        validate_header(name, value)
    for old in cfg.extra_header_names:
        if old not in headers:
            _delete_secret(HEADER_KEY_PREFIX + old)
    for name, value in headers.items():
        _store_secret(HEADER_KEY_PREFIX + name, value)
    cfg.extra_header_names = list(headers)
