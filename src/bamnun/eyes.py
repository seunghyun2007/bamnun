"""Eyes, expressions and head nods, measured against the driver's own calibration.

docs/SPEC.md, section 15, and docs/detection-audit.md (flaws F5-F28). The
pieces, in the order a frame meets them:

* ``EyeInputs``       one frame's raw measurements (both eyes, blendshapes,
                      brightness, face size and edge). Built from MediaPipe
                      landmarks on the device, or by the scenario simulator.
* ``Personal``        maps them onto the driver's 0-100 % openness scale,
                      corrected for head pose, fusing EAR with eyeBlink.
* ``Conditions``      decides whether this frame can be trusted for eye
                      measures (expression, lighting, edge, pose, glare).
* ``BlinkDetector``   blinks on the openness scale, with sub-frame timing.
* ``RollingPerclos``  P80 over 60 s of reliable time, incrementally.
* ``NodDetector``     head drops relative to the calibrated neutral pitch.
* ``Calibrator``      the look-ahead and eyes-closed steps, with quality
                      checks and live hints.

Everything here is plain arithmetic on a few numbers per frame; nothing
allocates per frame beyond small deque entries, because the Pi runs this at
30 fps alongside MediaPipe.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Optional

import numpy as np

# MediaPipe FaceMesh indices (468/478-point topology).
R_CORNERS = (33, 133)
L_CORNERS = (362, 263)
R_RING = (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246)
L_RING = (362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398)
MOUTH_CORNERS = (61, 291)


def _cfg(d: Optional[dict], key: str, default):
    v = (d or {}).get(key, default)
    return type(default)(v) if isinstance(default, (int, float)) and not isinstance(default, bool) else v


def face_brightness(image, points) -> Optional[float]:
    """Mean grey level of the face box, sampled sparsely (about 0.2 ms)."""
    try:
        h, w = image.shape[:2]
        x0, y0 = int(max(0, points[:, 0].min())), int(max(0, points[:, 1].min()))
        x1, y1 = int(min(w, points[:, 0].max())), int(min(h, points[:, 1].max()))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return float(image[y0:y1:6, x0:x1:6].mean())
    except Exception:  # noqa: BLE001 - brightness is advisory
        return None


# --------------------------------------------------------------------------- #
# One frame's measurements
# --------------------------------------------------------------------------- #


@dataclass
class EyeInputs:
    """What the camera says about the eyes and face in one frame."""

    ear_l: float = 0.0
    ear_r: float = 0.0
    width_l: float = 1.0        # each eye's width, relative to the wider one
    width_r: float = 1.0
    edge_l: bool = False        # that eye is at or past the frame edge
    edge_r: bool = False
    edge: bool = False          # the face is cut by the frame edge
    blink_l: Optional[float] = None     # MediaPipe eyeBlinkLeft/Right (0 open .. 1 shut)
    blink_r: Optional[float] = None
    squint_l: Optional[float] = None
    squint_r: Optional[float] = None
    jaw: Optional[float] = None         # jawOpen
    smile: Optional[float] = None       # mean mouthSmileLeft/Right
    cheek: Optional[float] = None       # mean cheekSquintLeft/Right
    mouth_width: float = 0.0    # mouth corner distance / interocular distance
    brightness: Optional[float] = None  # mean grey level around the face, 0-255
    iod_frac: Optional[float] = None    # interocular distance / frame width

    @property
    def has_blendshapes(self) -> bool:
        return self.blink_l is not None and self.blink_r is not None

    @classmethod
    def from_landmarks(cls, lms, ear_r: float, ear_l: float, iod: float,
                       brightness: Optional[float] = None) -> "EyeInputs":
        pts = lms.points
        w, h = lms.image_size

        def dist(a, b):
            return float(np.hypot(*(pts[a][:2] - pts[b][:2])))

        wr, wl = dist(*R_CORNERS), dist(*L_CORNERS)
        top = max(wr, wl, 1e-6)
        mx, my = 0.01 * w, 0.01 * h

        def off(ring):
            xs, ys = pts[list(ring), 0], pts[list(ring), 1]
            return bool(xs.min() < mx or xs.max() > w - mx or ys.min() < my or ys.max() > h - my)

        face_off = bool(pts[:, 0].min() < 0 or pts[:, 0].max() > w or pts[:, 1].min() < 0 or pts[:, 1].max() > h)
        bs = getattr(lms, "blendshapes", None) or {}

        def g(*names):
            v = [bs[n] for n in names if n in bs]
            return float(sum(v) / len(v)) if v else None

        return cls(
            ear_l=ear_l, ear_r=ear_r, width_l=wl / top, width_r=wr / top,
            edge_l=off(L_RING), edge_r=off(R_RING), edge=face_off,
            # MediaPipe names blendshapes from the subject's side.
            blink_l=g("eyeBlinkLeft"), blink_r=g("eyeBlinkRight"),
            squint_l=g("eyeSquintLeft"), squint_r=g("eyeSquintRight"),
            jaw=g("jawOpen"), smile=g("mouthSmileLeft", "mouthSmileRight"),
            cheek=g("cheekSquintLeft", "cheekSquintRight"),
            mouth_width=dist(*MOUTH_CORNERS) / max(iod, 1e-6),
            brightness=brightness, iod_frac=iod / max(w, 1),
        )


# --------------------------------------------------------------------------- #
# The personal openness scale
# --------------------------------------------------------------------------- #


class Personal:
    """EAR and eyeBlink -> openness, 1.0 = this driver's normal, 0.0 = shut."""

    def __init__(self, cfg: dict) -> None:
        self.drop_ratio = _cfg(cfg, "eye_drop_width_ratio", 0.60)
        self.max_angle = _cfg(cfg, "pose_compensation_max_deg", 30.0)
        self.w_bs = _cfg(cfg, "blendshape_weight", 0.5)
        self.disagree = _cfg(cfg, "eye_disagreement", 0.45)

    def ear(self, x: EyeInputs) -> Optional[float]:
        """Width-weighted mean of the usable eyes (F6, F20)."""
        eyes = []
        for ear, wdt, edge, other in ((x.ear_l, x.width_l, x.edge_l, x.width_r),
                                      (x.ear_r, x.width_r, x.edge_r, x.width_l)):
            if edge or ear <= 0 or wdt < self.drop_ratio * other:
                continue
            eyes.append((ear, wdt))
        if not eyes:
            return None
        return sum(e * w for e, w in eyes) / sum(w for _, w in eyes)

    def blink(self, x: EyeInputs) -> Optional[float]:
        if not x.has_blendshapes:
            return None
        vals = []
        for b, wdt, edge, other in ((x.blink_l, x.width_l, x.edge_l, x.width_r),
                                    (x.blink_r, x.width_r, x.edge_r, x.width_l)):
            if edge or wdt < self.drop_ratio * other:
                continue
            vals.append(b)
        return sum(vals) / len(vals) if vals else None

    def compensate(self, ear: float, yaw: float, pitch: float, cal) -> float:
        """Undo foreshortening relative to the calibrated neutral pose (F7)."""
        cy = math.cos(math.radians(max(-80.0, min(80.0, yaw))))
        cp = math.cos(math.radians(max(-80.0, min(80.0, pitch))))
        cy0 = math.cos(math.radians(cal.yaw_zero))
        cp0 = math.cos(math.radians(cal.pitch_zero))
        return ear * (cy / cy0) * (cp0 / max(cp, 0.3))

    def openness(self, x: EyeInputs, yaw: float, pitch: float, cal) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """(fused, from EAR, from eyeBlink); None where not measurable."""
        o_ear = o_bs = None
        e = self.ear(x)
        if e is not None:
            e = self.compensate(e, yaw, pitch, cal)
            span = max(cal.ear_open - cal.ear_closed, 1e-4)
            o_ear = max(-0.3, min(1.5, (e - cal.ear_closed) / span))
        b = self.blink(x)
        if b is not None and cal.bs_closed - cal.bs_open > 0.15:
            o_bs = max(-0.3, min(1.5, (cal.bs_closed - b) / (cal.bs_closed - cal.bs_open)))
        if o_ear is None and o_bs is None:
            return None, None, None
        if o_ear is None:
            return o_bs, o_ear, o_bs
        if o_bs is None:
            return o_ear, o_ear, o_bs
        return (1 - self.w_bs) * o_ear + self.w_bs * o_bs, o_ear, o_bs


