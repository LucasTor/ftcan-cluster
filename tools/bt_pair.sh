#!/usr/bin/env bash
# Pair the iPhone with the cluster — run ON the Pi.
#
# MUST be run during a writable window (./deploy.sh --rw): pairing keys live in
# /var/lib/bluetooth, which is tmpfs under overlayroot — pair while read-only
# and the pairing evaporates at the next power cut.
#
# Uses bt-agent (bluez-tools) as a NoInputNoOutput agent so pairing is
# "Just Works" — no PIN, auto-accepted. Do NOT script this with bluetoothctl's
# own agent: bluetoothctl silently auto-registers a KeyboardDisplay agent at
# startup, whose passkey-confirm prompts then time out unanswered and the
# iPhone shows "pairing failed" (learned the hard way, 2026-08-06).
#
# Opens a pairing window (default 180 s): on the iPhone, Settings > Bluetooth >
# "Gol Cluster". Afterwards every paired device is trusted so it reconnects in
# the car without any prompt, forever.
set -euo pipefail

WINDOW="${1:-180}"
command -v bt-agent >/dev/null 2>&1 || {
    echo "bt-agent not found — run tools/pi/make_permanent.sh (or: apt install bluez-tools)"
    exit 1
}

pkill -x bt-agent 2>/dev/null || true
bt-agent -c NoInputNoOutput -d
bluetoothctl pairable on >/dev/null
bluetoothctl discoverable on >/dev/null
echo ">> pairing window open for ~${WINDOW}s — pick 'Gol 🚙💨' on the iPhone"
sleep "$WINDOW"

echo ">> trusting paired devices"
{ bluetoothctl devices Paired 2>/dev/null || bluetoothctl paired-devices; } |
    awk '/^Device/ {print $2}' | while read -r mac; do
        bluetoothctl trust "$mac" >/dev/null
    done
bluetoothctl discoverable off >/dev/null 2>&1 || true
pkill -x bt-agent 2>/dev/null || true

echo ">> paired devices now:"
bluetoothctl devices Paired 2>/dev/null || bluetoothctl paired-devices
echo ">> play a song on the phone — title/artist appear in ~1 s, cover right after"
echo ">> then, from the Mac: ./deploy.sh --ro"
