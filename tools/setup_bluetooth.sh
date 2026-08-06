#!/usr/bin/env bash
# One-time Bluetooth audio provisioning — run ON the Pi, as root, during a
# writable window WITH internet:
#
#     ./deploy.sh --rw                      # from the Mac
#     ssh lucas@192.168.0.153
#     sudo bash <repo>/tools/setup_bluetooth.sh [alsa-pcm]
#     bash <repo>/tools/bt_pair.sh          # pair the iPhone (also needs --rw!)
#     ./deploy.sh --ro                      # from the Mac, when done
#
# Makes the Pi an A2DP sink named "Gol Cluster":
#   * BlueZ main.conf: name, car-audio device class, auto-enable on boot
#   * bluez-alsa: the headless Bluetooth-audio daemon (no PulseAudio/PipeWire
#     session needed — right fit for a read-only appliance)
#   * bluealsa-aplay: pipes whatever any connected phone streams to an ALSA
#     output. Which output: $1 or $BT_ALSA_DEV (default "default" — on a bare
#     Pi 5 that's HDMI; once a USB/I2S DAC is fitted, rerun with e.g. "hw:1,0"
#     or edit /etc/systemd/system/bluealsa-aplay.service).
#
# Track metadata needs nothing extra: bluetoothd exposes it on D-Bus and
# bt_media_helper.py picks it up. Idempotent — safe to rerun.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
PCM="${1:-${BT_ALSA_DEV:-default}}"

echo ">> installing packages (bluez, bluez-alsa)"
apt-get update
apt-get install -y bluez bluez-alsa-utils alsa-utils

echo ">> writing /etc/bluetooth/main.conf"
[ -f /etc/bluetooth/main.conf ] && [ ! -f /etc/bluetooth/main.conf.orig ] && \
    cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.orig
cat > /etc/bluetooth/main.conf <<'EOF'
# Written by tools/setup_bluetooth.sh (distro original: main.conf.orig)
[General]
Name = Gol 🚙💨
# Class of device: Audio+Rendering service, Audio/Video major, Car Audio minor
# -> the iPhone shows it with a car icon and treats it like a head unit
Class = 0x240420
# not discoverable in normal operation; bt_pair.sh opens a pairing window
DiscoverableTimeout = 180
FastConnectable = true

[Policy]
# radio on at boot so the trusted phone can reconnect unattended
AutoEnable = true
EOF

# bluez-alsa daemon binary name differs across versions
BLUEALSA_BIN="$(command -v bluealsad || command -v bluealsa || true)"
[ -n "$BLUEALSA_BIN" ] || { echo "bluez-alsa daemon binary not found"; exit 1; }
APLAY_BIN="$(command -v bluealsa-aplay)"

# Use packaged systemd units when the distro ships them; write minimal ones
# otherwise. A2DP source+sink are bluez-alsa's default profiles; -p a2dp-sink
# narrows us to sink-only (the cluster never sends audio).
if [ ! -f /lib/systemd/system/bluealsa.service ] && \
   [ ! -f /etc/systemd/system/bluealsa.service ]; then
    echo ">> writing bluealsa.service"
    cat > /etc/systemd/system/bluealsa.service <<EOF
[Unit]
Description=BluezALSA daemon (A2DP sink)
Requires=bluetooth.service
After=bluetooth.service

[Service]
ExecStart=$BLUEALSA_BIN -p a2dp-sink
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
fi

echo ">> writing bluealsa-aplay.service (output: $PCM)"
cat > /etc/systemd/system/bluealsa-aplay.service <<EOF
[Unit]
Description=BluezALSA playback (Bluetooth -> ALSA $PCM)
Requires=bluealsa.service
After=bluealsa.service

[Service]
# 00:00:00:00:00:00 = play audio from any connected device
ExecStart=$APLAY_BIN --pcm=$PCM 00:00:00:00:00:00
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

echo ">> enabling services"
systemctl daemon-reload
systemctl enable --now bluetooth bluealsa bluealsa-aplay

echo ">> done. Next: bash tools/bt_pair.sh  (while still writable!)"
echo "   then from the Mac: ./deploy.sh --ro"
