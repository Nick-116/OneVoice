"""Keyring backend for machines without a desktop keychain (the Raspberry Pi appliance).

Secrets live in one JSON file readable only by the service user (mode 0600),
next to the config but never inside it.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class FileKeyring(KeyringBackend):
    priority = 1  # only used when installed explicitly

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def _write(self, data: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".secrets-")
        try:
            if hasattr(os, "fchmod"):  # POSIX; mkstemp already creates the file 0600
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get_password(self, service: str, username: str) -> str | None:
        with self._lock:
            return self._read().get(service, {}).get(username)

    def set_password(self, service: str, username: str, password: str) -> None:
        with self._lock:
            data = self._read()
            data.setdefault(service, {})[username] = password
            self._write(data)

    def delete_password(self, service: str, username: str) -> None:
        with self._lock:
            data = self._read()
            if username not in data.get(service, {}):
                raise PasswordDeleteError(username)
            del data[service][username]
            self._write(data)
