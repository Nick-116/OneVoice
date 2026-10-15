"""Build the desktop app with PyInstaller: ``python build.py`` (run on the target OS)."""

import sys
from pathlib import Path

import PyInstaller.__main__

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    PyInstaller.__main__.run([str(here / "sender.spec"), "--noconfirm", "--clean",
                              "--distpath", str(here / "dist"), "--workpath", str(here / "build")])
    print("\nBuilt:", here / "dist" / ("Church Audio Sender.app" if sys.platform == "darwin" else "ChurchAudioSender"))