# --------------------------------------------------------------------------- #
# Frames that can't be trusted for eye measures
# --------------------------------------------------------------------------- #


class Conditions:
    """Expression, lighting, framing and pose checks (F14-F21)."""

    def __init__(self, cfg: dict) -> None:
        self.smile_th = _cfg(cfg, "smile_threshold", 0.35)
        self.cheek_th = _cfg(cfg, "cheek_threshold", 0.30)
        self.mouth_wide = _cfg(cfg, "smile_mouth_width_ratio", 1.12)
        self.talk_std = _cfg(cfg, "talk_jaw_std", 0.05)
        self.talk_window = _cfg(cfg, "talk_window_s", 1.0)
        self.yawn_jaw = _cfg(cfg, "yawn_jaw_open", 0.50)
        self.yawn_mar = _cfg(cfg, "yawn_mar", 0.55)
        self.yawn_min = _cfg(cfg, "yawn_min_s", 1.0)
        self.expr_hold = _cfg(cfg, "expression_hold_s", 0.7)
        self.light_jump = _cfg(cfg, "light_jump", 18.0)
        self.light_hold = _cfg(cfg, "light_hold_s", 1.0)
        self.min_iod_frac = _cfg(cfg, "min_iod_frac", 0.045)
        self.max_yaw = _cfg(cfg, "reliable_yaw_deg", 30.0)
        self.max_pitch = _cfg(cfg, "reliable_pitch_deg", 30.0)
        # The angle to the camera itself, not to the calibrated neutral: with
        # the device off to one side, a driver looking at the road is already
        # 40 degrees round, and a small turn away hides the far eye behind the
        # nose and flattens the near one, which reads as closed.
        self.max_camera_yaw = _cfg(cfg, "reliable_camera_yaw_deg", 55.0)
        self._jaw: Deque[tuple[float, float]] = deque()
        self._yawn_since: Optional[float] = None
        self._expr_until = -1e9
        self._light_until = -1e9
        self._slow_b: Optional[float] = None
        self._last_t: Optional[float] = None
        self.yawn_now = False
        self.yawns: Deque[float] = deque()
        self.expression = ""

    def update(self, t: float, x: EyeInputs, mar: float, cal) -> None:
        dt = 0.0 if self._last_t is None else max(0.0, min(0.5, t - self._last_t))
        self._last_t = t
        jaw = x.jaw if x.jaw is not None else max(0.0, (mar - cal.mar_rest) / 0.6)
        self._jaw.append((t, jaw))
        while self._jaw and self._jaw[0][0] < t - self.talk_window:
            self._jaw.popleft()
        expr = ""
        # Yawn: the jaw held wide open (Provine 1986: ~6 s, opening phase ~2 s).
        wide = (x.jaw is not None and x.jaw > self.yawn_jaw) or mar > cal.mar_rest + self.yawn_mar
        if wide:
            if self._yawn_since is None:
                self._yawn_since = t
            if t - self._yawn_since >= self.yawn_min:
                if not self.yawn_now:
                    self.yawns.append(t)
                self.yawn_now = True
                expr = "yawn"
        else:
            self._yawn_since = None
            self.yawn_now = False
        while self.yawns and self.yawns[0] < t - 600.0:
            self.yawns.popleft()
        # Smile or laugh: the cheeks squeeze the eyes from below.
        if not expr:
            if x.smile is not None:
                if x.smile > self.smile_th or (x.cheek or 0.0) > self.cheek_th:
                    expr = "smile"
            elif cal.mouth_width_rest > 0 and x.mouth_width > cal.mouth_width_rest * self.mouth_wide:
                expr = "smile"
        # Talking: the jaw moving at speech rate.
        if not expr and len(self._jaw) >= 4:
            vals = [v for _, v in self._jaw]
            if float(np.std(vals)) > self.talk_std and max(vals) < self.yawn_jaw:
                expr = "talk"
        if expr:
            self._expr_until = t + self.expr_hold
            self.expression = expr
        elif t >= self._expr_until:
            self.expression = ""
        # Lighting: a sudden change shifts the landmarks for a moment.
        if x.brightness is not None:
            if self._slow_b is None:
                self._slow_b = x.brightness
            if abs(x.brightness - self._slow_b) > self.light_jump:
                self._light_until = t + self.light_hold
                self._slow_b = x.brightness      # the new light is the new normal
            a = 1.0 - math.exp(-dt / 2.0) if dt > 0 else 0.0
            self._slow_b += (x.brightness - self._slow_b) * a

    def reason(self, t: float, x: EyeInputs, yaw: float, pitch: float, look_down: float) -> str:
        """Why this frame can't be trusted for eye measures ("" = it can)."""
        if self.expression or t < self._expr_until:
            return self.expression or "expression"
        if t < self._light_until:
            return "lighting"
        if x.edge:
            return "edge"
        if x.iod_frac is not None and x.iod_frac < self.min_iod_frac:
            return "small_face"
        if pitch > look_down:
            return "looking_down"
        if abs(yaw) > self.max_yaw or pitch < -self.max_pitch:
            return "pose"
        return ""


