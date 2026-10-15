"""Launch at login: a per-user LaunchAgent on macOS, an HKCU Run entry on Windows."""

from __future__ import annotations

import logging
import plistlib
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LABEL = "org.onevoice.sender"
WINDOWS_VALUE_NAME = "OneVoiceSender"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_supported() -> bool:
    return sys.platform == "darwin" or sys.platform == "win32"


def launch_command(extra_args: list[str] | None = None) -> list[str]:
    """Command that starts this app: the frozen executable, or the interpreter + run_sender.py."""
    args = list(extra_args or [])
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    python = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = python.with_name("pythonw.exe")  # no console window at login
        if pythonw.exists():
            python = pythonw
    script = Path(__file__).resolve().parent.parent / "run_sender.py"
    return [str(python), str(script), *args]


# ---------------------------------------------------------------- macOS


def mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def mac_plist_bytes(command: list[str]) -> bytes:
    from .config import log_dir

    logs = log_dir()
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": command,
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
            "StandardOutPath": str(logs / "launchagent.out.log"),
            "StandardErrorPath": str(logs / "launchagent.err.log"),
        }
    )


def _mac_enable(command: list[str]) -> None:
    from .config import log_dir

    log_dir().mkdir(parents=True, exist_ok=True)
    path = mac_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mac_plist_bytes(command))
    log.info("installed LaunchAgent %s", path)


def _mac_disable() -> None:
    path = mac_plist_path()
    if path.exists():
        # Unload quietly in case it was loaded manually; it is fine if this fails.
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
        path.unlink()
        log.info("removed LaunchAgent %s", path)


# ---------------------------------------------------------------- Windows


def windows_command_line(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _win_enable(command: list[str]) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, WINDOWS_VALUE_NAME, 0, winreg.REG_SZ, windows_command_line(command))
    log.info("added HKCU Run entry %s", WINDOWS_VALUE_NAME)


def _win_disable() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, WINDOWS_VALUE_NAME)
        log.info("removed HKCU Run entry %s", WINDOWS_VALUE_NAME)
    except FileNotFoundError:
        pass


def _win_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, WINDOWS_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------- public


def is_enabled() -> bool:
    if sys.platform == "darwin":
        return mac_plist_path().exists()
    if sys.platform == "win32":
        return _win_enabled()
    return False


def set_enabled(enabled: bool, extra_args: list[str] | None = None) -> None:
    """Install/remove the login item. GUI launches pass ``--minimized``; service setups may pass ``--headless``."""
    if not is_supported():
        raise NotImplementedError("Launch at login is only supported on macOS and Windows")
    command = launch_command(extra_args if extra_args is not None else ["--minimized"])
    if sys.platform == "darwin":
        _mac_enable(command) if enabled else _mac_disable()
    else:
        _win_enable(command) if enabled else _win_disable()
