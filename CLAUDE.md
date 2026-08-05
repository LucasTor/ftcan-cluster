# CLAUDE.md — working notes for AI sessions

Context and hard-won facts for working on this repo. Read this before making changes.

## What this is

A digital gauge cluster for a **1992 VW Gol G1** (turbo, "Azul Boreal" blue). It runs on a
**Raspberry Pi 5** (Armbian, Debian bookworm) on a **1920×720** display, reading engine data
from a **FuelTech ECU over CAN (FTCAN 2.0)** and switch inputs over **GPIO**. UI is **Kivy**
(SDL2 / KMS-DRM, no desktop). The look is minimal/dark with an Azul Boreal blue accent
(modelled on a Claude Design mockup, "Painel Gol Minimal").

There is also a **complete QML/Qt Quick twin of the UI** (see "The QML build" below) —
same backend, parallel view layer, not yet deployed to the Pi.

## The deployment is the tricky part — read this

- **Target Pi:** `192.168.0.153`, user `lucas`, password `lucas` (also baked as defaults in
  `deploy.sh`/`logs.sh`, overridable via `PI_HOST`/`PI_USER`/`PI_PASS`). Needs `sshpass`
  locally (`brew install sshpass`).
- **The root filesystem is READ-ONLY in normal operation.** The car cuts power to the Pi the
  instant the ignition goes off, so an unclean power loss must never corrupt the SD. Read-only
  is done with Armbian's **overlayroot** (writes go to a tmpfs in RAM and are discarded on
  power loss). It is toggled purely by the presence of an `overlayroot=tmpfs` token in
  **`/boot/firmware/cmdline.txt`** (on the always-writable FAT partition, recoverable by
  mounting the SD on any machine).
