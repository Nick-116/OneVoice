# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for OneVoice Sender.
#   macOS:   pyinstaller --noconfirm --clean sender.spec  ->  dist/OneVoice Sender.app
#   Windows: pyinstaller --noconfirm --clean sender.spec  ->  dist\OneVoiceSender\OneVoiceSender.exe
#                                                             (+ OneVoiceSender-cli.exe for --headless / --list-devices)
# Build on each target OS (PyInstaller does not cross-compile). CI builds both: .github/workflows/release.yml
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

VERSION = os.environ.get("ONEVOICE_VERSION", "1.3.0")
NAME = "OneVoiceSender"

hiddenimports = (
    collect_submodules("keyring.backends")
    + collect_submodules("soxr")
    + collect_submodules("websockets")
    + collect_submodules("webview")
    + ["church_sender.webui", "church_sender.controller"]
)
# Note: don't force win32ctypes/clr here. Importing win32ctypes early makes it pick its cffi
# backend, which PyInstaller deliberately blocks on Windows (build fails with
# "import of cffi halted"). keyring and pywebview's Windows backend pull them in normally.

datas = collect_data_files("certifi") + collect_data_files("webview") + [("church_sender/ui", "church_sender/ui")]

a = Analysis(
    ["run_sender.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "pytest_asyncio", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = "assets/OneVoice.icns" if sys.platform == "darwin" else "assets/OneVoice.ico"
gui_exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,            # windowed GUI app; logs go to the log file
    disable_windowed_traceback=False,
    upx=False,
    icon=icon,
    codesign_identity=os.environ.get("MACOS_SIGN_IDENTITY") or None,
    entitlements_file="assets/entitlements.plist" if sys.platform == "darwin" else None,
)
executables = [gui_exe]

if sys.platform == "win32":
    # Console twin for services / troubleshooting (stdout visible).
    executables.append(EXE(pyz, a.scripts, [], exclude_binaries=True, name=f"{NAME}-cli", console=True, upx=False, icon=icon))

coll = COLLECT(*executables, a.binaries, a.datas, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OneVoice Sender.app",
        icon="assets/OneVoice.icns",
        bundle_identifier="org.onevoice.sender",
        version=VERSION,
        info_plist={
            "CFBundleName": "OneVoice Sender",
            "CFBundleDisplayName": "OneVoice Sender",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSMicrophoneUsageDescription": "OneVoice Sender captures the speech mix from your Dante / audio interface to produce live captions.",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "11.0",
        },
    )
