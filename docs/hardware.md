# Hardware

Parts, wiring and the physical cautions for the Bamnun device. Moved here from
the main README, which now covers the whole system. The actuator list is
updated to what is actually wired: the Peltier cold-air stage and the piezo
buzzer were dropped, and the speakers, blue LED and CO₂ sensor were added.

## Pi pin map (as built)

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

The actuator pins are held low from boot with `gpio=17,24,25=op,dl` in
`config.txt`. Without it they float until the app claims them, and a floating
MOSFET gate half-switches its load: the blue LED lit when a finger touched
ground. `tools/run_pi.sh` drives them low again when the program exits, for
the same reason.

## Wiring cautions

- Common ground between the Pi and the 12 V supply; never share the 5 V rail.
- Flyback diode across any fan; it is an inductive load.
- `RPi.GPIO` does not work on the Pi 5 (new RP1 I/O controller). Use
  `gpiozero` with the `lgpio` backend. Half the tutorials you will find are
  wrong about this.
- Current mediapipe has **no** `mp.solutions.face_mesh`; that legacy API is
  gone. Only the Tasks API exists, which is what this code uses. Most
  tutorials online still use the old one.
- The thermal (Peltier) stage was dropped. Its code is still in `alerts.py`
  but nothing in the config uses it. If it ever comes back: the hot side
  **must** be heatsunk and fanned before you energise it. Unsunk, it will
  reach a temperature that destroys the module and can burn a finger.

## On IR wavelength — a real trade-off, and good poster content

850 nm gives noticeably better sensor response (the IMX708's QE at 940 nm is
roughly a third of its 850 nm figure), so you get shorter exposures and less
motion blur. But 850 nm emitters show a visible dim red glow, which a driver
will notice at night and may find distracting. 940 nm is genuinely invisible
and costs you light.

Buy both, measure the achievable exposure time and the landmark confidence at
each, and put the comparison in the report.

**Eye safety is a real constraint, not a formality.** Near-IR does not trigger
the pupillary or aversion reflex, so the usual protective behaviour is absent
and the exposure limits in IEC 62471 matter. Practical rule for this build:
use several low-power diffuse emitters at 40 cm or more rather than one bright
point source close in, keep total irradiance at the cornea low, and run them
only when the system is active (the code switches the IR LED on only for the
`picamera` source). This is exactly the kind of item to raise with a faculty
member and cite.

## Bill of materials

Prices are rough KRW estimates from memory and **must be checked** — treat the
column as a budget sketch, not a quote. Suppliers that stock all of this
domestically with 1–2 day delivery: 디바이스마트, 엘레파츠, 아이씨뱅큐,
메카솔루션.

### Critical path

| # | Part | Why | Est. KRW |
|---|---|---|---|
| 1 | **Raspberry Pi Camera Cable, 22-pin to 15-pin** (200 mm and 500 mm) | **The single most common Pi 5 blocker.** The Pi 5 has 22-pin 0.5 mm MIPI connectors. Camera Module 3 ships with a 15-pin 1.0 mm cable that does not fit. | 5,000 ×2 |
| 2 | Camera Module 3 NoIR (IMX708, wide or standard) | Standard 75° FoV is the better pick for a single driver at 50–70 cm; the 120° wide version wastes pixels on the passenger seat. | 40,000 |
| 3 | microSD, 64 GB A2/U3 (SanDisk Extreme or Samsung Pro Plus) | A1 cards make the Pi 5 feel broken. | 15,000 |
| 4 | Raspberry Pi 5 Active Cooler | Sustained landmark inference will thermally throttle a bare Pi 5 within minutes, and a throttled Pi silently halves your frame rate. | 9,000 |
| 5 | 850 nm and 940 nm IR LEDs | The NoIR sensor has no illuminator of its own. | 6,000 |
| 6 | Resistor assortment, breadboard, jumper wires (M-M, M-F) | | 12,000 |

### Actuators

| # | Part | Notes | Est. KRW |
|---|---|---|---|
| 7 | Ultrasonic atomizer with driver board | Peppermint stage. Get the one with the driver PCB, not the bare disc. | 8,000 |
| 8 | Logic-level MOSFET modules ×4 (IRF520 or IRLZ44N breakout) | The Pi's 16 mA per pin cannot drive any actuator directly. | 8,000 |
| 9 | Blue LED (~460 nm), dimmed by PWM | Stage 1. | — |
| 10 | INMP441 mic + 2× MAX98357A amps + speakers | Chime, voice and alarm, and recording the voice prompts. | — |
| 11 | SCD41 CO₂ sensor | Cabin air. | — |
| 12 | Peppermint essential oil | | — |

### Demo rig

| # | Part | Notes | Est. KRW |
|---|---|---|---|
| 13 | Gooseneck / articulated phone mount, or 1/4" ball head + clamp | The camera mount decides whether calibration holds. Rigid beats adjustable. | 10,000 |
| 14 | 7" HDMI display, or borrow a monitor | The overlay is part of the demo. Judges cannot see a GPIO pin go high. | 40,000 |
| 15 | Foam board / acrylic for a mock dashboard, plus a chair | | 20,000 |

The sensing half of this is under 80,000 KRW, against 1,500,000+ KRW for a
factory driver-monitoring option.