- **Use `./deploy.sh`** for everything — it cycles the overlay for you:
  - `./deploy.sh` — full: make writable → rsync the repo → re-enable read-only (2 reboots).
  - `./deploy.sh --no-ro` — deploy but leave it writable (iterate, then `--ro` when done).
  - `./deploy.sh --rw` / `--ro` — just flip the mode. `--status` — report mode.
  It preserves `.git`, sets `DEV=false` in the launcher, restarts the service, and confirms
  every reboot actually happened via the kernel **`boot_id`** (don't replace that check with a
  plain "is it up" ping — a reboot that didn't fire would look "up").
- **You cannot physically reset the Pi** (owner is usually away). Never run a change that could
  leave it unbootable without a recovery path. cmdline/config edits are safe (FAT, recoverable);
  initramfs changes are the risky ones. Always verify SSH returns after a reboot before the next
  irreversible step.
- **End every deploy with the Pi read-only.** After any `--no-ro`/`--rw` work, run `./deploy.sh --ro`.

## You cannot see the screen — how to verify

- The app runs headless via systemd `can-cluster.service` → `/usr/local/bin/start-can-cluster.sh`
  → `poetry run python start_cluster.py`. Confirm health with the journal (you're in the
  `systemd-journal` group, no sudo): `./logs.sh`, `./logs.sh gpio`, `./logs.sh 100`.
  "Service active, 0 restarts, no traceback, reached `Start application main loop`" = it built
  all widgets and is running.
- **For visual checks, render components locally and screenshot them.** This Mac has a real
  display, so a Kivy harness works. Pattern: set `KIVY_METRICS_DENSITY=1` + `KIVY_DPI=96`
  (match the Pi — otherwise Retina density 2 doubles every font), `DEV=false`, `Window.size`,
  build the widget at its **real pixel size** (gauges are 600×600), `Clock.schedule_once` to set
  values then `Window.screenshot(name='/tmp/x.png')`, then `Read` the PNG.
  - Do **not** render the full 1920×720 dashboard window (too wide for the screen / owner asked
    not to). Render one gauge / the centre card / the alert row in a window just big enough.
  - Widgets position with absolute coords + `WINDOW_HEIGHT` (720) and `Window.width`, so to see
    them at true position the window must be 720 tall (e.g. 1280×640/720 for two gauges).
  - Throwaway harness file: name it `_capture.py`, delete it before deploying.
- **Gotcha:** if you set a Label's text *and* screenshot in the same Clock callback, the shot is
  one frame stale (shows the old text). Set values ~1s before the screenshot.

## Data flow (how a value reaches a pixel)

```
CAN thread (can_helper.read_can) ─┐
                                  ├─→ SensorState (model.py, thread-safe) ─→ Dashboard.update() @30Hz ─→ widgets
GPIO thread (gpio_helper.read_io)─┘        (start_cluster.py spawns both threads)
```

- `model.SensorState` is the single shared state (a `@dataclass` with a lock). `update(dict)`
  merges decoded CAN frames and stamps a CAN-activity clock (`since_can()`); reader threads
  write it, the Kivy loop reads it. `IoState` is the GPIO sub-state.
- **No-CAN demo mode:** if `since_can() > 3s` (bench / not in car), `CarClusterApp` feeds
  `demo.simulate(t)` into the state so the cluster animates. Real CAN frames take over instantly.
  Running `cluster.py` standalone (no CAN) therefore self-animates.

## Wiring GPIO → tell-tale (3 names must line up)

`gpio_helper.Pin.<NAME>` (lowercased) **must equal** an `IoState` field name **must equal** the
key used in `TopAlerts.set_state` / `PILLS`. `IoState.update()` silently drops readings whose pin
name has no matching field. Then `set_state` maps `io.<field>` → a pill key. To add one: add the
`Pin`, add the `IoState` field, add the `set_state` line, add/keep the `PILLS` entry, deploy.

## FTCAN 2.0 (the CAN side) — important

- We currently read only the **simplified broadcast** (4 fixed frames `0x14080600..0x14080603`,
  extended IDs) in `can_helper.py`. These carry TPS/MAP/temps/pressures/gear/lambda/RPM/oil-temp/
  pit-limit/wheel-speeds. That's it.
- The protocol spec (`Protocol_FTCAN20.pdf`, has a text layer — extract with PyMuPDF/`fitz`,
  `page.get_text()`; this copy's DataID table is longer than the older repo one, reaching
  `0x0290 Vehicle Speed`, brake temps, TPMS) also defines a **real-time *tagged* broadcast**
  (MessageID `0x_FF`, frame IDs like
  `0x140011FF`) where each measure is `MeasureID(2B)+Value(2B)`, `MeasureID = (DataID<<1)|statusbit`.
  **We do NOT read this yet.** Fan, 2-step/launch, and ECU output states only live here.
  - **2-step / launch:** `DataID 0x0007` "ECU Launch Mode" (nonzero = a launch mode armed), or
    `DataID 0x0048` "2 Step Signal" (Note 7 = 0:off/1:on).
  - **Radiator fan:** read via the dedicated `DataID 0x004D` "ECU Eletro Fan" measure (Note 7 =
    0:off/1:on) → `SensorState.radiator_fan`. (The fan is physically wired to gray output 3, but the
    ECU's electro-fan function reports its state on this measure regardless of output.) An alternative
    source is the **Generic outputs state** bitmask `DataID 0x0152` (Note 9: bit N = Output N+1 on).
- **The sender is identifiable per frame:** bits 28–14 of the 29-bit arbitration ID are the
  ProductID (`(ProductTypeID << 5) | unique`, so `arbitration_id >> 19` = ProductTypeID). When two
  devices broadcast the same DataID, gate on the sender via `SOURCE_GATE` in `can_helper.py`
  (DataID → required ProductTypeID). Used for **fuel level** (`DataID 0x0281`, %×10 by our own
  convention — the spec's unit is TBD): the owner's ESP32 sender at ProductID `0x7F00`
  (ProductTypeID `0x03F8`, CAN ID `0x1FC003FF`, 10 Hz, DLC 4) is the trusted source; the spec
  lists the same DataID as a PowerFT ECU measure, which the gate drops. `log_realtime()` prints
  each measure's sender ProductID for discovery.

## The map layout (third layout, `map`)

- **NFS-style perspective street map** of São Marcos - RS at the car's GPS position:
  heading-up, car chevron fixed near the bottom, glowing tapered road ribbons (Kivy `Mesh`
  triangle strips — `Line` can't taper, and band approximations show visible steps). Pieces:
  `widgets/map_view.py` (roads/fog/marker), `gps_helper.py` (position feed), `map_data.json`
  (baked offline road data — the Pi has no internet). A satellite ground-texture layer
  (`ground_fx.py` + `map_texture.jpg`) was built and then removed at the owner's request
  (didn't like it); it's in this repo's session history if ever wanted again.
- **Position source:** `gps_helper.read_gps` thread. With no USB GPS present it mock-drives a
  real route across the region; when a NMEA module appears it hot-switches to
  parsing checksum-validated `RMC` sentences. The owner's module is a **VK-162** (u-blox 7,
  USB CDC, 9600 baud), found via `/dev/serial/by-id/*u-blox*` — NOT a bare ttyACM number.
  (Verified on the Pi 2026-07-29: the CANable runs candleLight/gs_usb — `1d50:606f`, no CDC
  serial at all — so there is no tty conflict today, but identity-based discovery stays: it
  is robust to any future device shuffle. `GPS_DEV` env overrides the path explicitly.) The owner's AliExpress listing (item 1629858367) names no
  chipset, but its spec table (50 channels, -160/-146 dBm, 32 s cold start, "4800 or 9600
  baud" output) fingerprints as **u-blox 6 generation** (NEO-6M class) — which accepts the
  same UBX rate command and maxes out at exactly the 5 Hz we request. Handled: baud auto-detect (9600 → 4800 SiRF → 38400 →
  115200; `GPS_BAUD` pins it) and 5 Hz fix-rate commands in all three dialects (u-blox UBX,
  CASIC `$PCAS02`, MediaTek `$PMTK220`) at every port open — each chip ignores the dialects
  it doesn't speak; SiRF stays at its default rate. If the module is a non-u-blox clone the
  `by-id` glob may not match its USB strings — check `ls /dev/serial/by-id/` and set
  `GPS_DEV` in the launcher if needed. Untested on the real module as of 2026-07-29. It writes `lat/lon/heading_deg/gps_speed_kmh`
  directly into `SensorState` fields (NOT via `state.update()` — that would stamp the CAN
  clock and kill no-CAN demo detection). The map HUD's speed is `wheel_speed_fl_kmh` (owner:
  wheel speed is the trusted source).
- **Baked data:** OSM roads (Overpass, clipped to 12.5 km radius = 25x25 km coverage,
  Douglas-Peucker'd, unnamed <30 m residential stubs demoted to "service" class — they're
  real half-mapped street entrances). ~1.7k road chunks; a 1 km-cell spatial index in
  `MapView` keeps per-frame culling proportional to local density, not map size. Bake script
  lives in the session scratchpad; re-baking needs internet on the Mac. Projection origin
  -28.970008, -51.071114; local metres via equirectangular.
- **Perf:** every frame rebuilds ~600-900 meshes (cores + 2 glow layers). The journal gets
  `[map] redraw avg X.Xms over 600 frames` every ~20 s — check it after deploying map changes;
  glow layers are the first knob if the Pi can't hold 30 fps.

## The display panel (verified on the Pi 2026-07-29)

- EDID identifies as "GRA (Graphica Computer) HD Display", 2020, preferred mode 1920×720.
- **DDC/CI is NOT implemented** — the panel serves EDID but "DDC communication failed"
  (`ddcutil detect` → Invalid display; `ddcutil` is already installed on the Pi). So HDMI
  brightness control is off the table; night dimming stays the `NightDim` overlay, and the
  only hardware route would be a backlight-PWM pin mod on the panel's driver board.
- The EDID **does** advertise HDR10 (PQ EOTF, max-luminance code 96 ≈ 400 nits claimed) —
  moot for us: Kivy/SDL2 has no HDR path and the cluster's dark flat UI wouldn't benefit.
- 1920×720 is a non-CEA mode, so the KMS driver defaults to **full-range RGB** output —
  the near-black theme background renders correctly (no washed-grey limited-range issue).

## Layout switching on the car

- **Flash-and-hold gesture** on the high-beam stalk cycles layouts: one short flash
  (<0.45 s), release (<0.9 s), then pull and hold (≥0.6 s). Detector is `gesture.py`
  (pure logic, unit-tested against normal high-beam / single & double flash-to-pass —
  none of them fire); `Dashboard.update` samples `state.io.high_beam` through it. The
  owner rejected touch input (fingerprints on the display). **Live-verified 2026-07-30** —
  the owner fired it 6 times in a row on the real stalk (first tries were rapid flicks,
  which correctly did NOT fire; flash-then-hold fired every time).

## In-flight / TODO

- **Fan + 2-step tell-tales:** fed by the tagged-broadcast reader in `can_helper.py`
  (`DATAID_LAUNCH 0x0008` → `two_step`, `DATAID_FAN 0x004D` "ECU Eletro Fan" → `radiator_fan`).
  **Live-verified 2026-07-30:** the real ECU (ProductID 0x5020) broadcasts both — fan observed
  as 1 with ignition on, 0x0008/0x0048 present at 0. Pill-level check (fan pill actually lit)
  still pending owner eyes-on-screen.
- **GPIO pin map is being discovered** by the owner via `./logs.sh gpio` (toggle a switch, see
  which GPIO logs `-> ON`). Known: `HIGH_BEAM=6, LEFT_INDICATOR=21, RIGHT_INDICATOR=16, CHOKE=13,
  PARKING_BRAKE=5`; `B=20, D=19, E=26` still unknown. `PARKING_BRAKE` → BRAKE pill, `HIGH_BEAM` →
  HIGH pill, `CHOKE` → BOOSTER pill, indicators → ◄ ► arrows. **CHOKE is active-high** — it's in
  `gpio_helper.INVERTED`, so its reading is inverted vs. the active-low default of the other pins.
- A **plymouth VW-logo boot splash** was attempted and **fully reverted** (couldn't get the logo
  to composite without seeing the screen; logo went off-screen). Boot logs are back to normal.
  `vw-logo.avif` is kept in the repo. If retrying, prefer a built-in plymouth image theme over a
  hand-written script theme, and you'll need the owner to confirm placement on the real screen.

## The QML build (parallel UI, 2026-08-04)

A full Qt Quick port of the cluster lives alongside the Kivy one — same three layouts
(street / detail / map), tell-tales incl. bulb check, alarms, intro sweeps, demo mode,
flash-and-hold gesture. **The Kivy build is untouched and remains what runs on the
car.** The QML build is verified on the Mac (screenshot parity) but **not yet deployed
to the Pi**. It also goes beyond the Kivy build in three deliberate ways: layouts
switch via an infinite vertical carousel slide (300 ms; every switch slides up — a
continuous `carouselPos` only ever advances and slots sit at wrapped offsets), the view
runs 4x MSAA, and night mode is **palette-level** instead of the Kivy black veil —
`Theme.d()` dims informational colours to ~45% while tell-tales, alarms, the shift
light and EGT status dots stay full-brightness (the custom `ring_item`/`map_item`
take a `dim` property since their colours never pass through QML).

- **Files:** `qml/` (all QML; `Theme.qml` mirrors `theme.py`), `cluster_qml.py`
  (SensorBridge QObject + all decision logic: pills/bulb-check/alarms/demo/gesture —
  QML is presentation only), `map_item.py` / `ring_item.py` (custom scene-graph items),
  `start_cluster_qml.py` (thread launcher twin). Backend (`model`, `demo`, `gesture`,
  `can/gpio/gps_helper`) is shared unmodified.
- **PySide6 version is load-bearing** (split by platform in `pyproject.toml`):
  Pi/linux = `6.7.3`, the last release whose manylinux aarch64 wheel (2_31) installs
  on bookworm's glibc 2.36 (needs python <3.13; Pi runs 3.11). Mac/darwin = `6.11.x`,
  verified with the custom scene-graph items on 3.13 and 3.14. Avoid 6.10.x — it
  crashed in Python scene-graph overrides. The project pins `python <3.14` because
  Kivy 2.3.1 has no cp314 wheels — the Mac poetry env runs **3.13** so the Kivy and
  QML builds share one env (`poetry env use python3.13`).
- **Python scene-graph rules (violating these = blank/segfaulting items):**
  keep `QSGGeometry.defaultAttributes_*()` in a module-level global (the binding hands
  you a temporary; QSGGeometry stores a pointer into it); keep Python refs to
  node/geometry/material on the item; write vertices by `struct.pack`-ing into a
  bytearray and `ctypes.memmove` into `int(geom.vertexData())` (address is stable and
  writes verified); set `QSG_RENDER_LOOP=basic` (done in `cluster_qml.py` — the
  threaded loop crashes into the GIL).
- **Verifying on the Mac:** run `scratchpad/qml_capture.py`-style harness — a real
  window at `DEV=true` half-scale (960×360); the Retina grab is exactly 1920×720.
  The offscreen platform **cannot** render the map/ring (it forces the software
  backend, which skips custom geometry nodes) — a real window is required for those.
  Mac-only gotcha: grabs can flakily lose custom-node regions when other windows
  occlude the test window (compositor artifact — looked like truncated geometry, cost
  a long debug session; re-run with the window unobstructed before believing a bad
  grab). Irrelevant on the Pi (eglfs fullscreen, no compositor).
- **Deploying would need (not done):** PySide6-Essentials==6.7.3 in the poetry env on
  the Pi (needs `--rw` + internet), a launcher pointing at `start_cluster_qml.py`, Qt
  `eglfs` platform (`QT_QPA_PLATFORM=eglfs`, likely a KMS config for the non-CEA
  1920×720 mode), `QSG_RENDER_LOOP=basic`, and eyes-on-screen the first boot — eglfs
  bring-up shows healthy logs even when the display is black, so keep the Kivy
  launcher as fallback.
- Fonts: Kivy's "bold" is Compagnon-**Medium** + synthetic bold — QML must use
  `font.bold: true` over Medium. `Compagnon-Bold.otf` is a decorative outline face
  that looks nothing like the cluster's digits; don't use it.

## Conventions

- `DEV` (env, default `true`): halves the window + density 1 for desktop preview. **Production
  launcher sets `DEV=false`** (full window, no demo-loop interference). Don't rely on `DEV` for
  the no-CAN demo — that's keyed off `since_can()`, independent of `DEV`.
- Match existing style: `theme.py` holds all colours/sizes; widgets pull from it. Fonts are loaded
  by path (`fonts/ShareTechMono-Regular.ttf`, etc.) so the working dir must be the repo root
  (the systemd launcher `cd`s there).
- Changes are typically left **uncommitted** unless the owner asks to commit.
