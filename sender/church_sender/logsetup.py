"""Logging: rotating file in the platform log dir (+ stdout in headless mode). Secrets are redacted."""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"cs_[0-9a-fA-F]{32}_\S+"), "cs_[REDACTED]"),
]
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    """Belt and braces: the token is never logged on purpose, but scrub anything token-shaped."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def add_handler(handler: logging.Handler, level: int = logging.INFO) -> logging.Handler:
    handler.addFilter(RedactFilter())
    handler.setLevel(level)
    if handler.formatter is None:
        handler.setFormatter(logging.Formatter(FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


def setup_logging(level: str = "INFO", to_stdout: bool = False, directory: Path | None = None) -> Path | None:
    from .config import log_dir

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # websockets debug logs include handshake headers: keep them quiet.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    path: Path | None = None
    try:
        d = directory or log_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / "sender.log"
        add_handler(logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"), root.level)
    except OSError as e:
        print(f"warning: cannot write log file: {e}", file=sys.stderr)
    if to_stdout and sys.stdout is not None:
        add_handler(logging.StreamHandler(sys.stdout), root.level)
    return path
