"""Synthetic driver scenarios for validating detection (docs/detection-audit.md).

Each scenario is a sequence of per-frame MEASUREMENTS, the same things the
camera pipeline extracts from a face: each eye's aspect ratio and width, the
MediaPipe blendshapes, head pose relative to the camera, face size, image
brightness and whether the face is near the frame edge. They are generated
from a simple model of a driver, so the detector downstream (features, state,
alerts) runs exactly as it does on a real camera.

Every scenario starts with the guided calibration protocol (15 s looking
ahead, 4 s eyes closed, 5 s normal), then its body. Drowsy scenarios carry
"events" with onset times; not-drowsy ones must stay quiet.

Timing anchors, cited in docs/thresholds.md:

* Alert blink rate 15-20/min, rising and then falling with fatigue (Stern et
  al. 1994); alert blink duration ~100-150 ms at half amplitude, lengthening
  to 200-400 ms when drowsy (Caffier et al. 2003; Ingre et al. 2006;
  Schleicher et al. 2008).
* Drowsy eyelids reopen slowly (Johns et al. 2007).
* PERCLOS under 5 % alert, over 15 % drowsy (Dinges & Grace 1998).
* Microsleeps: eye closures of 0.5 s to several seconds (Boyle et al. 2008;
  Hertig-Godeschalk et al. 2020).
* Yawns last about 6 s (Provine 1986).
* Mirror glances last about 0.8-1.2 s (Rockwell 1988; Wierwille 1993).
* Speech moves the jaw at the syllable rate, 3-7 Hz (Chandrasekaran et al.
  2009).
* Smiling raises the cheeks and narrows the eyes (Duchenne smile; Ekman,
  Davidson & Friesen 1990).
* Head nodding off: a slow drift down while the eyes close, then a fast
  corrective jerk back up (described in rater schemes such as Wierwille &
  Ellsworth 1994; the speeds here are our model, see docs/thresholds.md).
* The upper lid follows vertical gaze, so looking down lowers it without
  any drowsiness (Becker & Fuchs 1988).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

FPS = 30.0
CAL_LOOK_S = 15.0
CAL_CLOSE_S = 4.0
CAL_SETTLE_S = 5.0
LEAD_S = CAL_LOOK_S + CAL_CLOSE_S + CAL_SETTLE_S


@dataclass
class Eyes:
    """One driver's eyes and camera mount."""

    name: str
    ear_open: float            # EAR with the eyes normally open, head straight
    closed_ratio: float        # EAR shut / EAR open (MediaPipe never reaches 0)
    noise: float = 0.006       # landmark jitter in EAR units
    glasses: bool = False
    yaw0: float = -8.0         # camera mount offset: neutral head pose as seen by the camera
    pitch0: float = 6.0
    iod: float = 120.0         # face size, px between the eyes


EYES = {
    "small": Eyes("small", 0.20, 0.42, noise=0.005),
    "medium": Eyes("medium", 0.28, 0.33),
    "large": Eyes("large", 0.36, 0.28, noise=0.007),
    "glasses": Eyes("glasses", 0.26, 0.36, noise=0.011, glasses=True),
}


@dataclass
class Frame:
    t: float
    face: bool = True
    ear_l: float = 0.0
    ear_r: float = 0.0
    width_l: float = 1.0       # eye width relative to its straight-ahead width
    width_r: float = 1.0
    yaw: float = 0.0           # as the camera sees it (includes the mount offset)
    pitch: float = 0.0         # positive = head down
    roll: float = 0.0
    iod: float = 120.0
    brightness: float = 140.0
    edge: bool = False         # face partly out of frame
    blink_l: float = 0.05      # MediaPipe eyeBlinkLeft/Right
    blink_r: float = 0.05
    squint_l: float = 0.05     # eyeSquint (lower lid / cheek)
    squint_r: float = 0.05
    jaw: float = 0.02          # jawOpen
    smile: float = 0.0         # mouthSmile (mean of L/R)
    cheek: float = 0.0         # cheekSquint (mean)
    phase: str = "body"        # "look", "close", "settle", "body"

    @property
    def mar(self) -> float:
        return 0.02 + 0.75 * self.jaw


