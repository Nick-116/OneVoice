#!/bin/bash -e
# Builds the OneVoice Sender Raspberry Pi image with pi-gen (Raspberry Pi's own image builder).
# Needs Linux with Docker; an arm64 machine builds natively (CI uses GitHub's arm64 runner).
# Output: pi/dist/OneVoiceSender-<version>-RaspberryPi.img.xz

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIGEN_REF="2026-09-15-raspios-trixie-arm64"
WORK="${WORK:-$ROOT/pi/work}"
VERSION="$(cat "$ROOT/VERSION")"

rm -rf "$WORK/pi-gen"
mkdir -p "$WORK" "$ROOT/pi/dist"
git clone --depth 1 --branch "$PIGEN_REF" https://github.com/RPi-Distro/pi-gen.git "$WORK/pi-gen"
cd "$WORK/pi-gen"

cp "$ROOT/pi/config" config
cp -r "$ROOT/pi/stage-onevoice" .
rm -f stage2/EXPORT_IMAGE  # only export the final OneVoice image, not plain Raspberry Pi OS Lite

APP=stage-onevoice/01-onevoice/files/app
mkdir -p "$APP"
cp -r "$ROOT/sender/church_sender" "$ROOT/sender/requirements-pi.txt" "$APP/"
find "$APP" -name '__pycache__' -prune -exec rm -rf {} +

./build-docker.sh

IMG="$(ls -t deploy/*.img.xz | head -1)"
mv "$IMG" "$ROOT/pi/dist/OneVoiceSender-${VERSION}-RaspberryPi.img.xz"
ls -lh "$ROOT/pi/dist"
