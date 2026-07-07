# CLAUDE.md — working notes for AI sessions

Context and hard-won facts for working on this repo. Read this before making changes.

## What this is

A digital gauge cluster for a **1992 VW Gol G1** (turbo, "Azul Boreal" blue). It runs on a
**Raspberry Pi 5** (Armbian, Debian bookworm) on a **1920×720** display, reading engine data
from a **FuelTech ECU over CAN (FTCAN 2.0)** and switch inputs over **GPIO**. UI is **Kivy**
(SDL2 / KMS-DRM, no desktop). The look is minimal/dark with an Azul Boreal blue accent
(modelled on a Claude Design mockup, "Painel Gol Minimal").

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
- The protocol spec (`Protocol_FTCAN20.pdf`, image-only — render with `pdftoppm -png` and Read the
  PNGs) also defines a **real-time *tagged* broadcast** (MessageID `0x_FF`, frame IDs like
  `0x140011FF`) where each measure is `MeasureID(2B)+Value(2B)`, `MeasureID = (DataID<<1)|statusbit`.
  **We do NOT read this yet.** Fan, 2-step/launch, and ECU output states only live here.
  - **2-step / launch:** `DataID 0x0007` "ECU Launch Mode" (nonzero = a launch mode armed), or
    `DataID 0x0048` "2 Step Signal" (Note 7 = 0:off/1:on).
  - **Radiator fan:** read via the dedicated `DataID 0x004D` "ECU Eletro Fan" measure (Note 7 =
    0:off/1:on) → `SensorState.radiator_fan`. (The fan is physically wired to gray output 3, but the
    ECU's electro-fan function reports its state on this measure regardless of output.) An alternative
    source is the **Generic outputs state** bitmask `DataID 0x0152` (Note 9: bit N = Output N+1 on).

## In-flight / TODO

- **Fan + 2-step tell-tales:** now fed by the tagged-broadcast reader in `can_helper.py`
  (`DATAID_LAUNCH 0x0008` → `two_step`, `DATAID_FAN 0x004D` "ECU Eletro Fan" → `radiator_fan`).
  Both still need a live verify on the car to confirm the ECU actually broadcasts them.
- **GPIO pin map is being discovered** by the owner via `./logs.sh gpio` (toggle a switch, see
  which GPIO logs `-> ON`). Known: `HIGH_BEAM=6, LEFT_INDICATOR=21, RIGHT_INDICATOR=16, CHOKE=13,
  PARKING_BRAKE=5`; `B=20, D=19, E=26` still unknown. `PARKING_BRAKE` → BRAKE pill, `HIGH_BEAM` →
  HIGH pill, `CHOKE` → CHOKE pill, indicators → ◄ ► arrows. **CHOKE is active-high** — it's in
  `gpio_helper.INVERTED`, so its reading is inverted vs. the active-low default of the other pins.
- A **plymouth VW-logo boot splash** was attempted and **fully reverted** (couldn't get the logo
  to composite without seeing the screen; logo went off-screen). Boot logs are back to normal.
  `vw-logo.avif` is kept in the repo. If retrying, prefer a built-in plymouth image theme over a
  hand-written script theme, and you'll need the owner to confirm placement on the real screen.

## Conventions

- `DEV` (env, default `true`): halves the window + density 1 for desktop preview. **Production
  launcher sets `DEV=false`** (full window, no demo-loop interference). Don't rely on `DEV` for
  the no-CAN demo — that's keyed off `since_can()`, independent of `DEV`.
- Match existing style: `theme.py` holds all colours/sizes; widgets pull from it. Fonts are loaded
  by path (`fonts/ShareTechMono-Regular.ttf`, etc.) so the working dir must be the repo root
  (the systemd launcher `cd`s there).
- Changes are typically left **uncommitted** unless the owner asks to commit.
