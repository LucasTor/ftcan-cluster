# Making the QML cluster + Bluetooth media permanent

Everything below was executed and verified live on the car on 2026-08-06 —
but only inside the tmpfs overlay, so the Pi reverts to stock (Kivy cluster,
no Bluetooth) at the next power cycle. This runbook replays it onto the real
disk. Total time ~30 min, most of it the BlueZ build.

**Before starting: the Pi must not lose power while the filesystem is
writable.** Do this with the ignition on / battery charger connected, and
don't cut power until the final `--ro` completes.

## Steps

1. **Mac** — make writable and push the latest code (one reboot):

       ./deploy.sh --no-ro

   This also restarts the (still-Kivy) service with the new code — fine.

2. **Pi** — run the installer (~20 min, idempotent, rerun if it fails):

       ssh lucas@192.168.0.153
       sudo bash /home/lucas/can-cluster/tools/pi/make_permanent.sh

   What it does (details in CLAUDE.md "Bluetooth audio" entry):
   - apt: BlueZ build deps, `python3-dbus`, `bluez-tools`, Qt runtime libs
     (`libfontconfig1 libxkbcommon0 libinput10`)
   - PySide6-Essentials 6.7.3 into the poetry venv + grafts
     `libQt6EglFsKmsGbmSupport.so.6.7.3` (the lib the wheel omits) from
     `tools/pi/`
   - `tools/setup_bluetooth.sh` (bluez-alsa A2DP sink + "Gol Cluster" identity)
   - builds BlueZ 5.87 patched by `tools/pi/patch_bluez_cover_art.py`
     into /usr/local; systemd override so bluetoothd runs `-E`; obexd
     service on the system bus + D-Bus policy; main.conf copy into
     /usr/local/etc; statedir symlink so pairings persist
   - swaps the launcher to `start_cluster_qml.py` under eglfs
     (`tools/pi/eglfs_kms.json` → /dev/dri/card1), **keeping the Kivy
     launcher at `start-can-cluster.sh.kivy`**
   - restarts everything and sanity-checks daemons + service

3. **Eyes on screen** — the QML cluster must be visible when the script says
   so. If the screen is black (eglfs logs look healthy even then):

       sudo cp /usr/local/bin/start-can-cluster.sh.kivy /usr/local/bin/start-can-cluster.sh
       sudo systemctl restart can-cluster.service      # back on Kivy

   …and debug later; the rest of the install is inert alongside Kivy.

4. **Pi** — pair the iPhone (fresh pairing required — the previous one lived
   in the overlay; also both sides must cache the new cover-art SDP records):

       bash /home/lucas/can-cluster/tools/bt_pair.sh

   On the phone: Settings → Bluetooth → "Gol 🚙💨" (no PIN — auto-accepts).
   If the phone still lists an old "Gol Cluster" entry, **forget it first**.

5. **Test** — play music, skip a track:
   - title/artist within ~1 s, cover art right after (`[bt] cover art -> …`
     in `./logs.sh`)
   - map layout: now-playing top-left; street/detail: toast on track change
   - `[map] redraw avg` in the journal should stay in single-digit ms

6. **Mac** — ALWAYS finish read-only (one reboot):

       ./deploy.sh --ro

7. **Power-cycle test** (the one that matters): ignition off, wait, ignition
   on → QML cluster boots, phone auto-reconnects when music plays, art shows.
   Nothing needs to be writable at runtime — art JPEGs land in /tmp (tmpfs).

## Rollback

- **UI only** (back to Kivy): step 3's two commands. Survives read-only mode?
  No — do it in a `--rw` window to make it stick.
- **Bluetooth stack** (back to distro 5.66): delete
  `/etc/systemd/system/bluetooth.service.d/override.conf`, `systemctl
  daemon-reload && systemctl restart bluetooth`, disable `obexd.service`.
  The /usr/local install is inert once the override is gone.

## Notes for later

- New phone pairings always need a `--rw` window (keys live in
  /var/lib/bluetooth). `bt_pair.sh` is the whole procedure.
- Audio is currently routed to HDMI (silent — panel has no speakers). The
  audible path needs a USB or I2S DAC; then rerun
  `tools/setup_bluetooth.sh <alsa-device>` to repoint bluealsa-aplay.
- `CAN_DEBUG=false` in the QML launcher (canrt discovery spam off); flip to
  true if hunting new CAN measures.