# --------------------------------------------------------------------------- #
# Blinks on the openness scale
# --------------------------------------------------------------------------- #


@dataclass
class Blink:
    start: float
    end: float
    half_s: float               # duration at half amplitude (sub-frame interpolated)
    depth: float                # how far it closed (1 = fully, on the personal scale)
    avr: float                  # reopening amplitude / peak reopening speed, s
    judged: bool                # all its frames were reliable
    kind: str                   # "blink" | "long" | "microsleep" | "held"


class BlinkDetector:
    """Half-amplitude blinks with interpolated crossings (F9, F10).

    A blink starts when openness falls through ``half`` (50 %) from an open
    state and ends when it rises back through it. The crossing times are
    interpolated between frames, so at 15 fps the duration is not quantised to
    67 ms. Closures longer than ``held_s`` are not blinks (a held squint, a
    look down) and stay out of the averages.
    """

    def __init__(self, cfg: dict) -> None:
        self.half = _cfg(cfg, "blink_half_level", 0.50)
        self.open_level = _cfg(cfg, "blink_open_level", 0.70)
        self.long_s = _cfg(cfg, "long_blink_s", 0.30)
        self.micro_s = _cfg(cfg, "microsleep_s", 0.50)
        self.held_s = _cfg(cfg, "held_closure_s", 1.0)
        self.window = _cfg(cfg, "blink_window_s", 60.0)
        self.events: Deque[Blink] = deque()
        self._prev: Optional[tuple[float, float]] = None
        self._closing_at: Optional[float] = None
        self._min = 1.0
        self._peak_up = 0.0
        self._judged = True
        self._armed = True
        self.closed = False
        # The most recent ordinary blink, for the Camera screen.
        self.last_blink_s: Optional[float] = None

    def update(self, t: float, o: Optional[float], reliable: bool) -> Optional[Blink]:
        if o is None:
            self._prev = None
            return None
        ev = None
        p = self._prev
        if not self.closed:
            if o > self.open_level:
                self._armed = True
            if p is not None and self._armed and p[1] >= self.half > o:
                # Interpolated down-crossing.
                k = (p[1] - self.half) / max(p[1] - o, 1e-6)
                self._closing_at = p[0] + k * (t - p[0])
                self.closed = True
                self._min = o
                self._peak_up = 0.0
                self._judged = reliable
        else:
            self._min = min(self._min, o)
            self._judged = self._judged and reliable
            if p is not None and t > p[0]:
                self._peak_up = max(self._peak_up, (o - p[1]) / (t - p[0]))
            if p is not None and p[1] < self.half <= o:
                k = (self.half - p[1]) / max(o - p[1], 1e-6)
                up_at = p[0] + k * (t - p[0])
                start = self._closing_at if self._closing_at is not None else up_at
                half_s = max(0.0, up_at - start)
                depth = max(0.0, 1.0 - self._min)
                avr = depth / self._peak_up if self._peak_up > 1e-6 else 0.0
                kind = ("held" if half_s > self.held_s else "microsleep" if half_s >= self.micro_s
                        else "long" if half_s >= self.long_s else "blink")
                ev = Blink(start, up_at, half_s, depth, avr, self._judged, kind)
                self.events.append(ev)
                if kind in ("blink", "long"):
                    self.last_blink_s = half_s
                self.closed = False
                self._armed = False
                self._closing_at = None
        self._prev = (t, o)
        while self.events and self.events[0].end < t - self.window:
            self.events.popleft()
        return ev

    def ongoing_s(self, t: float) -> float:
        return t - self._closing_at if self.closed and self._closing_at is not None else 0.0

    def judged(self, kinds=("blink", "long")) -> list[Blink]:
        return [e for e in self.events if e.judged and e.kind in kinds]


