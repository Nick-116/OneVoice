"""Launcher script (used by PyInstaller and by the "Launch at login" entry when running from source)."""

import sys

from church_sender.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