@dataclass
class Event:
    kind: str          # what must be caught: "drowsy", "microsleep", "nod"
    onset: float       # seconds into the scenario (including the lead-in)
    window: float      # it must be caught within this many seconds


@dataclass
class Scenario:
    name: str
    drowsy: bool
    frames: list[Frame]
    events: list[Event] = field(default_factory=list)
    body_s: float = 0.0
    eyes: str = "medium"


# --------------------------------------------------------------------------- #
# The driver model
# --------------------------------------------------------------------------- #


class Driver:
    """Produces frames from a few slowly varying controls.

    Controls, set per frame by a scenario script:
      lid      upper-lid openness from drowsiness/heavy lids (1 normal, 0 shut)
      blink    extra closure from the current blink (0..1)
      yaw/pitch/roll   head pose relative to the driver's neutral
      smile, jaw       expression
      glare_l/r        a reflection corrupting that eye's landmarks (0..1)
      face             face visible at all
      bright           image brightness
      edge             face partly out of frame
      hide_l/r         that eye covered (hand, hair) or outside the frame
    """

    def __init__(self, eyes: Eyes, seed: int = 1, fps: float = FPS) -> None:
        self.e = eyes
        self.fps = float(fps)
        self.rng = random.Random(seed)
        # Slow natural wander, measured on a real webcam session (40 s at
        # 30 fps): open-eye EAR varies about +-7 % (p10..p90 = -7 %..+14 %)
        # with posture and gaze; head pitch wanders ~2-3 deg with 0.4 deg of
        # frame-to-frame jitter.
        self._drift = 0.0
        self._pw = 0.0
        self._yw = 0.0
        self.frames: list[Frame] = []
        self.t = 0.0
        self._blink: Optional[tuple[float, float, float]] = None   # start, half-amplitude duration, depth
        self._next_blink = self.rng.uniform(1.0, 3.0)
        self.c = dict(lid=1.0, yaw=0.0, pitch=0.0, roll=0.0, smile=0.0, jaw=0.02,
                      glare_l=0.0, glare_r=0.0, face=1.0, bright=140.0, edge=0.0,
                      hide_l=0.0, hide_r=0.0, ear_scale=1.0)
        # Blink habits: rate per minute and half-amplitude duration (s).
        self.blink_rate = 17.0
        self.blink_dur = (0.10, 0.15)
        self.reopen_slow = 1.0     # >1 = lids reopen slowly (drowsy)

    # -- blinks ------------------------------------------------------------ #

    def start_blink(self, dur: float, depth: float = 1.0) -> None:
        self._blink = (self.t, dur, depth)

    def _blink_closure(self) -> float:
        if self._blink is None:
            if self.t >= self._next_blink and self.blink_rate > 0:
                self.start_blink(self.rng.uniform(*self.blink_dur))
                gap = self.rng.expovariate(self.blink_rate / 60.0)
                self._next_blink = self.t + max(0.8, min(gap, 12.0))
            else:
                return 0.0
        t0, dur, depth = self._blink
        # Half-amplitude duration `dur`: close fast, hold, reopen more slowly.
        # With this shape the time above half closure is 0.8 x the blink's
        # full extent, whatever the reopening speed (measured at 240 Hz), so
        # the full extent is dur / 0.8. Slow reopening changes the shape
        # (and the amplitude-velocity ratio), not the half-amplitude length.
        total = dur / 0.8
        x = (self.t - t0) / total
        if x >= 1.0:
            self._blink = None
            return 0.0
        close_part = 0.30 / (0.30 + 0.70 * self.reopen_slow)   # share of time closing
        if x < close_part:
            v = x / close_part
        else:
            v = 1.0 - (x - close_part) / (1.0 - close_part)
        return depth * max(0.0, min(1.0, math.sin(v * math.pi / 2) ** 0.6))

    # -- one frame --------------------------------------------------------- #

    def step(self, phase: str = "body") -> Frame:
        c, e, r = self.c, self.e, self.rng
        dt = 1.0 / self.fps
        # A frame integrates light over its exposure (~half the frame time),
        # so a fast blink is averaged, not sampled at an instant.
        t_mid = self.t
        sub = []
        for k in (-0.25, 0.0, 0.25):
            self.t = t_mid + k * dt
            sub.append(self._blink_closure())
        self.t = t_mid
        blink = sum(sub) / len(sub)
        a = math.exp(-dt / 20.0)
        self._drift = a * self._drift + math.sqrt(1 - a * a) * r.gauss(0, 0.045)
        a = math.exp(-dt / 5.0)
        self._pw = a * self._pw + math.sqrt(1 - a * a) * r.gauss(0, 1.8)
        self._yw = a * self._yw + math.sqrt(1 - a * a) * r.gauss(0, 3.0)
        lid = max(0.0, min(1.0, c["lid"] * (1.0 - blink)))
        # Looking down lowers the upper lid (lid-gaze coupling); a smile lifts
        # the cheeks and narrows the eye from below.
        down = max(0.0, c["pitch"])
        gaze_lid = max(0.35, 1.0 - 0.014 * down)
        smile_squeeze = 1.0 - 0.38 * c["smile"]
        seen = lid * gaze_lid * smile_squeeze
        ear_true = e.ear_open * (e.closed_ratio + (1 - e.closed_ratio) * seen)
        yaw, pitch = c["yaw"] + self._yw, c["pitch"] + self._pw
        yaw_cam, pitch_cam = yaw + e.yaw0, pitch + e.pitch0
        # Foreshortening: a turned head narrows the eye's width, which RAISES
        # EAR; the far eye narrows more. Pitch shortens the eye's height.
        wl = max(0.15, math.cos(math.radians(yaw_cam + 12)))
        wr = max(0.15, math.cos(math.radians(yaw_cam - 12)))
        vf = max(0.4, math.cos(math.radians(pitch_cam)))
        n = e.noise * (1.0 + 2.0 * c["edge"])
        scale = c["ear_scale"] * (1.0 + self._drift)
        ear_l = ear_true * vf / wl * scale + r.gauss(0, n)
        ear_r = ear_true * vf / wr * scale + r.gauss(0, n)
        # Glare or a covered eye corrupts that eye's landmarks.
        if c["glare_l"] > 0:
            ear_l *= 1.0 - 0.6 * c["glare_l"] * r.uniform(0.6, 1.0)
        if c["glare_r"] > 0:
            ear_r *= 1.0 - 0.6 * c["glare_r"] * r.uniform(0.6, 1.0)
        if c["hide_l"] > 0:
            ear_l = r.uniform(0.02, 0.6) * e.ear_open
            wl *= 0.35
        if c["hide_r"] > 0:
            ear_r = r.uniform(0.02, 0.6) * e.ear_open
            wr *= 0.35
        if e.glasses and r.random() < 0.004:
            # A brief reflection off the lenses, mostly one eye.
            if r.random() < 0.8:
                c["glare_l" if r.random() < 0.5 else "glare_r"] = 1.0
            else:
                c["glare_l"] = c["glare_r"] = 1.0
            self._glare_until = self.t + r.uniform(0.1, 0.5)
        if getattr(self, "_glare_until", None) is not None and self.t >= self._glare_until:
            if phase != "glare":
                c["glare_l"] = c["glare_r"] = 0.0
            self._glare_until = None
        # Blendshapes: eyeBlink tracks upper-lid closure (and creeps up a
        # little when looking down or smiling); eyeSquint/cheekSquint follow
        # the cheeks. Glare confuses the model less than raw landmarks.
        bl_base = 0.04 + 0.9 * (1 - lid) + 0.010 * down + 0.22 * c["smile"]
        f = Frame(
            t=self.t, face=c["face"] > 0.5,
            ear_l=max(0.01, ear_l), ear_r=max(0.01, ear_r), width_l=wl, width_r=wr,
            yaw=yaw_cam + r.gauss(0, 0.45), pitch=pitch_cam + r.gauss(0, 0.45),
            roll=c["roll"] + r.gauss(0, 0.3), iod=e.iod * (0.6 if c["edge"] else 1.0),
            brightness=c["bright"] + r.gauss(0, 1.5), edge=c["edge"] > 0.5,
            blink_l=min(1, max(0, bl_base + 0.25 * c["glare_l"] + r.gauss(0, 0.02))),
            blink_r=min(1, max(0, bl_base + 0.25 * c["glare_r"] + r.gauss(0, 0.02))),
            squint_l=min(1, 0.05 + 0.6 * c["smile"] + r.gauss(0, 0.02)),
            squint_r=min(1, 0.05 + 0.6 * c["smile"] + r.gauss(0, 0.02)),
            jaw=max(0.0, c["jaw"] + r.gauss(0, 0.01)), smile=c["smile"], cheek=0.6 * c["smile"],
            phase=phase,
        )
        self.frames.append(f)
        self.t += dt
        return f

    def run(self, seconds: float, phase: str = "body",
            each: Optional[Callable[["Driver", float], None]] = None) -> None:
        end = self.t + seconds
        while self.t < end - 1e-9:
            if each is not None:
                each(self, self.t)
            self.step(phase)

    def ramp(self, key: str, to: float, seconds: float, phase: str = "body") -> None:
        start, t0 = self.c[key], self.t

        def go(d, t):
            x = min(1.0, (t - t0) / max(seconds, 1e-6))
            d.c[key] = start + (to - start) * x
        self.run(seconds, phase, go)