# --------------------------------------------------------------------------- #
# PERCLOS (P80) over reliable time
# --------------------------------------------------------------------------- #


class RollingPerclos:
    """Share of reliable time in the window with openness <= ``closed``.

    Incremental: O(1) per frame. Unreliable time is left out of both the
    numerator and the denominator, so a glance down or a laugh neither adds
    closure nor dilutes it.
    """

    def __init__(self, window_s: float = 60.0, closed: float = 0.20) -> None:
        self.window = window_s
        self.closed = closed
        self._buf: Deque[tuple[float, float, bool]] = deque()
        self._total = 0.0
        self._below = 0.0
        self._last_t: Optional[float] = None
        self._last_closed = False
        self._last_ok = False

    def push(self, t: float, o: Optional[float], reliable: bool) -> None:
        if self._last_t is not None and self._last_ok:
            dt = max(0.0, min(0.5, t - self._last_t))
            self._buf.append((t, dt, self._last_closed))
            self._total += dt
            if self._last_closed:
                self._below += dt
        self._last_t = t
        self._last_ok = reliable and o is not None
        self._last_closed = bool(o is not None and o <= self.closed)
        while self._buf and self._buf[0][0] < t - self.window:
            _, dt, c = self._buf.popleft()
            self._total -= dt
            if c:
                self._below -= dt

    @property
    def value(self) -> float:
        return max(0.0, self._below / self._total) if self._total > 5.0 else 0.0

    @property
    def coverage_s(self) -> float:
        return self._total


# --------------------------------------------------------------------------- #
# Head nods
# --------------------------------------------------------------------------- #


@dataclass
class Nod:
    t: float
    depth: float
    drop_speed: float
    recovery_speed: float
    eyes_heavy: bool
    lost: bool


