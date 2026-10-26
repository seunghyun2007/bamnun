# bamnun (밤눈) — IR driver state monitor

Low-cost near-infrared driver monitoring on a Raspberry Pi 5. Tracks eye
closure, blink dynamics, head pose and gaze under IR illumination; fuses them
into a drowsiness estimate and an independent distraction signal; predicts
when the driver will become unsafe; and escalates through a graded set of
arousal stimuli, including two that no consumer system uses.

Built for the 2026 연세-넥슨 √i RC창의플랫폼.

---

## Status

| Layer | State |
|---|---|
| Capture abstraction (Picamera2 / webcam / video) | done, Picamera2 path untested on hardware |
| MediaPipe landmark wrapper | done, needs the model bundle downloaded |
| Feature extraction (EAR, PERCLOS, blinks, pose, gaze, yawn) | done, 201 tests passing |
| State estimation (drowsiness + distraction) | done |
| Rest planning (trend + two-process alertness prior) | done |
| Graded alert policy | four stages (blue light → mint → slow chime → looming alarm), entered on the fused score or PERCLOS 5/10/15/20 %; actuators run as logging stubs without GPIO |
| Actuator hardware | atomizer, speakers, blue LED, IR LED and SCD41 wired (see the pin map below); thermal stage dropped; voice prompts not yet recorded |
| Real IR validation | not started |

```
python -m pytest tests/ -q          # 201 passed
python tools/simulate.py --minutes 45 --hours-awake 15
```

---

## Quick start

