# CLAUDE.md — working notes for AI sessions

Context and hard-won facts for working on this repo. Read this before making changes.

## What this is

A digital gauge cluster for a **1992 VW Gol G1** (turbo, "Azul Boreal" blue). It runs on a
**Raspberry Pi 5** (Armbian, Debian bookworm) on a **1920×720** display, reading engine data
from a **FuelTech ECU over CAN (FTCAN 2.0)** and switch inputs over **GPIO**. UI is **Kivy**
(SDL2 / KMS-DRM, no desktop). The look is minimal/dark with an Azul Boreal blue accent
(modelled on a Claude Design mockup, "Painel Gol Minimal").

There is also a **complete QML/Qt Quick twin of the UI** (see "The QML build" below) —
same backend, parallel view layer. **As of 2026-08-06 the QML build IS what runs on the
car** (launcher → `start_cluster_qml.py` under Qt eglfs); the Kivy launcher is preserved
at `/usr/local/bin/start-can-cluster.sh.kivy` as the rollback path.

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
  → `poetry run python start_cluster_qml.py` (QML build since 2026-08-06; the Kivy
  launcher is preserved at `start-can-cluster.sh.kivy`). Confirm health with the journal (you're in the
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

- **Street name + GPS clock (2026-08-06, QML build only, Mac-verified, NOT yet
  deployed/seen on the car):** map layout shows the current road name bottom-left
  (under KM/H) and every layout gets a wall clock top-right (Main.qml overlay,
  right-aligned with the map compass below it). Pieces: `map_names.json` (separate
  name layer — the render bake strips names; baked by `tools/bake_map_names.py`,
  needs internet, same origin/projection as map_data), `map_geometry.StreetNamer`
  (nearest-named-road with ON 30 m / OFF 45 m hysteresis + 2-sample debounce,
  sampled at ~2 Hz by the bridge), `decisions.clock_text` (UTC-3 hardcoded — RS
  has no DST since 2019) fed by new `SensorState.gps_time_utc/_mono` stamped from
  RMC time+date (A-status sentences only; the Pi has no RTC, GPS is the only true
  time source — clock shows blank until first fix). The mock drive feeds system
  time so the bench clock runs. Kivy build untouched (reads none of this).
- **Session peaks (2026-08-06, QML build only, Mac-verified, NOT yet deployed):**
  `decisions.PeakTracker` (max rpm/boost/speed/EGT since power-on; demo feeds it
  on the bench but the first real CAN frame after a demo episode resets it) →
  bridge `peak_*` props → `qml/PeaksTile.qml` in the detail grid's bottom-right
  corner (1594, 480); LAMBDA moved inward to (1296, 480), **replacing the MAP
  tile, which duplicated BOOST** (both bound `layout.boost`).
  The (700, 480) slot must STAY empty — it's clearance for the big RPM readout's
  right edge at 4-digit values (a tile there clips the readout).
- **Odometer: FTCAN 2.0 does NOT broadcast one.** Full DataID table
  (0x0000–0x02DF) extracted from this repo's spec PDF and checked 2026-08-06 —
  no total-distance measure exists; closest is `0x01B3 Fuel Total Consumption`
  (ECU-persisted, has a reset button). Worth one `log_realtime()` run on the car
  to look for undocumented DataIDs, but don't expect it. Realistic routes: the
  owner's ESP32 sender integrates wheel speed off the bus and broadcasts a custom
  DataID (it has flash — survives power cuts, unlike the Pi's overlayroot tmpfs),
  or a session-only trip counter on the Pi.

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
- **Bluetooth audio + now-playing (stage 1, 2026-08-05 — code written, Pi NOT provisioned,
  no widget yet, layout TBD):** the iPhone as A2DP source. Audio: bluez-alsa → ALSA (never
  touches Python). Metadata: `bt_media_helper.py` polls bluetoothd's `org.bluez.MediaPlayer1`
  via `busctl --json` at 1 Hz (zero new deps; pure parser `parse_managed_objects` is
  fixture-tested) into new `SensorState` fields `bt_connected/bt_device/track_*` — direct
  field writes like GPS, never `state.update()`. Run `poetry run python bt_media_helper.py`
  on the Pi as a live monitor. To provision: `sudo tools/setup_bluetooth.sh [pcm]` then
  `tools/bt_pair.sh`, BOTH during a `--rw` window with internet — **pairing keys in
  `/var/lib/bluetooth` are tmpfs under overlayroot**, so pairing while read-only evaporates
  at power-off. Audio out needs a USB/I2S DAC (Pi 5 has no analog jack; until then the PCM
  default lands on HDMI). **Cover art: WORKING (verified on the car with the owner's
  iPhone 2026-08-06). PERMANENT since 2026-08-06: `tools/pi/make_permanent.sh` was
  executed on the real disk (docs/permanent-deploy.md is the runbook) — phone paired
  as trusted under the new stack, alias "Gol 🚙💨" stored, all of it verified surviving
  a reboot into read-only mode.** The recipe it implements (for future reference /
  re-provisioning):
  1. Build **BlueZ 5.87** (kernel.org tarball) with **`tools/pi/patch_bluez_cover_art.py`
     applied first** — per AVRCP 1.6.2 a target only returns the cover-art handle when
     *specifically* requested, so stock BlueZ (which sends count-0 "all attributes")
     never receives an ImgHandle, on BOTH request paths: `avrcp_get_element_attributes`
     AND `avrcp_get_item_attributes` (the browsing-channel one — that's what actually
     runs on track change for browsing players like iPhones). Configure:
     `--prefix=/usr/local --disable-manpages --disable-systemd --enable-experimental
     --disable-mesh --disable-btpclient`; build deps: build-essential pkg-config
     libglib2.0-dev libdbus-1-dev libudev-dev libical-dev libreadline-dev.
  2. `bluetoothd` must run with **`-E`** (ImgHandle is experimental) via a **systemd
     override of bluetooth.service ExecStart** — a manually-started daemon gets
     silently replaced by the distro 5.66 one through D-Bus activation of org.bluez.
     The /usr/local build reads `/usr/local/etc/bluetooth/main.conf` (copy ours there)
     and stores at `/usr/local/var/lib/bluetooth` — **symlink it to
     /var/lib/bluetooth** or pairings "vanish".
  3. `obexd -n --system-bus` (5.80+ flag) + a D-Bus policy file allowing root to own
     `org.bluez.obex` on the system bus (`/etc/dbus-1/system.d/obex.conf`).
  4. **Clean re-pair after changing our SDP record** (the 5.87 controller record
     advertises cover art; 5.66's didn't): delete
     `/var/lib/bluetooth/<adapter>/cache/<phone-mac>` AND forget on the iPhone —
     both sides cache SDP. Symptom of staleness: no ImgHandle ever appears.
  5. iPhone specifics handled in `bt_media_helper._ArtFetcher`: the cover-art OBEX
     PSM exists only inside the AVRCP target record (obexd's own SDP search for an
     Imaging 0x111A record fails with "Unable to find service record" — which is ALSO
     its error for a failed L2CAP connect, beware) so CreateSession gets an explicit
     `PSM` parsed from BlueZ's SDP cache file; and iOS only includes ImgHandle in
     metadata once the BIP session is CONNECTED, so the fetcher "primes" the session
     eagerly on connect (with retry — the cache file is mid-rewrite right at connect).
  6. **obexd destroys a client session the moment its creating D-Bus connection
     drops** — one-shot busctl calls can NEVER hold a session. `_ArtFetcher` keeps a
     persistent dbus-python SystemBus connection (`apt install python3-dbus`; the
     poetry venv reaches it via `/usr/lib/python3/dist-packages` — same cp311 ABI).
  7. Pairing agent: scripted `bluetoothctl` is a trap (it auto-registers a
     KeyboardDisplay agent asynchronously; passkey-confirm prompts then time out
     unanswered → iPhone shows "pairing failed"). Use `bt-agent -c NoInputNoOutput`
     (apt: bluez-tools). Update setup_bluetooth.sh/bt_pair.sh accordingly for the
     permanent deploy.
  8. BlueZ 5.87 nests players at `.../dev_XX/avrcp/player0` (5.66: `.../dev_XX/player0`)
     — anything deriving the device path from the player path must handle both
     (`bt_media_helper._DEV_RE`).
  **Display (QML build ONLY, owner's call — the Kivy build has no media UI):** a transient
  bottom-centre toast on track change / phone connect (`qml/MediaToast.qml`; envelope +
  lines from `decisions.MediaToast`, driven via bridge `toast_*` props; hidden while the
  alarm banner is up and on the map layout) plus a persistent top-left now-playing on the
  map (`qml/NowPlaying.qml` — top-left is inside the fog band, always solid background).
  Both show an MDI "disc" placeholder in the art square (`decisions.MEDIA_ART_ICON`)
  when a track has no art. **Track transitions are ATOMIC (owner's call):**
  `bt_media_helper._TrackPresenter` holds the old title/artist/art on screen until the
  new track's metadata has been stable for a full poll AND its cover has downloaded,
  then swaps everything at once — because iOS pushes Track updates staggered (ImgHandle
  first, often under the old title, then the title with a *reissued* handle), and
  reacting per-push flashed placeholders and double-fetched art. Rapid skipping holds
  the display until skipping stops. Fetched JPEGs are validated end-to-end
  (`_jpeg_complete` — aborted OBEX transfers leave truncated files that render as
  visible garbage). Screenshot-verified on the Mac 2026-08-05. **Demo mode also
  plays a fake playlist** (`demo.PLAYLIST`, 45 s/track, device "DEMO") so the bench
  exercises the media UI; ownership rules: a real phone always wins (`state.since_bt()`
  stamped by the helper, which itself writes only on change), and `DemoFeed.reset(state)`
  clears a demo-owned track when real CAN returns — mind those if touching either side.
- A **plymouth VW-logo boot splash** was attempted and **fully reverted** (couldn't get the logo
  to composite without seeing the screen; logo went off-screen). Boot logs are back to normal.
  `vw-logo.avif` is kept in the repo. If retrying, prefer a built-in plymouth image theme over a
  hand-written script theme, and you'll need the owner to confirm placement on the real screen.

## The QML build (parallel UI, 2026-08-04)

A full Qt Quick port of the cluster lives alongside the Kivy one — same three layouts
(street / detail / map), tell-tales incl. bulb check, intro sweeps, demo mode,
flash-and-hold gesture. (The Kivy build's bottom alarm banner was **removed from the QML
build** 2026-08-05, owner's call — the critical alarms already blink in the tell-tale
row; `AlarmBar.qml` deleted, `alarms` dropped from the bridge. The map HUD also lost its
coords readout, and gained the top-left NowPlaying.) **DEPLOYED 2026-08-06: the QML
build is now the car's boot service** (installed by `tools/pi/make_permanent.sh`;
launcher env: eglfs + `tools/pi/eglfs_kms.json` → /dev/dri/card1, `QSG_RENDER_LOOP=basic`,
`CAN_DEBUG=false`; map redraw ~2 ms/frame on the Pi). The Kivy build stays in the repo
as the fallback — `start-can-cluster.sh.kivy` on the Pi restores it. The QML build
goes beyond the Kivy build in three deliberate ways: layouts
switch via an infinite vertical carousel slide (300 ms; every switch slides up — a
continuous `carouselPos` only ever advances and slots sit at wrapped offsets), the view
runs 4x MSAA, and night mode is **palette-level** instead of the Kivy black veil —
`Theme.d()` dims informational colours to ~45% while tell-tales, alarms, the shift
light and EGT status dots stay full-brightness (the custom `ring_item`/`map_item`
take a `dim` property since their colours never pass through QML).

- **Files:** `qml/` (all QML; `Theme.qml` mirrors `theme.py` — checked by
  `tools/check_theme_sync.py`, run it after touching either), `cluster_qml.py`
  (SensorBridge QObject; QML is presentation only), `map_item.py` / `ring_item.py`
  (custom scene-graph items), `start_cluster_qml.py` (thread launcher twin).
  Backend (`model`, `demo`, `gesture`, `can/gpio/gps_helper`) is shared unmodified.
- **Shared decision/geometry modules (2026-08-05 refactor — BOTH builds consume
  these; edit them, not per-build copies):** `decisions.py` (all thresholds,
  the PILLS spec incl. icons/colour names, `compute_pills`/`compute_alarms`,
  `BulbCheck`, `wifi_connected`, intro-sweep timing, layout names/startup),
  `dial_spec.py` (big-dial geometry + comet-trail hue; BigDial.qml reads it via
  the bridge's constant `dial`/`intro` maps), `map_geometry.py` (map projection
  constants, road styles, `RoadMap` culling/clipping, `SmoothedPose`, ribbon
  extrusion — map_view.py and map_item.py are thin adapters; verified
  pixel-identical to the pre-refactor renderer), `demo.DemoFeed` (no-CAN feed).
- **SensorBridge emits per-property change signals** (generated in the class
  body from `_SENSOR_FLOATS`), not one global tick signal: `tick()` compares
  each mirrored value and fires only what moved, so steady sensors cost no QML
  binding re-evaluations. CenterInfo's micro-grid is static `MicroCell`
  instances with per-sensor bindings — don't turn it back into a per-tick JS
  array model (that recreated all 8 delegates every 33 ms).
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
- **Pi bring-up REHEARSED 2026-08-05, made PERMANENT 2026-08-06** (via
  `tools/pi/make_permanent.sh`). The rehearsal: the QML build ran 30 s on the car's panel under eglfs
  with zero Qt errors, live ECU CAN flowing, all reader threads healthy, Kivy service
  restored after. The verified recipe (redo all of this in `--rw` to make it stick):
  1. `pip install PySide6-Essentials==6.7.3` into root's poetry venv
     (`/root/.cache/pypoetry/virtualenvs/can-cluster-jqod14ML-py3.11`; the
     manylinux_2_31 wheel installs fine on bookworm glibc 2.36).
  2. `apt-get install libfontconfig1 libxkbcommon0 libinput10` — Qt needs these and
     the Kivy/SDL stack never pulled them in (first failure mode: libfontconfig).
  3. **The PySide6 wheel omits `libQt6EglFsKmsGbmSupport.so.6`** (manylinux forbids
     linking libgbm), which breaks the whole eglfs_kms integration ("Failed to load
     EGL device integration eglfs_kms"). Fix: copy `tools/pi/
     libQt6EglFsKmsGbmSupport.so.6.7.3` (kept in-repo; extracted from official Qt
     6.7.3 linux_arm64 qtbase via `aqt install-qt linux_arm64 desktop 6.7.3
     --archives qtbase`) into the wheel's `PySide6/Qt/lib/` + symlink `.so.6` — the
     plugin's rpath then finds it. Same-version official Qt, so the private ABI matches.
  4. **KMS device must be `/dev/dri/card1`** (card0 is the v3d render node with no
     KMS — default gives "drmModeGetResources failed"). Launcher env:
     `QT_QPA_PLATFORM=eglfs QT_QPA_EGLFS_KMS_CONFIG=<json>` with
     `{ "device": "/dev/dri/card1" }`, plus `QSG_RENDER_LOOP=basic`, `DEV=false`.
     The panel's preferred 1920×720 mode is picked automatically — no mode config
     needed.
  5. Stop `can-cluster.service` first (it holds the DRM master); keep it as the boot
     service / fallback until the QML build has eyes-on-screen approval.
- Fonts: Kivy's "bold" is Compagnon-**Medium** + synthetic bold — QML must use
  `font.bold: true` over Medium. `Compagnon-Bold.otf` is a decorative outline face
  that looks nothing like the cluster's digits; don't use it. **Qt trap (found
  2026-08-06): every Compagnon file reports the same family name ("Compagnon") and
  Light mislabels its weight as 400/Normal, so `Theme.fontMain` and `Theme.fontLight`
  are the identical string and a plain `fontMain` request silently renders LIGHT.**
  Any non-bold `fontMain` text must pair with `font.weight: Theme.weightMain`
  (600 = exact match on Medium); bold texts already land on Medium via weight 700.
  Kivy is immune (it registers the Medium *file* as the default font).

## Conventions

- `DEV` (env, default `true`): halves the window + density 1 for desktop preview. **Production
  launcher sets `DEV=false`** (full window, no demo-loop interference). Don't rely on `DEV` for
  the no-CAN demo — that's keyed off `since_can()`, independent of `DEV`.
- Match existing style: `theme.py` holds all colours/sizes; widgets pull from it. Fonts are loaded
  by path (`fonts/ShareTechMono-Regular.ttf`, etc.) so the working dir must be the repo root
  (the systemd launcher `cd`s there).
- Changes are typically left **uncommitted** unless the owner asks to commit.