class NodDetector:
    """Head drops relative to the calibrated neutral pitch (F22, F23).

    A nodding-off movement is a slow-to-moderate drift down, often with the
    eyes closing, then a fast corrective jerk back up. A deliberate glance at
    the dashboard goes down faster, with the eyes open, and comes back without
    a jerk. A face lost right after a downward movement is the bottom of a
    nod, not an empty seat.
    """

    def __init__(self, cfg: dict) -> None:
        self.start_deg = _cfg(cfg, "nod_start_deg", 6.0)
        self.depth_deg = _cfg(cfg, "nod_depth_deg", 12.0)
        self.wobble_k = _cfg(cfg, "nod_wobble_multiple", 3.0)
        self.max_drop_speed = _cfg(cfg, "nod_max_drop_speed_deg_s", 45.0)
        self.jerk = _cfg(cfg, "nod_recovery_speed_deg_s", 60.0)
        self.recover_s = _cfg(cfg, "nod_recovery_window_s", 2.5)
        self.lost_window = _cfg(cfg, "head_drop_lost_window_s", 0.6)
        self.lost_speed = _cfg(cfg, "head_drop_min_speed_deg_s", 8.0)
        self.window = _cfg(cfg, "nod_window_s", 120.0)
        self.events: Deque[Nod] = deque()
        self._hist: Deque[tuple[float, float, Optional[float]]] = deque()
        self._drop: Optional[dict] = None
        self.head_drop_since: Optional[float] = None
        self.wobble = 2.0
        self.max_drop_s = _cfg(cfg, "nod_max_drop_s", 4.0)
        self._prev_pitch: Optional[float] = None

    def _speed(self, t: float, span: float = 0.15) -> float:
        """Pitch speed, deg/s (positive = going down), over the last span."""
        if len(self._hist) < 2:
            return 0.0
        t1, p1, _ = self._hist[-1]
        for t0, p0, _ in reversed(self._hist):
            if t1 - t0 >= span:
                return (p1 - p0) / (t1 - t0)
        t0, p0, _ = self._hist[0]
        return (p1 - p0) / max(t1 - t0, 1e-3)

    def update(self, t: float, pitch: float, openness: Optional[float]) -> Optional[Nod]:
        """``pitch`` relative to the calibrated neutral, positive = down."""
        self.head_drop_since = None
        self._hist.append((t, pitch, openness))
        while self._hist and self._hist[0][0] < t - 3.0:
            self._hist.popleft()
        ev = None
        need = max(self.depth_deg, self.wobble_k * self.wobble)
        d = self._drop
        prev, self._prev_pitch = self._prev_pitch, pitch
        if d is None:
            # A drop starts only by crossing down OUT of the neutral band, so
            # its whole descent is seen; a head already held down (reading a
            # phone) never starts one.
            if prev is not None and prev <= self.start_deg < pitch and self._speed(t) > 0:
                d = self._drop = {"t0": t, "p0": pitch, "max": pitch, "t_max": t,
                                  "heavy": 0, "n": 0, "speed": self._speed(t)}
        if d is not None:
            # The drop's speed is its FASTEST downward movement (over 0.15 s),
            # not the average to the lowest point: a glance at the phone drops
            # in a quarter of a second and then holds still.
            d["speed"] = max(d["speed"], self._speed(t))
            if pitch >= d["max"]:
                d["max"], d["t_max"] = pitch, t
                if openness is not None:
                    d["n"] += 1
                    d["heavy"] += openness < 0.5
            up = -self._speed(t, 0.1)
            depth = d["max"]
            back = depth - pitch
            if depth >= need and back >= 0.6 * (depth - min(0.0, pitch)) and t - d["t_max"] <= self.recover_s:
                heavy = d["n"] > 0 and d["heavy"] / d["n"] >= 0.5
                slow = d["speed"] <= self.max_drop_speed
                # Nodding off: a slow drift down, then a jerk back up at least
                # twice as fast. A glance at the phone or dashboard goes down
                # as fast as it comes back, so it fails the first test.
                if slow and up >= self.jerk and up >= 2.0 * d["speed"]:
                    ev = Nod(t, depth, d["speed"], up, heavy, False)
                    self.events.append(ev)
                self._drop = None
            elif (pitch < self.start_deg * 0.5 or t - d["t_max"] > self.recover_s
                  or t - d["t0"] > self.max_drop_s):
                self._drop = None
        while self.events and self.events[0].t < t - self.window:
            self.events.popleft()
        return ev

    def lost(self, t: float) -> bool:
        """The face just vanished. True if it went down with the head."""
        if self.head_drop_since is not None:
            return True
        if not self._hist:
            return False
        t1, p1, _ = self._hist[-1]
        if t - t1 > self.lost_window:
            return False
        speed = self._speed(t1, 0.3)
        if p1 > self.start_deg and speed >= self.lost_speed:
            self.head_drop_since = t1
            self.events.append(Nod(t1, p1, speed, 0.0, True, True))
            self._drop = None
            return True
        return False

    def count(self) -> int:
        return len(self.events)


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #


HINTS = ("no_face", "closer", "farther", "dark", "bright", "face_camera", "still")