def lead_in(d: Driver) -> None:
    """The guided calibration: look ahead, close the eyes, settle."""
    d.run(CAL_LOOK_S, "look")
    saved = d.blink_rate
    d.blink_rate = 0
    d._blink = None
    d.ramp("lid", 0.0, 0.25, "close")
    d.run(CAL_CLOSE_S - 0.5, "close")
    d.ramp("lid", 1.0, 0.25, "close")
    d.blink_rate = saved
    d._next_blink = d.t + 1.0
    d.run(CAL_SETTLE_S, "settle")


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #


def _alert(d, body):
    d.run(body)


def _talking(d, body):
    def each(dd, t):
        dd.c["jaw"] = max(0.0, 0.12 + 0.12 * math.sin(2 * math.pi * 4.5 * t) + dd.rng.gauss(0, 0.04))
        dd.c["smile"] = 0.15 + 0.1 * math.sin(2 * math.pi * 0.3 * t)
        dd.c["pitch"] = 1.5 * math.sin(2 * math.pi * 0.8 * t)
        dd.c["yaw"] = 2.5 * math.sin(2 * math.pi * 0.25 * t)
    d.blink_rate = 22.0     # people blink more when talking
    d.run(body, each=each)


def _smiling(d, body):
    end = d.t + body
    while d.t < end:
        d.run(d.rng.uniform(4, 10))
        d.ramp("smile", d.rng.uniform(0.6, 0.95), 0.4)           # smile or laugh
        laugh = d.rng.random() < 0.5
        if laugh:
            def each(dd, t):
                dd.c["jaw"] = 0.35 + 0.2 * abs(math.sin(2 * math.pi * 3.0 * t))
                dd.c["lid"] = 0.55 + 0.25 * abs(math.sin(2 * math.pi * 2.0 * t))   # eyes squeezed by laughter
                dd.c["pitch"] = 4 * math.sin(2 * math.pi * 1.0 * t)
            d.run(d.rng.uniform(2, 4), each=each)
            d.c["lid"] = 1.0
            d.c["jaw"] = 0.02
            d.c["pitch"] = 0.0
        else:
            d.run(d.rng.uniform(2, 5))
        d.ramp("smile", 0.0, 0.6)