### On a laptop, before the camera arrives

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python tools/download_models.py          # ~3.7 MB MediaPipe bundle
python -m bamnun.app --source webcam
```

Press `c` to calibrate (look straight ahead for 12 s and blink normally), then
close your eyes for two seconds and watch the stage ladder fire in the
console. Actuators log instead of actuating when `gpiozero` is absent, so the
whole policy is exercised without hardware.

### On the Raspberry Pi 5

```bash
sudo apt install -y python3-picamera2 python3-libcamera libgl1 libglib2.0-0
python3 -m venv --system-site-packages .venv    # picamera2 comes from apt
source .venv/bin/activate
pip install -r requirements.txt gpiozero lgpio
python tools/download_models.py
libcamera-hello --list-cameras                  # confirm the sensor is seen
python -m bamnun.app --source picamera
```

The `--system-site-packages` flag is not optional. `picamera2` is an apt
package; a plain venv cannot see it and there is no working pip version.

---

## Architecture

```
capture     -> Frame           pixels + monotonic timestamp
landmarks   -> LandmarkResult  478 facial points (MediaPipe Tasks)
features    -> FeatureFrame    EAR, PERCLOS, blinks, head pose, gaze, yawns
state       -> DriverState     fused drowsiness score + independent distraction
predictor   -> RestPlan        forward projection and rest timing
alerts      -> AlertDecision   graded escalation across actuators
```

Each layer depends only on the one above it. The hand-weighted fusion in
`state` can be replaced by a model trained on the CSV logs without touching
anything else.

### Design decisions worth defending in the report

**Closure thresholds are relative to the driver, not absolute.** The published
EAR threshold of 0.21 fails on narrow eye apertures, which are common in
Korean drivers: a person whose fully-open EAR is 0.17 reads as permanently
asleep. The system calibrates each driver's open-eye EAR from a 12-second
baseline and expresses closure as 65% of *their* value. There is an end-to-end
test for exactly this case.

**Drowsiness and distraction are separate channels.** They have different
evidence, different time constants and different correct responses. Fusing
them into one number, as most implementations do, gives you a system that
either responds late to distraction or flaps on drowsiness.

**Microsleeps are reported while the eye is still shut.** A closure-duration
metric that only fires on reopening cannot alert during the event it exists to
catch. The tracker latches at 500 ms of continuous closure and the state
estimator bypasses its own dwell timer for it.

**PERCLOS is integrated over time, not averaged over frames.** A dropped frame
does not silently change the metric.

**The escalation ladder is paced by cooldowns, not by the frame rate.** Obvious
in hindsight, easy to get wrong: "advance one stage per update" at 25 Hz fires
every stage in under 200 ms.

**Each stage uses the modality that fits its timescale.** Stage 1 is a dim
blue light held for 30 minutes (melatonin suppression takes tens of minutes),
stage 2 adds a mint burst (trigeminal, fast, resists habituation), stage 3 a
slow 1 Hz chime plus a recorded voice, stage 4 a 3 Hz alarm that rises 30 dB
instead of starting at full volume, to avoid a startle at the wheel. A glance
away gets its own short chime and leaves the ladder alone. Rationale and
sources: the team research doc; check the primary references before quoting.

**The prediction blends slopes, not levels.** See `predictor.py`; blending
predicted levels puts a discontinuity at the present and, worse, bends the
curve back down so a measurably deteriorating driver is told to keep going.

**Nothing alerts before calibration completes.** A false positive in front of a
judge costs more than a miss.

---

## Bill of materials

Prices are rough KRW estimates from memory and **must be checked** — treat the
column as a budget sketch, not a quote. Suppliers that stock all of this
domestically with 1–2 day delivery: 디바이스마트, 엘레파츠, 아이씨뱅큐,
메카솔루션.

### Critical path — order today

| # | Part | Why | Est. KRW |
|---|---|---|---|
| 1 | **Raspberry Pi Camera Cable, 22-pin to 15-pin** (200 mm and 500 mm) | **The single most common Pi 5 blocker.** The Pi 5 has 22-pin 0.5 mm MIPI connectors. Camera Module 3 ships with a 15-pin 1.0 mm cable that does not fit. Buy both lengths; the long one is what you need once the camera is on a dashboard mount. | 5,000 ×2 |
| 2 | Camera Module 3 NoIR (IMX708, wide or standard) | Already chosen. Standard 75° FoV is the better pick for a single driver at 50–70 cm; the 120° wide version wastes pixels on the passenger seat. | 40,000 |
| 3 | microSD, 64 GB A2/U3 (SanDisk Extreme or Samsung Pro Plus) | A1 cards make the Pi 5 feel broken. | 15,000 |
| 4 | Raspberry Pi 5 Active Cooler | Sustained landmark inference will thermally throttle a bare Pi 5 within minutes, and a throttled Pi silently halves your frame rate. Non-optional for this workload. | 9,000 |
| 5 | 850 nm IR LEDs, 5 mm, ×10, plus 940 nm ×10 | The NoIR sensor has no illuminator of its own. It sees nothing in a dark cabin without these. Buy both wavelengths and measure; see the note below. | 6,000 |
| 6 | Resistor assortment, breadboard, jumper wires (M-M, M-F) | | 12,000 |

### Actuators — order today, they ship slower

| # | Part | Notes | Est. KRW |
|---|---|---|---|
| 7 | TEC1-12706 Peltier module + heatsink + 40 mm fan | Cold-air stage. **Needs a separate 12 V supply and a heatsink on the hot side.** Never off the Pi's rails. | 12,000 |
| 8 | Ultrasonic piezo atomizer, 20 mm 108 kHz, with driver board | Peppermint stage. Get the one with the driver PCB, not the bare disc. | 8,000 |
| 9 | Logic-level MOSFET modules ×4 (IRF520 or IRLZ44N breakout) | The Pi's 16 mA per pin cannot drive any of the above. | 8,000 |
| 10 | 12 V 5 A DC supply, or a 12 V→5 V car buck converter | Peltier current. | 12,000 |
| 11 | Piezo buzzer, 5 V blower fan (30–40 mm), peppermint essential oil | | 10,000 |
| 12 | Small thermocouple or IR thermometer | To report the actual ΔT the cold-air stage achieves. A measured number beats a claim. | 15,000 |

### Demo rig

| # | Part | Notes | Est. KRW |
|---|---|---|---|
| 13 | Gooseneck / articulated phone mount, or 1/4" ball head + clamp | The camera mount decides whether calibration holds. Rigid beats adjustable. | 10,000 |
| 14 | 7" HDMI display, or borrow a monitor | The overlay is the demo. Judges cannot see a GPIO pin go high. | 40,000 |
| 15 | Foam board / acrylic for a mock dashboard, plus a chair | | 20,000 |

Rough total: **250,000–270,000 KRW**, of which about 90,000 is the Pi-side
essentials. Worth noting on the poster: the sensing half of this is under
80,000 KRW against 1,500,000+ KRW for a factory DMS option, and the comparison
table is one of the things your own analysis of past winning posters
identified as decisive.

### On IR wavelength — a real trade-off, and good poster content

850 nm gives noticeably better sensor response (the IMX708's QE at 940 nm is
roughly a third of its 850 nm figure), so you get shorter exposures and less
motion blur. But 850 nm emitters show a visible dim red glow, which a driver
will notice at night and may find distracting. 940 nm is genuinely invisible
and costs you light.

Buy both, measure the achievable exposure time and the landmark confidence at
each, and put the comparison in the report. That is a physics measurement your
background makes easy and most teams will not do.

**Eye safety is a real constraint, not a formality.** Near-IR does not trigger
the pupillary or aversion reflex, so the usual protective behaviour is absent
and the exposure limits in IEC 62471 matter. Practical rule for this build:
use several low-power diffuse emitters at 40 cm or more rather than one bright
point source close in, keep total irradiance at the cornea low, and run them
only when the system is active. This is exactly the kind of item to raise with
a faculty member and cite — "expert consultation" and "honest limitations"
were both on your list of what distinguishes winning posters.

### Wiring cautions

- Common ground between the Pi and the 12 V supply; never share the 5 V rail.
- Flyback diode across the blower fan; it is an inductive load.
- The Peltier's hot side **must** be heatsunk and fanned before you energise
  it. Unsunk, it will reach a temperature that destroys the module and can
  burn a finger.
- `RPi.GPIO` does not work on the Pi 5 (new RP1 I/O controller). Use
  `gpiozero` with the `lgpio` backend. Half the tutorials you will find are
  wrong about this.
- Current mediapipe has **no** `mp.solutions.face_mesh`; that legacy API is
  gone. Only the Tasks API exists, which is what this code uses. Most
  tutorials online still use the old one.

### Pi pin map (as built)

| GPIO | Header pin | Connected to | Used by |
|---|---|---|---|
| 2 / 3 | 3 / 5 | SCD41 CO₂ sensor (I2C, 0x62) | `air`: logs CO₂, plays the open-window prompt |
| 17 | 11 | MOSFET board → ultrasonic mister (button bridged) | `alerts.actuators.scent` |
| 18 | 12 | I2S BCLK: INMP441 SCK + both MAX98357A BCLK | sound card |
| 19 | 35 | I2S LRCLK: INMP441 WS + both MAX98357A LRC | sound card |
| 20 | 38 | I2S data in: INMP441 SD | sound card |
| 21 | 40 | I2S data out: both MAX98357A DIN | sound card |
| 24 | 18 | MOSFET board → blue alertness LED (PWM-dimmed) | `alerts.actuators.blue_light` |
| 25 | 22 | MOSFET board → 3 W IR LED (built-in driver, 3–6 V, run at 5 V) | `capture.illuminator` |

The sound card is `dtoverlay=googlevoicehat-soundcard` in
`/boot/firmware/config.txt`, made the ALSA default in `/etc/asound.conf` so
`aplay` with no device reaches the speakers. Every sound actuator plays
through it; the piezo buzzer the chime was designed for would have sat on
GPIO18, which I2S now owns. `tests/test_hardware_map.py` fails if an actuator
is ever configured on an I2S or I2C pin.

The actuator pins are held low from boot with
`gpio=17,24,25=op,dl` in `config.txt`. Without it they float until the app
claims them, and a floating MOSFET gate half-switches its load: the blue LED
lit when a finger touched ground.

---

## Plan to the 27 September interim report

Seven days. The camera is the critical path and it is not in hand, so the week
is arranged so that a slipped delivery does not cost you the report.

**Sun 20 (today)** — Place every order above in one go; the 22-pin cable is the
part that will otherwise stall you for three days. Get the pipeline running on
your laptop webcam and confirm calibration behaves on your own face. Create the
report skeleton.

**Mon 21** — The 특강 및 멘토링 설명회 is today. Go, and use the mentoring slot
on the IR eye-safety question and on whether the exhibition venue allows a
12 V supply at your table. Meanwhile: flash Pi OS, headless setup, install
dependencies, confirm the test suite passes on the Pi.

**Tue 22 – Wed 23** — Camera work. `libcamera-hello --list-cameras`, then the
focus sweep (the IMX708 is a voice-coil autofocus module and hunting at 50 cm
will wreck your landmarks; `lens_position` must be pinned). Wire the IR LEDs,
darken a room, and find the exposure/gain pair that gives stable landmarks.
Measure and record frame rate at 1536×864.

**Thu 24** — Record real sessions on yourself: one alert, one after a genuinely
short night. Three to four ten-minute recordings. This is your only real data
and everything in the report's results section comes from it. Run the recorded
files back through `--source video` and produce the first PERCLOS and score
plots.

**Fri 25** — Breadboard the buzzer and the atomizer, which are the two easy
actuators, and get one end-to-end alert firing from a real closure. Peltier
only if the parts arrived; it is the one stage you can honestly report as "in
progress".

**Sat 26** — Write the report around the real numbers and plots. Structure it
as problem, evidence, method, measured results, honest limitations.

**Sun 27** — Buffer and submit.

### Then

Oct 27 창보고 전시 설명회 · Oct 28 23:59 final report + poster · Nov 10
exhibition · Nov 12 예심 · Nov 24 창의공모전.

Between the interim report and Oct 28 the work that moves the needle is not
more features. It is: real data from more than one person, a measured ΔT and
latency figure for the cold-air stage, the 850/940 nm comparison, and a
price-comparison table against commercial DMS. Your own reading of past
winning posters said problem selection and evidence decide this, not technical
novelty — so the schedule should protect the evidence, not the feature list.

---

## Tools

| Command | Purpose |
|---|---|
| `python -m bamnun.app --source webcam` | live monitor with overlay |
| `python -m bamnun.app --source video --device clip.mp4 --fast` | re-score a recording at full speed |
| `python tools/simulate.py --minutes 45` | synthetic 45-minute drive through the real decision stack |
| `python tools/download_models.py` | fetch the MediaPipe bundle |
| `python -m pytest tests/ -q` | 201 tests |
| `python tools/make_chime.py` | regenerate the alert tones in `assets/` |
| `python3 tools/record_prompts.py` | record the spoken prompts with the Pi's mic (`--list`, `--only NAME`) |

Session logs land in `runs/`: one CSV of per-frame features at 10 Hz, one JSONL
of alert and closure events, one JSON of the exact config used. The CSV is the
training set for any later learned model, and the provenance for every number
in the report.

---

## Known limitations

Worth stating plainly in the report; an honest limitations section was on your
own list of what winning posters share.

1. **MediaPipe's landmark model is trained on visible-light RGB faces.** It
   works on NoIR imagery but with reduced confidence. Thresholds are already
   lowered to 0.4. `docs/ir_fallback.md` has the plan if it proves unreliable.
2. **Glasses are unvalidated.** IR reflection off lenses is the classic failure
   mode of every camera-based DMS. Test early and report what happens.
3. **The KSS mapping is heuristic.** Score×8+1 is a presentation convenience,
   not a validated instrument. Say so rather than implying otherwise.
4. **The rest-plan ETA is jittery.** The Theil-Sen slope over a 10-minute
   window can swing the predicted crossing between 15 and 78 minutes on
   consecutive updates. The reported number should be smoothed, or only shown
   above a confidence floor.
5. **No ground truth.** Without a reference measure of sleepiness, none of
   the accuracy claims can be more than self-report plus observation. A
   defensible cheap substitute is a self-reported KSS every five minutes
   during recording, timestamped into the log.
6. **Single subject so far.** Two or three more people, with different eye
   shapes and at least one glasses wearer, changes the report's credibility
   more than any code you could write in the same time.