@dataclass
class Calibration:
    """What the calibration learned about this driver."""

    ear_open: float = 0.30          # median EAR, eyes normally open, pose-corrected
    ear_closed: float = 0.0         # EAR with the eyes shut (0 = estimate from ear_open)
    ear_p10: float = 0.27
    ear_p90: float = 0.33
    ear_std: float = 0.02
    bs_open: float = 0.05           # eyeBlink, open
    bs_closed: float = 0.75         # eyeBlink, shut
    blink_half_s: float = 0.12      # this driver's normal blink, half-amplitude duration
    blink_rate: float = 17.0        # per minute
    reopen_avr: float = 0.06        # normal reopening amplitude-velocity ratio, s
    mar_rest: float = 0.05
    mouth_width_rest: float = 0.0
    yaw_zero: float = 0.0
    pitch_zero: float = 0.0
    roll_zero: float = 0.0
    yaw_wobble: float = 2.0         # normal head movement, deg (robust std)
    pitch_wobble: float = 2.0
    roll_wobble: float = 1.5
    gaze_h_zero: float = 0.0
    gaze_v_zero: float = 0.0
    interocular_px: float = 100.0
    brightness: float = 0.0
    n_samples: int = 0
    n_blinks: int = 0
    closed_estimated: bool = True   # no eyes-closed step yet: closed level from population data
    complete: bool = False
    version: int = 2
    quality: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ear_closed <= 0:
            self.ear_closed = self.ear_open * 0.33

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Calibration":
        known = {k: d[k] for k in d if k in cls.__dataclass_fields__}
        cal = cls(**known)
        if int(d.get("version", 1)) < 2:
            # A version-1 file only knew the 75th-percentile open EAR. The
            # median sits about 6 % lower (measured on a real session), and
            # the closed level is estimated.
            cal.ear_open = float(d.get("ear_open", 0.30)) * 0.94
            cal.ear_closed = cal.ear_open * 0.33
            cal.closed_estimated = True
            cal.version = 2
        return cal

    @property
    def eye_size(self) -> str:
        return "small" if self.ear_open < 0.23 else "large" if self.ear_open > 0.32 else "medium"

    def summary(self) -> dict[str, Any]:
        """The plain summary shown at the end of the guided calibration."""
        return {
            "eye_size": self.eye_size,
            "ear_open": round(self.ear_open, 3), "ear_closed": round(self.ear_closed, 3),
            "separation": round((self.ear_open - self.ear_closed) / max(self.ear_open, 1e-6), 2),
            "blink_ms": int(round(1000 * self.blink_half_s)), "blink_rate": round(self.blink_rate, 1),
            "blinks_seen": self.n_blinks,
            "head": {"yaw": round(self.yaw_zero, 1), "pitch": round(self.pitch_zero, 1),
                     "roll": round(self.roll_zero, 1)},
            "wobble": {"yaw": round(self.yaw_wobble, 1), "pitch": round(self.pitch_wobble, 1)},
            "closed_estimated": self.closed_estimated, "quality": dict(self.quality),
        }


def _robust_std(v: np.ndarray) -> float:
    if len(v) < 3:
        return 0.0
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


