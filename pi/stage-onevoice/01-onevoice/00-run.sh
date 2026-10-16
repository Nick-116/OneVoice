#!/bin/bash -e
# Installs OneVoice Sender in web mode. build.sh copies the app into files/app first.

install -d "${ROOTFS_DIR}/opt/onevoice-sender"
cp -r files/app/church_sender files/app/requirements-pi.txt "${ROOTFS_DIR}/opt/onevoice-sender/"
install -m 644 files/onevoice-sender.service "${ROOTFS_DIR}/etc/systemd/system/onevoice-sender.service"
install -m 644 files/motd "${ROOTFS_DIR}/etc/motd"

on_chroot << CHROOT
set -e
id -u onevoice >/dev/null 2>&1 || adduser --system --group --home /var/lib/onevoice --no-create-home onevoice
python3 -m venv /opt/onevoice-sender/venv
/opt/onevoice-sender/venv/bin/pip install --no-cache-dir --upgrade pip
/opt/onevoice-sender/venv/bin/pip install --no-cache-dir --only-binary=:all: -r /opt/onevoice-sender/requirements-pi.txt
/opt/onevoice-sender/venv/bin/python -c "import numpy, sounddevice, soxr, websockets, keyring, ctypes.util; assert ctypes.util.find_library('crypt'); print('onevoice-sender deps ok')"
find /opt/onevoice-sender -name '__pycache__' -prune -exec rm -rf {} +
chown -R root:root /opt/onevoice-sender
systemctl enable onevoice-sender.service avahi-daemon.service unattended-upgrades.service
# pi-gen sets a root password while building; nobody needs root logins on this appliance.
passwd -l root
CHROOT