def _glances(yaw_range, pitch_range, dur_range, gap_range):
    def script(d, body):
        end = d.t + body
        while d.t < end:
            d.run(d.rng.uniform(*gap_range))
            y, p = d.rng.uniform(*yaw_range), d.rng.uniform(*pitch_range)
            d.ramp("yaw", y, 0.25); d.c["pitch"] = 0.0
            d.ramp("pitch", p, 0.25)
            d.run(d.rng.uniform(*dur_range))
            d.ramp("pitch", 0.0, 0.25)
            d.ramp("yaw", 0.0, 0.25)
    return script


_mirrors = _glances((-40, 42), (-3, 6), (0.7, 1.3), (5, 12))
_dashboard = _glances((-6, 6), (15, 22), (0.6, 1.5), (6, 14))
_phone = _glances((-8, 8), (30, 40), (1.8, 3.0), (10, 20))


def _head_turns(d, body):
    end = d.t + body
    while d.t < end:
        d.run(d.rng.uniform(8, 16))
        side = d.rng.choice((-1, 1))
        d.ramp("yaw", side * d.rng.uniform(50, 70), 0.45)
        if abs(d.c["yaw"]) > 55:
            d.c["face"] = 0.0               # MediaPipe loses a full profile
        d.run(d.rng.uniform(0.5, 1.2))
        d.c["face"] = 1.0
        d.ramp("yaw", 0.0, 0.45)


