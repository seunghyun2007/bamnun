# Bamnun (밤눈): a night-time drowsiness monitor for drivers

Bamnun is a small device on the dashboard that watches the driver's eyes with
an infrared camera and wakes them gently, long before it's too late. It runs
on a Raspberry Pi 5. When the driver gets drowsy it climbs a four-step
wake-up ladder: a dim blue light, a burst of mint mist, a chime with a spoken
warning, and finally a rising alarm. A phone app shows what the device sees,
live, and will later hold the trip history.

The Pi does all the safety work by itself. The phone is a window onto it: if
the phone is off, locked or out of range, the ladder still runs.

Built for the 2026 연세-넥슨 √i RC창의플랫폼.

---

## Contents

1. [See it in 1 minute (nothing to install)](#1-see-it-in-1-minute-nothing-to-install)
2. [What works today](#2-what-works-today)
3. [How it works](#3-how-it-works)
4. [Running it](#4-running-it)
5. [The phone app](#5-the-phone-app)
6. [Live data: the API](#6-live-data-the-api)
7. [Configuration](#7-configuration)
8. [Tools](#8-tools)
9. [Tests](#9-tests)
10. [Session logs](#10-session-logs)
11. [Design decisions worth defending](#11-design-decisions-worth-defending)
12. [Known limitations](#12-known-limitations)
13. [Troubleshooting](#13-troubleshooting)
14. [Repository map](#14-repository-map)
15. [Documents](#15-documents)

---

## 1. See it in 1 minute (nothing to install)

Double-click **`frontend/Bamnun_app.html`**. It opens in any browser, on a
computer or a phone.

Opened like that, the app plays a **simulated driver**, labelled
"Demo · simulated driver" on the Home screen. Over two and a half minutes
you'll see calibration, normal driving, an empty seat, a glance away from the
road, then drowsiness climbing the whole ladder, with Ollie the owl getting
sleepy and then alarmed. Tap the camera tile on Home for the Camera screen.

The demo is played by the page itself, so it shows what the screens do, not
what the detector measures. To see real detection, run the device (section 4).

---

## 2. What works today

| Part | State |
|---|---|
| Camera capture (Pi camera, webcam, video file) | Done. Pi camera path runs on the Pi 5 |
| Face landmarks (MediaPipe) | Done. Needs the model download (section 4) |
| Eye closure, PERCLOS, blinks, microsleeps, yawns, head pose, gaze | Done, tested |
| Drowsiness and distraction estimate | Done, tested |
| Rest prediction | Done; its time estimate is jittery (section 12) |
| Four-stage wake-up ladder | Done, tested. Runs on the real parts on the Pi, as logging stubs elsewhere |
| CO₂ reading and "open the window" prompt | Done. Needs `smbus2` on the Pi |
| Demo mode on the device (keys fire each stage) | Done |
| **Live data server** (`--serve`): app, `/api/health`, `/ws` | **Done, new.** Tested |
| **Live Home and Camera screens** in the app | **Done, new.** Tested in a browser |
| Simulated driver, served (`tools/sim_server.py`) and in-app demo | **Done, new** |
| Android and iOS app projects (Capacitor) | Created, not yet compiled (needs Android Studio, and a Mac for iOS) |
| Voice prompts | Recording tool done; recordings not in the repo |
| Trips, insights, settings sync, calibration from the phone, Bluetooth setup, route, emergency contact | Not started. Planned in `docs/SPEC.md`, section 10 |
| Validation on real IR footage from several drivers | Not started |

---

## 3. How it works

### The device

```
camera (IR, 30 fps)
  │
  ▼
landmarks   478 face points per frame (MediaPipe)
  │
  ▼
features    eye openness, PERCLOS, blinks, microsleeps, yawns, head pose, gaze
  │
  ▼
state       drowsiness score and level  +  a separate "eyes off the road" signal
  │
  ├──▶ predictor   when will this driver become unsafe? suggest a break
  │
  ▼
alerts      the wake-up ladder, paced by cooldowns
  │
  ├──▶ blue light · mint mist · chime + voice · rising alarm   (GPIO, speakers)
  │
  └──▶ telemetry   numbers only  ──▶  server (own thread)  ──▶  phone app
```

Each layer depends only on the one above it, so any one can be replaced, for
example the hand-weighted drowsiness score by a model trained on the logs,
without touching the rest.

### Measuring drowsiness

- **Calibration first.** For 12 seconds the driver looks ahead and blinks
  normally. The device learns *this driver's* open-eye level and forward head
  pose, and saves them, so a repeat run doesn't recalibrate. Nothing alerts
  before calibration is done.
- **Eye openness** is the eye aspect ratio (EAR) divided by the calibrated
  open level. The eye counts as closed below 65% of the driver's own level, so
  narrow eyes are never mistaken for sleep.
- **PERCLOS** is the share of the last 60 seconds with the eyes closed,
  integrated over time so a dropped frame doesn't skew it.
- **Microsleeps**: an eye shut for 0.5 s or more is reported *while it is
  still shut*, so the alarm can sound during the event.
- **The drowsiness score** is a transparent weighted sum of PERCLOS, blink
  duration, microsleeps, yawns and head nodding. A level is entered on the
  score *or* on PERCLOS alone (5 / 10 / 15 / 20%), so each stage can be quoted
  against a published threshold. Sources: `docs/thresholds.md`.
- **Distraction** is its own channel: a head turned outside the forward cone
  for over 2 seconds (NHTSA's guideline), or eyes down with the head forward
  (the phone-in-the-lap case). Mirror checks get a little longer.

### The wake-up ladder

| Stage | Entered at | What happens | Why this stimulus |
|---|---|---|---|
| 1 | a bit drowsy | dim blue light, held 30 min | blue light suppresses melatonin, which takes tens of minutes |
| 2 | drowsy | + 10 s mint mist | peppermint wakes the senses fast, and doesn't fade like a repeated tone |
| 3 | very drowsy | + slow chime, then a spoken warning | a conscious, clear advisory |
| 4 | extreme, or any microsleep | + 3 Hz alarm rising 30 dB, voice, long mint burst | strong, but rising rather than a startling blast at the wheel |

- The ladder climbs one stage per cooldown, never several stages in one
  instant. A microsleep jumps straight to stage 4.
- A glance away from the road gets one short chime and leaves the ladder alone.
- Each actuator has a refractory period and an hourly budget. Mint, for
  example, waits 2 minutes between bursts, because the nose adapts quickly.
- An empty seat chimes only every 45 s, not every 10.

### The phone link

- The Pi runs a small FastAPI server on its own thread. It serves the app at
  `/`, the device's status at `/api/health`, and a live stream at `/ws`.
- The camera loop never waits for it. It drops its latest numbers into a
  shared "hub" (`src/bamnun/telemetry.py`) and moves on; the server reads from
  the hub at its own pace. A crashed server, a slow phone or no phone at all
  change nothing about when the ladder fires.
- **Video only goes to the driver's phone, never online.** The Pi streams
  its camera to the app's Camera screen only while that screen is open, with
  the tracked eye outlines drawn on, and encodes nothing when nobody is
  watching. It is never recorded or uploaded. Everything else is numbers.

---

## 4. Running it

There are three ways, from least to most setup.

### A. A simulated driver, served (Python only)

Shows the app with live data from the real drowsiness and alert pipeline,
fed by a synthetic driver. No camera needed.

```bash
pip install -r requirements.txt          # once
python tools/sim_server.py               # an 8-minute drive, on repeat
```

Open <http://localhost:8000>. From a phone on the same Wi-Fi, use
`http://<this computer's address>:8000`. Options: `--minutes 3` for a
faster drive, `--once` to stop after one, `--port`.

### B. Real detection on a laptop webcam

```bash
python -m venv .venv
.venv\Scripts\activate                   # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python tools/download_models.py          # ~3.7 MB face model
python -m bamnun.app --source webcam --serve
```

- A preview window opens with the overlay. Press `c` to recalibrate, `s` for
  a snapshot, `a` to toggle the actuators, `q` to quit.
- Open <http://localhost:8000> for the app with *your* live data. Close your
  eyes for two seconds and watch the stage change on the phone screen.
- Without GPIO, every actuator logs instead of firing, so the whole ladder is
  exercised safely.
- If the webcam picks the wrong camera, use `--device 1` (see
  `config/laptop.yaml`).
- Tested on Windows with Python 3.14 and MediaPipe 1.2 on a laptop webcam
  (about 30 fps). The Pi uses Python 3.13; `requirements.txt` picks the right
  MediaPipe for each.

### C. On the Raspberry Pi 5

One-time setup, on Raspberry Pi OS (64-bit, bookworm or trixie):

```bash
bash setup_pi.sh                 # apt packages, venv, Python packages, model, self-test
source .venv/bin/activate
pip install -r requirements.txt  # again after this update, for the server packages
pip install smbus2               # CO2 sensor; setup_pi.sh doesn't install it yet
python tools/focus_sweep.py      # pin the camera's lens position first
```

Run:

```bash
./tools/run_pi.sh --serve                # camera, preview window, app on :8000
./tools/run_pi.sh --serve --no-window    # headless
./tools/run_pi.sh --serve --demo         # showcase: keys 1-4 fire each stage, t runs a tour
```

Then open `http://<the Pi's address>:8000` on a phone on the same network
(`hostname -I` on the Pi prints the address).

- `run_pi.sh` sets up the display for the preview window and drives the
  actuator pins low again when the program exits.
- The venv must be made with `--system-site-packages`, because `picamera2`
  only comes from apt. `setup_pi.sh` does this.
- `./tools/install_desktop_entry.sh` adds desktop icons for the monitor and
  the demo.
- The Pi doesn't make its own Wi-Fi hotspot yet, and the program doesn't
  start at boot yet. Both are in the spec.

### Command-line options

`python -m bamnun.app --help` lists them all. The main ones:

| Option | Meaning |
|---|---|
| `--source picamera\|webcam\|video` | where frames come from |
| `--device N` or `--device file.mp4` | webcam index, or video path |
| `--serve` | serve the app and live data |
| `--host`, `--port` | where to serve (default `0.0.0.0:8000`) |
| `--no-window` | run without the preview window |
| `--no-alerts` | detect, but never actuate |
| `--demo` | showcase mode with short timings |
| `--hours-awake H` | the driver's hours since waking, for the rest prediction |
| `--duration S`, `--tag NAME` | stop after S seconds; label the log files |
| `--fast`, `--loop` | video source: run flat out; loop the file |
| `--calibration FILE` | load a saved calibration |
| `--config FILE` | YAML merged over `config/default.yaml` |

---

## 5. The phone app

The app lives in `frontend/`. It is plain HTML, CSS and JavaScript built into
one file, wrapped with Capacitor for Android and iOS. See
`frontend/README.md` for the details.

- **Screens**: onboarding (language, welcome, meet Ollie, name, vehicle, work
  week, voice, wake-up ladder, privacy, permissions, connect, calibrate, all
  set), route, Home, Camera, Trips, Insights and Settings. English and Korean
  throughout.
- **Live today**: Home's "Right now" card (status, sleepiness gauge, eyes
  closed %, blinks per minute, trip time), the camera tile, cab air, the
  wake-up steps (the current stage lights up), Ollie's mood, and the whole
  Camera screen: the device's live video with eye outlines, eye state, frame
  rate, last blink and head direction. Without a camera (the demo or
  `sim_server.py`) the Camera screen shows a drawn face whose eyes follow the
  numbers instead.
- **Still sample data**: name, last trip, trips, insights, settings, route.
  Those come with the later steps of the spec.
- **Ways to open it**:
  - `frontend/Bamnun_app.html` from disk: demo driver, nothing installed;
  - from the device or `sim_server.py`: `http://<address>:8000`;
  - any copy with `?pi=192.168.0.12:8000` in the address: talk to that device;
  - `?demo` in the address: the demo driver anywhere.
- **Rebuild** after changing a screen:
  `python frontend/build/build.py frontend/screens frontend/www/index.html,frontend/Bamnun_app.html frontend/ollie`
  from the repo root. It needs only Python.
- **Native apps**: `cd frontend && npm install && npm run sync`, then
  `npx cap run android` (needs Android Studio) or `npx cap open ios` (needs a
  Mac). What needs a Mac or a paid Apple account: spec section 12.

---

## 6. Live data: the API

Full contract: `docs/SPEC.md`, section 1. What exists today:

### `GET /api/health`

```json
{
  "device": "bamnun-pi",
  "version": "0.1.0",
  "calibrated": true,
  "gpio": true,
  "parts": {
    "camera": "picamera",
    "ir_light": "ok",
    "blue_light": "ok",
    "mist": "ok",
    "speakers": "ok",
    "co2": "ok"
  },
  "camera_live": true
}
```

A part is `ok`, `simulated` (no hardware, or nothing to play), `missing`
(failed to start) or `off`. `camera_live` is false when the camera loop
hasn't published for 2 seconds.

### `GET /video`

The camera as MJPEG, about 10 frames per second, 480 px wide, with the eye
outlines drawn on. The app's Camera screen shows it as an ordinary image. The
Pi encodes frames only while at least one `/video` stream is open, and drops
the last frame when the last viewer leaves. It answers 404 when there is no
camera, as on the simulated device. `"video": true` in `/api/health` and in
each snapshot says it's available.

### `WS /ws`

The server sends JSON messages with a `type`:

- **`snapshot`**, 5 per second:

  | Field | Meaning |
  |---|---|
  | `face` | a face is in view |
  | `eye_open` | eye openness, 1.0 = this driver's normal open level; `null` with no face or while calibrating |
  | `eye_closed` | eyes count as closed right now |
  | `blink_rate` | blinks per minute |
  | `perclos` | share of the last 60 s with the eyes closed, 0–1 |
  | `last_blink_s` | length of the last normal blink |
  | `microsleep` | eyes shut 0.5 s or more, right now |
  | `stage`, `stage_name` | wake-up ladder stage 0–4 (`none`, `light`, `scent`, `chime`, `emergency`) |
  | `level`, `level_name`, `score`, `kss` | drowsiness level, score 0–1, sleepiness 1–9 (display only) |
  | `distracted`, `distraction_reason` | eyes-off-road channel |
  | `yaw`, `off_road` | head turn in degrees (negative = driver's left), outside the safe zone |
  | `calibrated`, `calibrating`, `cal_progress` | calibration state |
  | `co2_ppm`, `co2_age_s` | cabin CO₂ and the reading's age |
  | `trip_s` | seconds since the program started |
  | `fps` | frames processed per second |
  | `age_s`, `stale` | snapshot age; `stale` after 2 s |

  Values that weren't measured are `null`, never a guess.

- **`alert`**, as soon as the stage changes: `stage`, `stage_name`,
  `previous`, `reason`, `fired` (the parts that went off), `time`.

The phone sends `{"type": "hello", "time": <ms>, "lang": "en", "tz": "..."}`
on connecting, because the Pi has no reliable clock.

Try it without the app: `curl http://localhost:8000/api/health`, and in any
browser's developer console,
`new WebSocket("ws://localhost:8000/ws").onmessage = e => console.log(e.data)`.

---

## 7. Configuration

Every tunable is in `config/default.yaml`, with a comment saying why it has
that value. `--config other.yaml` merges a file over it, as
`config/laptop.yaml` does to pick a different webcam.

| Block | Holds |
|---|---|
| `capture` | camera source, resolution, frame rate; Pi camera exposure, gain and pinned focus; IR LED pin |
| `landmarks` | face model path and confidence thresholds (lowered for IR) |
| `features` | eye-closure fractions, PERCLOS window, blink and yawn timing, head cone, permitted mirror glances |
| `calibration` | duration, quality bar, head-pose gate, where it's saved |
| `state` | score weights, the four levels (score and PERCLOS gates, dwell times), face-loss grace |
| `predictor` | rest-prediction window and model shape |
| `alerts` | the stages, their actuators and cooldowns, the distraction chime, each actuator's pin, sound file, refractory and budget |
| `air` | CO₂ sensor and the open-window thresholds |
| `logging`, `ui` | log folder and rate; overlay options |

Where each threshold comes from (published, physical, or our choice):
`docs/thresholds.md`.

---

## 8. Tools

| Command | Purpose |
|---|---|
| `python tools/sim_server.py` | serve the app with a simulated driver through the real pipeline |
| `python tools/simulate.py --minutes 45` | a synthetic 45-minute drive through the real decision stack, written to CSV |
| `python tools/download_models.py` | fetch the MediaPipe face model |
| `python tools/focus_sweep.py` | find the sharpest Pi camera lens position |
| `python tools/bench.py --seconds 30 --source picamera` | per-stage timing and frame rate |
| `python tools/measure_glance_zones.py` | measure the mirror zones in the real cab |
| `python3 tools/record_prompts.py` | record the spoken prompts with the Pi's mic (`--list`, `--only NAME`) |
| `python tools/make_chime.py` | regenerate the alert tones in `assets/` |
| `python tools/render_overlay_demo.py` | the overlay in every state, as one image |
| `python tools/make_icon.py` | the desktop icon |
| `./tools/run_pi.sh` | start the monitor on the Pi with the display set up |
| `./tools/install_desktop_entry.sh` | Pi desktop icons |

---

## 9. Tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -q        # 226 tests
```

- The suite never touches real hardware: on the Pi, gpiozero is pointed at a
  mock (`tests/conftest.py`).
- The server tests skip if FastAPI isn't installed, so an older Pi setup
  still passes.
- `tests/test_hardware_map.py` fails if an actuator is ever put on a sound or
  sensor bus pin.

---

## 10. Session logs

Every run writes to `runs/` (not in git):

- `*_frames.csv`: every feature at 10 per second, from the end of calibration;
- `*_events.jsonl`: each alert, closure, CO₂ reading and demo action;
- `*_meta.json`: the exact config and arguments used;
- `calibration.json`: the saved calibration.

The CSV is the training set for any later learned model, and the source for
every number in the report.

---

## 11. Design decisions worth defending

**Closure thresholds are relative to the driver, not absolute.** The usual
EAR threshold of 0.21 fails on narrow eyes, which are common in Korean
drivers: someone whose fully open EAR is 0.17 reads as permanently asleep.
Closure is 65% of *their* calibrated value. There's an end-to-end test for
exactly this case.

**Drowsiness and distraction are separate channels.** They have different
evidence, different time scales and different correct responses. One number
for both either responds late to distraction or flaps on drowsiness.

**Microsleeps are reported while the eye is still shut.** A measure that only
fires on reopening can't alert during the event it exists to catch.

**PERCLOS is integrated over time, not averaged over frames.** A dropped frame
doesn't silently change it.

**The ladder is paced by cooldowns, not the frame rate.** "One stage per
update" at 25 Hz would fire every stage in under 200 ms.

**Each stage uses the stimulus that fits its time scale.** Blue light for 30
minutes (melatonin takes tens of minutes), mint for a fast jolt that resists
habituation, a slow chime and voice, then an alarm that rises rather than
starts at full volume, to avoid a startle at the wheel.

**The prediction blends slopes, not levels** (`predictor.py`). Blending
predicted levels puts a jump at the present and bends the curve back down, so
a measurably worsening driver is told to keep going.

**Nothing alerts before calibration completes.** A false alarm in front of a
judge costs more than a miss.

**The phone can't slow the ladder down.** The server is a reader on its own
thread; the camera loop only hands it numbers. Every publishing step is
guarded, so even a bug there can't stop detection.

**Video goes to the driver's phone and nowhere else.** It travels only over
the local network, only while the Camera screen is open, and is never stored.
The rest of the time the link carries a few hundred bytes five times a
second, and the Pi spends nothing on encoding.

---

## 12. Known limitations

1. **MediaPipe was trained on visible-light faces.** It works on infrared
   images with lower confidence; thresholds are lowered to 0.4.
   `docs/ir_fallback.md` has the plan if it proves unreliable.
2. **Glasses are untested.** IR reflection off lenses is the classic failure
   of every camera-based monitor.
3. **The sleepiness 1–9 (KSS) number is presentation only**, not a validated
   measure.
4. **The rest-prediction time is jittery**, swinging between 15 and 78 minutes
   on consecutive updates. It should be smoothed before it's shown to drivers.
5. **No ground truth yet.** A cheap substitute: ask the driver for a KSS
   rating every five minutes while recording.
6. **One test driver so far.** More people, with different eye shapes and at
   least one glasses wearer, would matter more than any new code.
7. **The live server has no login.** Anyone on the same network can read the
   live numbers **and open the camera video**. Fine on the Pi's own
   password-protected hotspot once it exists; until then, don't run `--serve`
   on a shared network (school, café) with a driver in view.
8. **Trip time is time since the program started**, until trips exist.
9. **The phone app is only partly live**; see section 5.

---

## 13. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The app shows "Not connected" | The device isn't reachable at that address. Open the exact `http://<address>:8000` the Pi uses, or add `?pi=<address>:8000`. Phone and Pi must be on the same network |
| The app says "No camera" | The camera loop stopped sending: check the program's console |
| The Camera screen shows a drawn green face, not video | Expected with the demo or `sim_server.py`, which have no camera. With a real camera: check `/api/health` says `"video": true`, and that the address is reachable |
| `--serve needs fastapi and uvicorn` | `pip install -r requirements.txt` |
| Port 8000 already in use | Detection keeps running without the server. Use `--port 8001`, or stop the other program |
| Calibration keeps restarting | The console says why: no face, head turned more than 30°, or too few frames. Face the camera squarely and check the lighting |
| Preview window fails on the Pi with "platform plugins: xcb" | Start it with `./tools/run_pi.sh`, which sets the display |
| "no cameras available" on the Pi | The cable: the Pi 5 needs the 22-pin to 15-pin camera cable |
| The webcam opens but every frame is black | Wrong camera index (often a virtual camera). Try `--device 1` |
| CO₂ always shows "Sensor offline" | `pip install smbus2`, and check the SCD41 on I2C address 0x62 |
| On Windows, a `ConnectionResetError` in the log | Harmless: a browser tab closed its connection abruptly |
| `build.py` fails with a Unicode error | It shouldn't any more; pull the latest `frontend/build/build.py` |

---

## 14. Repository map

```
bamnun/
├── README.md               this file
├── config/
│   ├── default.yaml        every tunable, with reasons
│   └── laptop.yaml         example override: a different webcam
├── docs/
│   ├── SPEC.md             the app and backend spec: the source of truth
│   ├── hardware.md         pin map, wiring cautions, parts list, IR eye safety
│   ├── thresholds.md       where each threshold comes from
│   ├── ir_fallback.md      plan B if face tracking fails on infrared
│   └── original-readme.md  the original README, unchanged
├── src/bamnun/
│   ├── app.py              the main loop; --serve starts the server
│   ├── capture.py          Pi camera, webcam, video file; the IR LED
│   ├── landmarks.py        MediaPipe face landmarks
│   ├── features.py         eye openness, PERCLOS, blinks, head pose, gaze, calibration
│   ├── state.py            drowsiness score and levels; distraction
│   ├── predictor.py        rest prediction
│   ├── alerts.py           actuators and the wake-up ladder
│   ├── air.py              CO₂ sensor
│   ├── telemetry.py        the snapshot and the hub between the loop and the server
│   ├── server.py           FastAPI: the app, /api/health, /ws, /video
│   ├── session.py          config loading and session logs
│   ├── demo.py             showcase mode
│   └── viz.py              the preview overlay
├── tests/                  226 tests
├── tools/                  see section 8
├── assets/                 alert tones, icon; voice prompts go in assets/voice/
├── frontend/               the phone app: see frontend/README.md
│   ├── Bamnun_app.html     the whole app in one file: double-click to try it
│   ├── screens/            one file per screen
│   ├── build/              build script, shell, live data, translations
│   ├── android/  ios/      Capacitor projects
│   └── fonts/  ollie/      fonts and mascot images
├── requirements.txt        Python packages, with reasons
├── pyproject.toml          makes `python -m bamnun.app` work from anywhere
└── setup_pi.sh             one-time Pi setup
```

---

## 15. Documents

- `docs/SPEC.md`: how the app and backend should behave, the build order,
  Android and iOS differences, and open questions. Kept up to date first,
  before code changes.
- `docs/hardware.md`: the pin map, sound card setup, wiring cautions, IR eye
  safety, and the parts list.
- `docs/thresholds.md`: where every number in the config comes from.
- `docs/ir_fallback.md`: what to do if face tracking fails on infrared.
- `docs/original-readme.md`: the original README, kept word for word, including the September plan.
- `frontend/README.md`: building and running the app.

Coming up: Nov 10 exhibition · Nov 12 예심 · Nov 24 창의공모전.
