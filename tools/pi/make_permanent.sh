#!/usr/bin/env bash
# make_permanent.sh — install the QML cluster + Bluetooth media/cover-art stack
# permanently on the Pi. Every step here was executed and verified live on
# 2026-08-06 in the tmpfs overlay; this script replays them onto the real disk.
#
# Run ON the Pi, as root, while the filesystem is WRITABLE and online:
#
#     (Mac)  ./deploy.sh --no-ro          # writable + latest code
#     (Pi)   sudo bash /home/lucas/can-cluster/tools/pi/make_permanent.sh
#     (Pi)   bash /home/lucas/can-cluster/tools/bt_pair.sh   # pair the iPhone
#     (Mac)  ./deploy.sh --ro             # ALWAYS finish read-only
#
# Idempotent — safe to rerun if a step fails. Takes ~20 min (BlueZ build).
# The Kivy launcher is preserved at start-can-cluster.sh.kivy (rollback:
# copy it back over the launcher and restart can-cluster.service).
set -euo pipefail

REPO="${REPO:-/home/lucas/can-cluster}"
BLUEZ_VER=5.87

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
if findmnt -nro FSTYPE / | grep -qx overlay; then
    echo "root is the read-only overlay — run './deploy.sh --rw' from the Mac first"
    exit 1
fi
[ -d "$REPO" ] || { echo "repo not found at $REPO"; exit 1; }

echo "== [1/7] apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    build-essential pkg-config libglib2.0-dev libdbus-1-dev libudev-dev \
    libical-dev libreadline-dev wget \
    python3-dbus bluez-tools \
    libfontconfig1 libxkbcommon0 libinput10

echo "== [2/7] PySide6 6.7.3 + the GBM lib the wheel omits"
VENV="$(cd "$REPO" && /root/.local/bin/poetry env info -p)"
QTLIB="$VENV/lib/python3.11/site-packages/PySide6/Qt/lib"
"$VENV/bin/pip" show PySide6-Essentials 2>/dev/null | grep -q "Version: 6.7.3" \
    || "$VENV/bin/pip" install --no-cache-dir PySide6-Essentials==6.7.3
# manylinux forbids linking libgbm, so the wheel ships eglfs_kms without its
# support lib; this copy is from the official Qt 6.7.3 linux_arm64 qtbase
cp "$REPO/tools/pi/libQt6EglFsKmsGbmSupport.so.6.7.3" "$QTLIB/"
ln -sf libQt6EglFsKmsGbmSupport.so.6.7.3 "$QTLIB/libQt6EglFsKmsGbmSupport.so.6"

echo "== [3/7] stock Bluetooth audio path (bluez-alsa)"
bash "$REPO/tools/setup_bluetooth.sh"

echo "== [4/7] BlueZ $BLUEZ_VER with cover-art patches -> /usr/local"
if ! /usr/local/libexec/bluetooth/bluetoothd --version 2>/dev/null \
        | grep -qx "$BLUEZ_VER"; then
    cd /tmp
    [ -f "bluez-$BLUEZ_VER.tar.xz" ] || \
        wget -q "https://www.kernel.org/pub/linux/bluetooth/bluez-$BLUEZ_VER.tar.xz"
    rm -rf /tmp/bluez-build
    mkdir /tmp/bluez-build
    tar xf "bluez-$BLUEZ_VER.tar.xz" -C /tmp/bluez-build
    cd "/tmp/bluez-build/bluez-$BLUEZ_VER"
    # AVRCP 1.6.2: cover-art handle only returned when explicitly requested —
    # stock BlueZ never asks, so no ImgHandle ever appears without this
    python3 "$REPO/tools/pi/patch_bluez_cover_art.py" .
    ./configure --prefix=/usr/local --disable-manpages --disable-systemd \
                --enable-experimental --disable-mesh --disable-btpclient \
                > /tmp/bluez_cfg.log
    make -j4 > /tmp/bluez_make.log 2>&1
    make install > /tmp/bluez_install.log 2>&1
fi

echo "== [5/7] BlueZ config plumbing"
# the /usr/local build reads its own sysconfdir
mkdir -p /usr/local/etc/bluetooth
cp /etc/bluetooth/main.conf /usr/local/etc/bluetooth/main.conf
# ...and its own statedir: symlink onto the real store or pairings "vanish"
mkdir -p /usr/local/var/lib
if [ -d /usr/local/var/lib/bluetooth ] && [ ! -L /usr/local/var/lib/bluetooth ]; then
    rm -rf /usr/local/var/lib/bluetooth
fi
[ -L /usr/local/var/lib/bluetooth ] || \
    ln -s /var/lib/bluetooth /usr/local/var/lib/bluetooth
# systemd override: REQUIRED — D-Bus activation of org.bluez otherwise
# resurrects the distro 5.66 daemon behind your back. -E: ImgHandle is
# an experimental property.
mkdir -p /etc/systemd/system/bluetooth.service.d
cat > /etc/systemd/system/bluetooth.service.d/override.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/local/libexec/bluetooth/bluetoothd -E
EOF
# obexd on the system bus needs a D-Bus policy to own org.bluez.obex
cat > /etc/dbus-1/system.d/obex.conf <<'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="org.bluez.obex"/>
  </policy>
  <policy context="default">
    <allow send_destination="org.bluez.obex"/>
  </policy>
</busconfig>
EOF
cat > /etc/systemd/system/obexd.service <<'EOF'
[Unit]
Description=OBEX daemon (BlueZ /usr/local, system bus, BIP cover-art client)
After=bluetooth.service
[Service]
ExecStart=/usr/local/libexec/bluetooth/obexd -n --system-bus
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable obexd >/dev/null 2>&1
systemctl restart bluetooth obexd bluealsa bluealsa-aplay
sleep 3
ps -eo args | grep -q "^/usr/local/libexec/bluetooth/bluetoothd -E" \
    || { echo "ERROR: patched bluetoothd not running"; exit 1; }
busctl status org.bluez.obex >/dev/null || { echo "ERROR: obexd not on bus"; exit 1; }

echo "== [6/7] QML launcher (Kivy preserved as .kivy fallback)"
L=/usr/local/bin/start-can-cluster.sh
[ -f "$L.kivy" ] || cp "$L" "$L.kivy"
cat > "$L" <<EOF
#!/bin/bash
# QML cluster launcher (Qt eglfs on KMS).
# Fallback to Kivy: cp $L.kivy $L && systemctl restart can-cluster.service
export DEV=false
export CAN_DEBUG=false
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=$REPO/tools/pi/eglfs_kms.json
export QSG_RENDER_LOOP=basic

cd $REPO
exec /root/.local/bin/poetry run python start_cluster_qml.py
EOF
chmod +x "$L"
systemctl restart can-cluster.service
sleep 6
systemctl is-active can-cluster.service >/dev/null \
    || { echo "ERROR: can-cluster.service not active — check journalctl"; exit 1; }

echo "== [7/7] done"
echo "LOOK AT THE SCREEN NOW — the QML cluster should be on it."
echo "Next:  bash $REPO/tools/bt_pair.sh    (pair the iPhone, still writable!)"
echo "Then from the Mac:  ./deploy.sh --ro"