def _yawning(d, body):
    end = d.t + body
    while d.t < end:
        d.run(d.rng.uniform(25, 50))
        d.ramp("jaw", 0.85, 2.0)
        d.c["lid"] = 0.45                     # eyes squeeze at the peak
        d.run(d.rng.uniform(1.5, 2.5))
        d.c["lid"] = 1.0
        d.ramp("jaw", 0.02, 2.0)


def _glare(d, body):
    end = d.t + body
    while d.t < end:
        d.run(d.rng.uniform(3, 9))
        both = d.rng.random() < 0.3
        side = d.rng.choice(("glare_l", "glare_r"))
        if both:
            d.c["glare_l"] = d.c["glare_r"] = 1.0
        else:
            d.c[side] = 1.0
        d.run(d.rng.uniform(0.3, 1.5), "glare")
        d.c["glare_l"] = d.c["glare_r"] = 0.0


def _lighting(d, body):
    end = d.t + body
    while d.t < end:
        d.run(d.rng.uniform(8, 20))
        dark = d.rng.uniform(55, 80)
        d.ramp("bright", dark, 0.3)
        d.c["ear_scale"] = d.rng.uniform(0.9, 1.08)      # landmarks shift with the light
        d.run(d.rng.uniform(4, 10))                      # a tunnel
        d.ramp("bright", 140, 0.3)
        d.c["ear_scale"] = 1.0


def _out_of_frame(d, body):
    end = d.t + body
    while d.t < end:
        d.run(d.rng.uniform(8, 15))
        d.c["edge"] = 1.0
        d.c["hide_l" if d.rng.random() < 0.5 else "hide_r"] = 1.0
        d.run(d.rng.uniform(3, 8))
        d.c["edge"] = 0.0
        d.c["hide_l"] = d.c["hide_r"] = 0.0


def _one_eye(d, body):
    end = d.t + body
    while d.t < end:
        d.run(d.rng.uniform(6, 12))
        d.c["hide_l" if d.rng.random() < 0.5 else "hide_r"] = 1.0    # hand rubbing an eye, hair
        d.run(d.rng.uniform(3, 10))
        d.c["hide_l"] = d.c["hide_r"] = 0.0


# -- drowsy ----------------------------------------------------------------- #

def _slow_blinks(d, body):
    d.run(20)
    d.blink_dur = (0.30, 0.45)
    d.blink_rate = 14.0
    d.reopen_slow = 2.0
    d.run(body - 20)


def _heavy_eyelids(d, body):
    d.run(20)
    d.blink_dur = (0.18, 0.32)
    d.reopen_slow = 1.6

    def each(dd, t):
        dd.c["lid"] = 0.62 + 0.06 * math.sin(2 * math.pi * t / 23.0) + dd.rng.gauss(0, 0.01)
    d.run(body - 20, each=each)


def _nods(d, body, events):
    d.run(20)
    d.blink_dur = (0.18, 0.30)
    end = d.t + body - 20
    first = True
    while d.t < end - 8:
        d.run(d.rng.uniform(15, 30))
        if first:
            events.append(Event("nod", d.t, 20.0))
            first = False
        depth = d.rng.uniform(16, 32)
        drop_s = d.rng.uniform(1.0, 2.2)          # slow drift: ~8-25 deg/s
        lid_min = d.rng.uniform(0.15, 0.55)       # heavy, but often not fully shut
        t0 = d.t

        def down(dd, t, depth=depth, drop_s=drop_s, t0=t0, lid_min=lid_min):
            x = min(1.0, (t - t0) / drop_s)
            dd.c["pitch"] = depth * x * x
            dd.c["lid"] = max(lid_min, 1.0 - 1.2 * x)
            if dd.c["pitch"] > 26:
                dd.c["face"] = 0.0                  # chin towards the chest: face lost
        d.run(drop_s, each=down)
        d.run(d.rng.uniform(0.1, 0.4))
        d.c["face"] = 1.0
        d.c["lid"] = 1.0
        d.ramp("pitch", -3.0, d.rng.uniform(0.12, 0.25))   # the jerk back up: ~100-200 deg/s
        d.ramp("pitch", 0.0, 0.5)


