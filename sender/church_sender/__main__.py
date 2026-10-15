"""Entry point: GUI by default, ``--headless`` for service use, ``--list-devices`` for diagnostics."""

from __future__ import annotations

import argparse
import logging
import sys

from . import APP_NAME, __version__


def _list_devices() -> int:
    from .audio import list_input_devices

    try:
        devices = list_input_devices()
    except Exception as e:  # PortAudio missing, etc.
        print(f"Cannot list audio devices: {e}", file=sys.stderr)
        return 1
    if not devices:
        print("No input devices found.")
        return 0
    print(f"{'#':>3}  {'Host API':<22} {'Ch':>3} {'Rate':>6}  Name")
    for d in devices:
        print(f"{d.index:>3}  {d.hostapi:<22} {d.max_input_channels:>3} {int(d.default_samplerate):>6}  {d.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="church-sender", description=f"{APP_NAME} {__version__}")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true", help="run without GUI using the saved settings (service mode)")
    mode.add_argument("--list-devices", action="store_true", help="list audio input devices and exit")
    p.add_argument("--minimized", action="store_true", help="start the GUI minimised (used by Launch at login)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    if args.list_devices:
        return _list_devices()

    from .config import load_config
    from .logsetup import setup_logging

    log_file = setup_logging(args.log_level, to_stdout=args.headless)
    log = logging.getLogger("church_sender")
    log.info("%s %s starting (%s)%s", APP_NAME, __version__, "headless" if args.headless else "gui",
             f", log file {log_file}" if log_file else "")
    cfg = load_config()

    if args.headless:
        from .runner import run_headless

        return run_headless(cfg)

    from .webui import run_gui

    return run_gui(cfg, minimized=args.minimized)


if __name__ == "__main__":
    sys.exit(main())
