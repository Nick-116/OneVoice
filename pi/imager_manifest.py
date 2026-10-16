"""Write a Raspberry Pi Imager repository file (onevoice-imager.json) for the OneVoice Sender image.

Imager 2 only offers "Edit settings" (username, password, Wi-Fi) for images whose
listing says how they're customised. A file picked with "Use custom" has no
listing, so the settings are greyed out. Pointing Imager at this file fixes that.

Usage: python3 pi/imager_manifest.py IMAGE.img.xz VERSION OUT.json
"""

from __future__ import annotations

import datetime
import hashlib
import json
import lzma
import os
import sys
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "Nick-116/OneVoice")
OFFICIAL_LIST = "https://downloads.raspberrypi.com/os_list_imagingutility_v4.json"
DEVICE_TAGS = ["pi5-64bit", "pi4-64bit", "pi3-64bit"]
ICON = f"https://raw.githubusercontent.com/{REPO}/main/sender/assets/icon-256.png"


def sha256_and_size(chunks) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    for c in chunks:
        h.update(c)
        n += len(c)
    return h.hexdigest(), n


def read_chunks(f, size=1 << 20):
    while chunk := f.read(size):
        yield chunk


def main(image: str, version: str, out: str) -> None:
    with open(image, "rb") as f:
        dl_sha, dl_size = sha256_and_size(read_chunks(f))
    with lzma.open(image, "rb") as f:
        ex_sha, ex_size = sha256_and_size(read_chunks(f))

    with urllib.request.urlopen(OFFICIAL_LIST, timeout=60) as r:
        official = json.load(r)
    devices = [d for d in official["imager"]["devices"] if set(d.get("tags") or []) & set(DEVICE_TAGS)]

    name = os.path.basename(image)
    manifest = {
        "imager": {"latest_version": official["imager"].get("latest_version", ""), "url": official["imager"].get("url", ""), "devices": devices},
        "os_list": [
            {
                "name": f"OneVoice Sender {version}",
                "description": "Streams a USB audio input to OneVoice for live captions. Set up at http://onevoice-sender.local",
                "icon": ICON,
                "url": f"https://github.com/{REPO}/releases/download/v{version}/{name}",
                "extract_size": ex_size,
                "extract_sha256": ex_sha,
                "image_download_size": dl_size,
                "image_download_sha256": dl_sha,
                "release_date": datetime.date.today().isoformat(),
                "init_format": "cloudinit-rpi",  # Raspberry Pi OS Trixie with cloud-init, like the official Lite image
                "devices": DEVICE_TAGS,
                "capabilities": [],
            }
        ],
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"wrote {out}: {name} ({dl_size} bytes, extracts to {ex_size})")


if __name__ == "__main__":
    main(*sys.argv[1:4])
