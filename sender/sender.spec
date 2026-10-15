# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Church Audio Sender.
#   macOS:   pyinstaller --noconfirm --clean sender.spec  ->  dist/Church Audio Sender.app
#   Windows: pyinstaller --noconfirm --clean sender.spec  ->  dist\ChurchAudioSender\ChurchAudioSender.exe
#                                                             (+ ChurchAudioSender-cli.exe for --headless / --list-devices)
# Build on each target OS (PyInstaller does not cross-compile).
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

VERSION = "1.0.0"
NAME = "ChurchAudioSender"

hiddenimports = (
    collect_submodules("keyring.backends")
    + collect_submodules("soxr")
    + collect_submodules("websockets")
    + ["church_sender.gui"]
)
if sys.platform == "win32":
    hiddenimports += ["win32ctypes.core"]

a = Analysis(
    ["run_sender.py"],
    pathex=["."],
    datas=collect_data_files("certifi"),
    hiddenimports=hiddenimports,
    excludes=["pytest", "pytest_asyncio"],
    noarchive=False,
)
pyz = PYZ(a.pure)

gui_exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,            # windowed GUI app; logs go to the log file
    disable_windowed_traceback=False,
    upx=False,
    icon=None,                # add an .icns / .ico here if you have one
)
executables = [gui_exe]

if sys.platform == "win32":
    # Console twin for services / troubleshooting (stdout visible).
    executables.append(EXE(pyz, a.scripts, [], exclude_binaries=True, name=f"{NAME}-cli", console=True, upx=False))

coll = COLLECT(*executables, a.binaries, a.datas, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Church Audio Sender.app",
        bundle_identifier="church.captions.sender",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSMicrophoneUsageDescription": "Church Audio Sender captures the speech mix from your Dante / audio interface to produce live captions.",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