def _microsleep(d, body, events):
    d.run(30)
    end = d.t + body - 30
    while d.t < end - 5:
        d.run(d.rng.uniform(20, 40))
        events.append(Event("microsleep", d.t, 1.5))
        d.blink_rate = 0
        d._blink = None
        d.ramp("lid", 0.0, 0.15)
        d.run(d.rng.uniform(0.6, 2.0))
        d.ramp("lid", 1.0, 0.25)
        d.blink_rate = 17.0
        d._next_blink = d.t + 1.5


def _progressive(d, body, events):
    """Ten minutes from alert to nodding off (KSS ~4 -> 8)."""
    third = body / 3

    def each(dd, t, t0=d.t):
        x = min(1.0, (t - t0) / body)
        dd.blink_dur = (0.10 + 0.20 * x, 0.15 + 0.28 * x)
        dd.reopen_slow = 1.0 + 1.2 * x
        dd.blink_rate = 17 - 4 * x
        dd.c["lid"] = 1.0 - 0.35 * max(0.0, x - 0.3) / 0.7 + dd.rng.gauss(0, 0.01)
    d.run(third, each=each)
    events.append(Event("drowsy", d.t, 2 * third))
    d.run(third, each=each)
    for _ in range(3):
        d.run(d.rng.uniform(10, 25), each=each)
        depth, drop_s, t0 = d.rng.uniform(15, 25), d.rng.uniform(1.2, 2.0), d.t

        def down(dd, t, depth=depth, drop_s=drop_s, t0=t0):
            x = min(1.0, (t - t0) / drop_s)
            dd.c["pitch"] = depth * x * x
            dd.c["lid"] = max(0.05, 0.8 - x)
        d.run(drop_s, each=down)
        d.c["lid"] = 0.75
        d.ramp("pitch", 0.0, 0.2)
    d.run(5, each=each)


NOT_DROWSY = {
    "alert": _alert, "talking": _talking, "smiling_laughing": _smiling,
    "mirror_glances": _mirrors, "dashboard_glances": _dashboard, "phone_glances": _phone,
    "head_turns": _head_turns, "yawning": _yawning, "glasses_glare": _glare,
    "lighting_change": _lighting, "face_partly_out": _out_of_frame, "one_eye_hidden": _one_eye,
}
DROWSY = {
    "slow_blinks": _slow_blinks, "heavy_eyelids": _heavy_eyelids, "head_nods": _nods,
    "microsleep": _microsleep, "progressive": _progressive,
}
# Gradual drowsy cases are caught when they reach level 1 within this long
# after the change starts (20 s into the body).
GRADUAL_WINDOW_S = 90.0


def build(name: str, eyes: str = "medium", seed: int = 1, body_s: float = 180.0,
          fps: float = FPS) -> Scenario:
    d = Driver(EYES[eyes], seed=seed, fps=fps)
    lead_in(d)
    events: list[Event] = []
    if name in NOT_DROWSY:
        NOT_DROWSY[name](d, body_s)
        drowsy = False
    else:
        drowsy = True
        fn = DROWSY[name]
        if name in ("head_nods", "microsleep", "progressive"):
            fn(d, body_s, events)
        else:
            fn(d, body_s)
            events.append(Event("drowsy", LEAD_S + 20.0, GRADUAL_WINDOW_S))
    return Scenario(name=name, drowsy=drowsy, frames=d.frames, events=events,
                    body_s=d.t - LEAD_S, eyes=f"{eyes}@{fps:g}fps")


def all_names() -> list[str]:
    return list(NOT_DROWSY) + list(DROWSY)


def iter_cases(eyes: tuple[str, ...] = ("small", "medium", "large", "glasses"),
               seeds: tuple[int, ...] = (1,), body_s: float = 180.0) -> Iterator[Scenario]:
    for name in all_names():
        for e in eyes:
            for s in seeds:
                yield build(name, e, s, 600.0 if name == "progressive" else body_s)