class Calibrator:
    """The look-ahead and eyes-closed steps (F24-F27).

    ``feed`` collects look-ahead frames; ``finish`` turns them into a
    Calibration (closed level estimated) once at least ``duration_s`` have
    passed and enough blinks were seen (extending to ``max_duration_s``).
    ``start_closed`` / ``feed_closed`` / ``finish_closed`` then learn the
    closed level. ``hint`` is the live advice for the screen.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.duration_s = _cfg(cfg, "duration_s", 15.0)
        self.max_duration_s = _cfg(cfg, "max_duration_s", 25.0)
        self.min_fraction = _cfg(cfg, "min_tracking_fraction", 0.60)
        self.min_samples = _cfg(cfg, "min_open_samples", 30)
        self.max_rel_pose = _cfg(cfg, "max_relative_pose_deg", 12.0)
        self.max_steady = _cfg(cfg, "max_wobble_deg", 4.0)
        self.min_blinks = _cfg(cfg, "min_blinks", 3)
        self.min_separation = _cfg(cfg, "min_separation", 0.30)
        self.dark = _cfg(cfg, "min_brightness", 45.0)
        self.bright = _cfg(cfg, "max_brightness", 235.0)
        self.closer = _cfg(cfg, "min_face_frac", 0.06)
        self.farther = _cfg(cfg, "max_face_frac", 0.32)
        self.facing = _cfg(cfg, "max_facing_deg", 28.0)
        self.closed_lead_s = _cfg(cfg, "closed_lead_s", 0.7)
        self.closed_ratio = _cfg(cfg, "estimated_closed_ratio", 0.33)
        self.attempts = 0
        self.last_failure: Optional[str] = None
        self.failure_code: Optional[str] = None
        self._t0: Optional[float] = None
        self._rows: list[tuple] = []
        self._seen = 0
        self._recent: Deque[tuple[float, float, float]] = deque()
        self._closed: Optional[list[tuple]] = None
        self._closed_t0: Optional[float] = None
        self.hint = ""

    # -- compatibility with the old calibrator's surface -------------------- #

    @property
    def active(self) -> bool:
        return self._t0 is not None

    def progress(self, t: float) -> float:
        if self._t0 is None:
            return 0.0
        return min(1.0, (t - self._t0) / self.duration_s)

    def stats(self, t: Optional[float] = None) -> dict[str, Any]:
        el = (t - self._t0) if (self._t0 is not None and t is not None) else 0.0
        return {"seen": self._seen, "usable": len(self._rows),
                "fraction": len(self._rows) / self._seen if self._seen else 0.0,
                "fps": self._seen / el if el > 0.3 else 0.0, "attempts": self.attempts,
                "hint": self.hint, "need_fraction": self.min_fraction,
                "need_samples": self.min_samples, "rejected_pose": self._seen - len(self._rows),
                "raw_yaw": 0.0, "raw_pitch": 0.0}

    # -- live hint ------------------------------------------------------------ #

    def _hint(self, t: float, x: Optional[EyeInputs], yaw: float, pitch: float) -> str:
        if x is None:
            return "no_face"
        if x.iod_frac is not None and x.iod_frac < self.closer:
            return "closer"
        if x.iod_frac is not None and x.iod_frac > self.farther:
            return "farther"
        if x.brightness is not None and x.brightness < self.dark:
            return "dark"
        if x.brightness is not None and x.brightness > self.bright:
            return "bright"
        if abs(yaw) > self.facing or abs(pitch) > self.facing:
            return "face_camera"
        self._recent.append((t, yaw, pitch))
        while self._recent and self._recent[0][0] < t - 0.6:
            self._recent.popleft()
        if len(self._recent) > 3:
            ys = [r[1] for r in self._recent]
            ps = [r[2] for r in self._recent]
            if max(ys) - min(ys) > 7 or max(ps) - min(ps) > 7:
                return "still"
        return ""

    def observe(self, t: float, x: Optional[EyeInputs], yaw: float = 0.0, pitch: float = 0.0) -> str:
        """Update and return the live hint, whatever step is running."""
        self.hint = self._hint(t, x, yaw, pitch)
        return self.hint

    # -- look ahead ----------------------------------------------------------- #

    def start(self, t: float) -> None:
        """(Re)start the look-ahead. A failure's code and reason stay readable
        until the next calibration is started from outside (``reset``)."""
        self._t0 = t
        self._rows = []
        self._seen = 0
        self._closed = None

    def reset(self) -> None:
        self.attempts = 0
        self.failure_code = None
        self.last_failure = None

    def feed(self, t: float, ear: float, mar: float, pose, gaze: tuple[float, float, bool],
             iod: float, x: Optional[EyeInputs] = None) -> None:
        if self._t0 is None:
            return
        self._seen += 1
        self.observe(t, x, pose.yaw if pose.valid else 0.0, pose.pitch if pose.valid else 0.0)
        if not pose.valid:
            return
        x = x or EyeInputs(ear_l=ear, ear_r=ear)
        b = None
        if x.has_blendshapes:
            b = (x.blink_l + x.blink_r) / 2.0
        self._rows.append((t, x.ear_l, x.ear_r, x.width_l, x.width_r, x.edge_l, x.edge_r,
                           pose.yaw, pose.pitch, pose.roll, gaze[0] if gaze[2] else np.nan,
                           gaze[1] if gaze[2] else np.nan, iod, mar, x.mouth_width,
                           np.nan if b is None else b,
                           np.nan if x.brightness is None else x.brightness))

    def _ears(self, rows, yaw0: float, pitch0: float) -> np.ndarray:
        p = Personal({})
        tmp = Calibration(yaw_zero=yaw0, pitch_zero=pitch0)
        out = []
        for r in rows:
            e = p.ear(EyeInputs(ear_l=r[1], ear_r=r[2], width_l=r[3], width_r=r[4], edge_l=r[5], edge_r=r[6]))
            out.append(np.nan if e is None else p.compensate(e, r[7], r[8], tmp))
        return np.asarray(out, dtype=float)

    def finish(self, t: float) -> Optional[Calibration]:
        """The look-ahead result, once it is long enough; None until then."""
        if self._t0 is None or t - self._t0 < self.duration_s - 1e-6:
            return None
        rows = self._rows
        el = max(t - self._t0, 1e-6)
        fail = None
        if len(rows) < self.min_samples or len(rows) < self.min_fraction * self._seen:
            fail = ("no_face", "Ollie couldn't see your face steadily. Check the light and that the camera faces you.")
        if fail is None:
            a = np.array([r[7:10] for r in rows], dtype=float)
            yaw0, pitch0, roll0 = (float(np.median(a[:, i])) for i in range(3))
            keep = (np.abs(a[:, 0] - yaw0) <= self.max_rel_pose) & (np.abs(a[:, 1] - pitch0) <= self.max_rel_pose)
            rows = [r for r, k in zip(rows, keep) if k]
            a = a[keep]
            wy, wp, wr = (_robust_std(a[:, i]) for i in range(3))
            if wy > self.max_steady or wp > self.max_steady:
                fail = ("still", "Your head moved a lot. Sit still and look ahead.")
        if fail is None:
            br = np.array([r[16] for r in rows], dtype=float)
            br = br[~np.isnan(br)]
            if len(br) and np.median(br) < self.dark:
                fail = ("dark", "It's too dark for the camera. Turn on a light or the infrared.")
            elif len(br) and np.median(br) > self.bright:
                fail = ("bright", "Too much light on your face. Shade the camera or your face.")
        if fail is None:
            ears = self._ears(rows, yaw0, pitch0)
            ok = ~np.isnan(ears)
            ears_ok = ears[ok]
            if len(ears_ok) < self.min_samples:
                fail = ("no_face", "Ollie couldn't see your eyes clearly.")
        if fail is None:
            med = float(np.median(ears_ok))
            open_mask = ears_ok > 0.8 * med
            ear_open = float(np.median(ears_ok[open_mask]))
            closed_est = ear_open * self.closed_ratio
            o = (ears - closed_est) / max(ear_open - closed_est, 1e-4)
            ts = np.array([r[0] for r in rows], dtype=float)
            # Blinks during the look-ahead, on the provisional scale.
            det = BlinkDetector({"blink_window_s": 1e9})
            for ti, oi in zip(ts, o):
                det.update(float(ti), None if np.isnan(oi) else float(oi), True)
            blinks = det.judged()
            if len(blinks) < self.min_blinks and el < self.max_duration_s:
                return None          # keep looking: blink stats need a few blinks
            bs = np.array([r[15] for r in rows], dtype=float)
            bs = bs[~np.isnan(bs)]
            mars = np.array([r[13] for r in rows], dtype=float)
            mw = np.array([r[14] for r in rows], dtype=float)
            gh = np.array([r[10] for r in rows], dtype=float)
            gv = np.array([r[11] for r in rows], dtype=float)
            cal = Calibration(
                ear_open=ear_open, ear_closed=closed_est,
                ear_p10=float(np.percentile(ears_ok[open_mask], 10)),
                ear_p90=float(np.percentile(ears_ok[open_mask], 90)),
                ear_std=max(float(np.std(ears_ok[open_mask])), 1e-3),
                bs_open=float(np.median(bs)) if len(bs) else 0.05,
                bs_closed=0.75,
                blink_half_s=float(np.median([b.half_s for b in blinks])) if len(blinks) >= 2 else 0.12,
                blink_rate=len(blinks) * 60.0 / el if blinks else 17.0,
                reopen_avr=float(np.median([b.avr for b in blinks if b.avr > 0])) if any(b.avr > 0 for b in blinks) else 0.06,
                mar_rest=float(np.median(mars)), mouth_width_rest=float(np.median(mw)) if len(mw) else 0.0,
                yaw_zero=yaw0, pitch_zero=pitch0, roll_zero=roll0,
                yaw_wobble=max(wy, 0.5), pitch_wobble=max(wp, 0.5), roll_wobble=max(wr, 0.5),
                gaze_h_zero=float(np.nanmedian(gh)) if np.any(~np.isnan(gh)) else 0.0,
                gaze_v_zero=float(np.nanmedian(gv)) if np.any(~np.isnan(gv)) else 0.0,
                interocular_px=float(np.median([r[12] for r in rows])),
                brightness=float(np.median(br)) if len(br) else 0.0,
                n_samples=len(rows), n_blinks=len(blinks), closed_estimated=True, complete=True,
                quality={"face": "ok", "steady": "ok", "light": "ok" if len(br) else "unknown",
                         "blinks": "ok" if len(blinks) >= self.min_blinks else "few",
                         "separation": "estimated"},
            )
            self._t0 = None
            self.last_failure = None
            self.failure_code = None
            return cal
        self.attempts += 1
        self.failure_code, self.last_failure = fail
        self.start(t)
        return None

    # -- eyes closed ------------------------------------------------------------ #

    def start_closed(self, t: float) -> None:
        self._closed = []
        self._closed_t0 = t

    def feed_closed(self, t: float, x: Optional[EyeInputs], pose) -> None:
        if self._closed is None or x is None or self._closed_t0 is None:
            return
        if t - self._closed_t0 < self.closed_lead_s:
            return
        b = (x.blink_l + x.blink_r) / 2.0 if x.has_blendshapes else np.nan
        self._closed.append((x.ear_l, x.ear_r, x.width_l, x.width_r, x.edge_l, x.edge_r,
                             pose.yaw, pose.pitch, b))

    def finish_closed(self, cal: Calibration) -> tuple[bool, str, str]:
        """Learn the closed level into ``cal``. (ok, code, reason)."""
        rows = self._closed or []
        self._closed = None
        if len(rows) < 5:
            return False, "no_face", "Ollie couldn't see your eyes while they were closed."
        p = Personal({})
        ears = []
        for r in rows:
            e = p.ear(EyeInputs(ear_l=r[0], ear_r=r[1], width_l=r[2], width_r=r[3], edge_l=r[4], edge_r=r[5]))
            if e is not None:
                ears.append(p.compensate(e, r[6], r[7], cal))
        if len(ears) < 5:
            return False, "no_face", "Ollie couldn't see your eyes while they were closed."
        ears = np.sort(np.asarray(ears))
        closed = float(np.median(ears[: max(3, int(len(ears) * 0.6))]))
        sep = (cal.ear_open - closed) / max(cal.ear_open, 1e-6)
        bs = np.array([r[8] for r in rows], dtype=float)
        bs = bs[~np.isnan(bs)]
        bs_closed = float(np.median(bs)) if len(bs) else None
        bs_sep = (bs_closed - cal.bs_open) if bs_closed is not None else 0.0
        if sep < self.min_separation and bs_sep < 0.35:
            cal.quality["separation"] = "poor"
            return False, "separation", ("Ollie couldn't tell your open and closed eyes apart. "
                                         "Close your eyes fully, and check the light.")
        cal.ear_closed = min(closed, cal.ear_open * 0.7)
        if bs_closed is not None and bs_sep >= 0.25:
            cal.bs_closed = bs_closed
        cal.closed_estimated = False
        cal.quality["separation"] = "ok" if sep >= self.min_separation else "blendshapes"
        return True, "", ""
