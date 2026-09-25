"""Per-frame geometric features and the stateful trackers built on them.

Everything here is deliberately pure NumPy (cv2 only for solvePnP) so the
whole feature layer is unit-testable with synthetic landmark arrays. That
matters: you cannot debug a drowsiness detector by staring at a webcam, and
you certainly cannot show a judge a graph of its behaviour without being able
to drive it from a known input.

Three choices in here are worth defending in the report:

1. The closure threshold is a fraction of the DRIVER'S OWN calibrated
   open-eye EAR, not the literature's 0.21. EAR is scale-invariant but not
   shape-invariant: narrow eye apertures, which are common in Korean drivers,
   sit near 0.18 wide open. A fixed 0.21 threshold reports such a driver as
   permanently asleep. This is a real and testable failure of most student
   implementations and a strong point to make on a poster.

2. Microsleeps are reported while the eye is still shut, not after it
   reopens. A closure-duration metric that only fires on reopening cannot
   alert during the event it is meant to catch.

3. PERCLOS is integrated over time, not averaged over frames, so a dropped
   frame does not silently change the metric.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Deque, Optional, Sequence

import numpy as np

from .landmarks import (
    CHIN, LEFT_EYE_EAR, LEFT_EYE_INNER, LEFT_EYE_OUTER, LEFT_IRIS_CENTER,
    MOUTH_BOTTOM, MOUTH_LEFT, MOUTH_RIGHT, MOUTH_TOP, NOSE_TIP,
    PNP_LANDMARKS, PNP_MODEL_3D, RIGHT_EYE_EAR, RIGHT_EYE_INNER,
    RIGHT_EYE_OUTER, RIGHT_IRIS_CENTER,
)

# --------------------------------------------------------------------------- #
# Stateless geometry
# --------------------------------------------------------------------------- #


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a[:2] - b[:2]))


def eye_aspect_ratio(points: np.ndarray, idx: Sequence[int]) -> float:
    """Soukupova & Cech EAR over the canonical six points.

    EAR = (|p2-p6| + |p3-p5|) / (2 |p1-p4|)

    Returns 0.0 for a degenerate eye width, which the callers treat as
    "unmeasurable" rather than "closed".
    """
    p1, p2, p3, p4, p5, p6 = (points[i] for i in idx)
    width = _dist(p1, p4)
    if width <= 1e-6:
        return 0.0
    return (_dist(p2, p6) + _dist(p3, p5)) / (2.0 * width)


def both_eye_ear(points: np.ndarray) -> tuple[float, float]:
    """(right, left) EAR in subject frame."""
    return (
        eye_aspect_ratio(points, RIGHT_EYE_EAR),
        eye_aspect_ratio(points, LEFT_EYE_EAR),
    )


def mouth_aspect_ratio(points: np.ndarray) -> float:
    """Vertical inner-lip gap over mouth width. Yawn proxy."""
    width = _dist(points[MOUTH_LEFT], points[MOUTH_RIGHT])
    if width <= 1e-6:
        return 0.0
    return _dist(points[MOUTH_TOP], points[MOUTH_BOTTOM]) / width


def interocular_px(points: np.ndarray) -> float:
    """Outer-corner to outer-corner distance. The natural scale unit."""
    return _dist(points[RIGHT_EYE_OUTER], points[LEFT_EYE_OUTER])


def rotation_matrix_to_euler(R: np.ndarray) -> tuple[float, float, float]:
    """Rotation matrix to (yaw, pitch, roll) in degrees.

    Camera frame: x right, y down, z away from the lens. The decomposition is
    R = Rz(roll) . Rx(pitch) . Ry(yaw), so

        yaw   = rotation about the vertical axis   (head turning left/right)
        pitch = rotation about the lateral axis    (nodding)
        roll  = rotation about the optical axis    (head tilt)

    from which, writing M = Rx.Ry, the bottom row of R is unaffected by roll
    and the middle column is unaffected by yaw:

        R[2,1] =  sin(pitch)
        R[2,0] = -cos(pitch) sin(yaw)
        R[2,2] =  cos(pitch) cos(yaw)
        R[0,1] = -sin(roll) cos(pitch)
        R[1,1] =  cos(roll) cos(pitch)

    The previous version of this function read yaw out of atan2(R[1,0],
    R[0,0]), which is rotation about the OPTICAL axis, not the vertical one.
    The effect was that turning the head produced a change in the reported
    pitch and almost none in the reported yaw, so the off-road glance test
    was watching the wrong angle. Worth a unit test against a known rotation,
    which is what tests/test_features.py now does for each axis separately.

    The gimbal-lock branch matters in practice: a driver checking a blind spot
    genuinely reaches large angles, and a shoulder check can put pitch near
    the degenerate point.
    """
    sp = max(-1.0, min(1.0, float(R[2, 1])))
    pitch = math.asin(sp)
    cp = math.sqrt(max(0.0, 1.0 - sp * sp))
    if cp > 1e-6:
        yaw = math.atan2(-R[2, 0], R[2, 2])
        roll = math.atan2(-R[0, 1], R[1, 1])
    else:  # pitch at +-90 deg: yaw and roll are not separable
        yaw = 0.0
        roll = math.atan2(R[0, 2], R[0, 0])
    return (math.degrees(yaw), math.degrees(pitch), math.degrees(roll))


@dataclass(slots=True)
class HeadPose:
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    valid: bool = False


def solve_head_pose(points: np.ndarray, image_size: tuple[int, int]) -> HeadPose:
    """Perspective-n-Point on six facial points against a generic 3D head.

    The absolute angles carry a bias that depends on how far the driver's face
    departs from the generic model, so the pipeline uses angles RELATIVE to
    the calibration pose rather than raw values. Judges ask about this; the
    answer is that a per-driver zero is cheap and removes the bias entirely.
    """
    import cv2

    w, h = image_size
    image_pts = np.array([points[i][:2] for i in PNP_LANDMARKS], dtype=np.float64)

    focal = float(w)  # a sane pinhole guess; refine with a checkerboard later
    camera_matrix = np.array(
        [[focal, 0.0, w / 2.0], [0.0, focal, h / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    dist = np.zeros((4, 1))

    # SQPNP rather than the usual ITERATIVE. Six facial points are nearly
    # coplanar, which is an ill-conditioned configuration: the iterative
    # solver needs an initial guess and, given none, settles into the
    # mirror-ambiguous local minimum for small rotations. SQPNP is globally
    # optimal and needs no seed. Fall back for OpenCV older than 4.5.4.
    flag = getattr(cv2, "SOLVEPNP_SQPNP", cv2.SOLVEPNP_ITERATIVE)
    try:
        ok, rvec, _tvec = cv2.solvePnP(
            PNP_MODEL_3D, image_pts, camera_matrix, dist, flags=flag
        )
    except cv2.error:
        return HeadPose()
    if not ok or rvec is None:
        return HeadPose()
    R, _ = cv2.Rodrigues(rvec)
    yaw, pitch, roll = rotation_matrix_to_euler(R)
    # Signs, with the object frame matching the camera frame. Measured by
    # projecting a known rotation and watching which way the nose moves
    # relative to the eye midpoint, NOT assumed:
    #
    #   yaw   < 0  driver turned toward their OWN LEFT  (nose toward image right)
    #   yaw   > 0  driver turned toward their OWN RIGHT
    #   pitch > 0  chin down, driver looking down
    #   roll  > 0  head tilted toward their right shoulder
    #
    # This comment previously claimed positive yaw was a turn to the driver's
    # left, which is backwards; anything keyed to the sign (mirror zones, the
    # off-road cone) would have been mirrored. See test_features.py.
    return HeadPose(yaw=yaw, pitch=pitch, roll=roll, valid=True)


def gaze_offset(points: np.ndarray) -> tuple[float, float, bool]:
    """Iris displacement inside the eye opening, averaged over both eyes.

    Returns (horizontal, vertical, valid) where each component is roughly
    -1 .. +1 with 0 meaning the iris is centred. This is a coarse gaze proxy,
    not a calibrated gaze vector, and the report should say so: it is used
    only to distinguish "eyes toward the road" from "eyes on a phone in the
    lap", which is a large-angle decision.
    """
    try:
        r_iris = points[RIGHT_IRIS_CENTER]
        l_iris = points[LEFT_IRIS_CENTER]
    except IndexError:
        return (0.0, 0.0, False)

    out = []
    for iris, outer, inner, ear_idx in (
        (r_iris, points[RIGHT_EYE_OUTER], points[RIGHT_EYE_INNER], RIGHT_EYE_EAR),
        (l_iris, points[LEFT_EYE_OUTER], points[LEFT_EYE_INNER], LEFT_EYE_EAR),
    ):
        centre = (outer[:2] + inner[:2]) / 2.0
        half_w = _dist(outer, inner) / 2.0
        if half_w <= 1e-6:
            continue
        # Vertical scale from the eyelid opening, floored so a nearly closed
        # eye does not produce an enormous normalised offset.
        upper = points[ear_idx[1]][:2]
        lower = points[ear_idx[5]][:2]
        half_h = max(float(np.linalg.norm(upper - lower)) / 2.0, half_w * 0.15)
        d = iris[:2] - centre
        out.append((d[0] / half_w, d[1] / half_h))

    if not out:
        return (0.0, 0.0, False)
    arr = np.asarray(out, dtype=np.float64)
    return (float(arr[:, 0].mean()), float(arr[:, 1].mean()), True)


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #


class Ewma:
    """Exponentially weighted moving average with an explicit first sample."""

    __slots__ = ("alpha", "value")

    def __init__(self, alpha: float) -> None:
        self.alpha = float(alpha)
        self.value: Optional[float] = None

    def update(self, x: float) -> float:
        if self.value is None:
            self.value = float(x)
        else:
            self.value = self.alpha * float(x) + (1.0 - self.alpha) * self.value
        return self.value

    def reset(self) -> None:
        self.value = None


class TimeWindow:
    """Rolling (timestamp, value) buffer with time-weighted statistics."""

    __slots__ = ("window_s", "_buf")

    def __init__(self, window_s: float) -> None:
        self.window_s = float(window_s)
        self._buf: Deque[tuple[float, float]] = deque()

    def push(self, t: float, v: float) -> None:
        self._buf.append((t, float(v)))
        cutoff = t - self.window_s
        while len(self._buf) > 1 and self._buf[0][0] < cutoff:
            self._buf.popleft()

    def clear(self) -> None:
        self._buf.clear()

    @property
    def span_s(self) -> float:
        if len(self._buf) < 2:
            return 0.0
        return self._buf[-1][0] - self._buf[0][0]

    def values(self) -> np.ndarray:
        return np.array([v for _, v in self._buf], dtype=np.float64)

    def times(self) -> np.ndarray:
        return np.array([t for t, _ in self._buf], dtype=np.float64)

    def mean(self) -> float:
        return float(self.values().mean()) if self._buf else 0.0

    def std(self) -> float:
        return float(self.values().std()) if len(self._buf) > 1 else 0.0

    def time_fraction_above(self, threshold: float) -> float:
        """Complement of ``time_fraction_below``, for exposure accounting."""
        if len(self._buf) < 2:
            return 0.0
        total = 0.0
        above = 0.0
        items = list(self._buf)
        for (t0, v0), (t1, _v1) in zip(items, items[1:]):
            dt = t1 - t0
            if dt <= 0:
                continue
            total += dt
            if v0 >= threshold:
                above += dt
        return above / total if total > 0 else 0.0

    def time_fraction_below(self, threshold: float) -> float:
        """Fraction of elapsed TIME (not of samples) spent below ``threshold``.

        Each interval between consecutive samples is attributed to the state at
        its left endpoint. With even sampling this equals the sample fraction;
        with dropped frames it does not, and the time-weighted answer is the
        correct one.
        """
        if len(self._buf) < 2:
            return 0.0
        total = 0.0
        below = 0.0
        items = list(self._buf)
        for (t0, v0), (t1, _v1) in zip(items, items[1:]):
            dt = t1 - t0
            if dt <= 0:
                continue
            total += dt
            if v0 < threshold:
                below += dt
        return below / total if total > 0 else 0.0


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #


@dataclass
class Calibration:
    """Per-driver baseline. Persisted so a repeat demo does not re-calibrate."""

    ear_open: float = 0.30
    ear_std: float = 0.02
    mar_rest: float = 0.05
    yaw_zero: float = 0.0
    pitch_zero: float = 0.0
    roll_zero: float = 0.0
    gaze_h_zero: float = 0.0
    gaze_v_zero: float = 0.0
    interocular_px: float = 100.0
    n_samples: int = 0
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Calibration":
        known = {k: d[k] for k in d if k in cls.__dataclass_fields__}
        return cls(**known)


class Calibrator:
    """Collects an open-eye baseline while the driver looks ahead.

    Robustness details that matter in practice: samples taken while the head
    is off-axis are rejected, and the open-eye EAR is taken as a high
    percentile rather than a mean, because the driver will blink during
    calibration and those frames must not drag the baseline down.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.duration_s = float(cfg.get("duration_s", 12.0))
        # Two separate requirements, because one absolute frame count cannot
        # express both.
        #
        # min_open_samples used to be 120 over a 12 s window, which silently
        # assumed at least 10 usable frames per second. Below that frame rate
        # calibration could NEVER complete however good the tracking was: the
        # window would expire short of the count, restart, and loop forever
        # with no symptom except a progress bar that kept returning to zero.
        # MediaPipe on a laptop CPU with a preview window can sit under 10 fps,
        # so this was reachable on ordinary hardware.
        #
        # The quality requirement is now a FRACTION of the frames actually
        # seen, which is frame-rate independent and is what "is tracking good
        # enough" actually means. The absolute floor is only there to stop a
        # 2 fps stream from passing on three lucky frames.
        self.min_fraction = float(cfg.get("min_tracking_fraction", 0.40))
        self.min_samples = int(cfg.get("min_open_samples", 30))
        self.max_yaw = float(cfg.get("max_yaw_deg", 20.0))
        self.max_pitch = float(cfg.get("max_pitch_deg", 20.0))
        self.attempts = 0
        self.last_failure: Optional[str] = None
        self._seen = 0
        self._rejected_pose = 0
        self._raw_yaw: list[float] = []
        self._raw_pitch: list[float] = []
        self._t0: Optional[float] = None
        self._ear: list[float] = []
        self._mar: list[float] = []
        self._yaw: list[float] = []
        self._pitch: list[float] = []
        self._roll: list[float] = []
        self._gh: list[float] = []
        self._gv: list[float] = []
        self._iod: list[float] = []

    @property
    def active(self) -> bool:
        return self._t0 is not None

    def start(self, t: float) -> None:
        self._t0 = t
        self._seen = 0
        self._rejected_pose = 0
        for lst in (self._ear, self._mar, self._yaw, self._pitch, self._roll,
                    self._gh, self._gv, self._iod, self._raw_yaw,
                    self._raw_pitch):
            lst.clear()

    def progress(self, t: float) -> float:
        if self._t0 is None:
            return 0.0
        return min(1.0, (t - self._t0) / self.duration_s)

    @property
    def median_raw_yaw(self) -> float:
        return float(np.median(self._raw_yaw)) if self._raw_yaw else 0.0

    @property
    def median_raw_pitch(self) -> float:
        return float(np.median(self._raw_pitch)) if self._raw_pitch else 0.0

    def stats(self, t: Optional[float] = None) -> dict[str, Any]:
        """Live diagnostics, shown on the calibration banner.

        Calibration is the one phase where the driver is looking at the screen
        and waiting, so it is the one phase that must explain itself while it
        is happening rather than after it fails.
        """
        usable = len(self._ear)
        elapsed = 0.0
        if self._t0 is not None and t is not None:
            elapsed = max(t - self._t0, 0.0)
        return {
            "seen": self._seen,
            "usable": usable,
            "rejected_pose": self._rejected_pose,
            "fraction": (usable / self._seen) if self._seen else 0.0,
            "fps": (self._seen / elapsed) if elapsed > 0.3 else 0.0,
            "need_fraction": self.min_fraction,
            "need_samples": self.min_samples,
            "attempts": self.attempts,
            "raw_yaw": self.median_raw_yaw,
            "raw_pitch": self.median_raw_pitch,
        }

    def feed(self, t: float, ear: float, mar: float, pose: HeadPose,
             gaze: tuple[float, float, bool], iod: float) -> None:
        if self._t0 is None:
            return
        self._seen += 1
        if pose.valid:
            # Kept regardless of acceptance, so a pose-gate rejection can
            # report what the angles actually were.
            self._raw_yaw.append(pose.yaw)
            self._raw_pitch.append(pose.pitch)
        # Head must be roughly forward for the pose zero to mean anything. The
        # raw PnP angles are used here because there is no zero yet.
        #
        # These limits come from the config. They used to be read into
        # self.max_yaw/max_pitch and then ignored in favour of a hardcoded 45
        # degrees, so the documented 12-degree gate did nothing.
        if pose.valid and (abs(pose.yaw) > self.max_yaw
                           or abs(pose.pitch) > self.max_pitch):
            self._rejected_pose += 1
            return
        self._ear.append(ear)
        self._mar.append(mar)
        if pose.valid:
            self._yaw.append(pose.yaw)
            self._pitch.append(pose.pitch)
            self._roll.append(pose.roll)
        if gaze[2]:
            self._gh.append(gaze[0])
            self._gv.append(gaze[1])
        if iod > 0:
            self._iod.append(iod)

    def finish(self, t: float) -> Optional[Calibration]:
        if self._t0 is None:
            return None
        # Tolerance, not a bare `< 1.0`. A caller that accumulates dt rather
        # than reading a clock lands on 11.999999999999863 for a nominal 12 s,
        # which silently skipped the evaluation for one more frame.
        if (t - self._t0) < self.duration_s - 1e-6:
            return None
        usable = len(self._ear)
        fraction = (usable / self._seen) if self._seen else 0.0
        elapsed = max(t - (self._t0 or t), 1e-6)
        fps = self._seen / elapsed

        if usable < self.min_samples or fraction < self.min_fraction:
            # Not enough usable data. Restart rather than commit a bad
            # baseline, but say WHY. A silent restart looks identical to a
            # hung progress bar, and the causes have completely different
            # fixes: no face at all means lighting, focus or framing; frames
            # rejected for pose means the driver is not facing the camera or
            # the generic-head bias in solvePnP exceeds the gate; a low frame
            # rate means the machine cannot keep up.
            self.attempts += 1
            if self._seen == 0:
                self.last_failure = ("no face detected at all; check lighting, "
                                     "focus and framing")
            elif self._rejected_pose > self._seen * 0.5:
                self.last_failure = (
                    f"{self._rejected_pose}/{self._seen} frames rejected for head "
                    f"pose outside +-{self.max_yaw:.0f} deg yaw / "
                    f"{self.max_pitch:.0f} deg pitch "
                    f"(median yaw {self.median_raw_yaw:+.0f}, "
                    f"pitch {self.median_raw_pitch:+.0f}); face the camera "
                    "squarely, or widen calibration.max_yaw_deg / max_pitch_deg"
                )
            elif usable < self.min_samples:
                self.last_failure = (
                    f"only {usable} usable frames in {elapsed:.0f}s "
                    f"({fps:.1f} fps), absolute minimum is {self.min_samples}; "
                    "the machine is too slow or tracking keeps dropping")
            else:
                self.last_failure = (
                    f"tracking {fraction*100:.0f}% of frames "
                    f"({usable}/{self._seen} at {fps:.1f} fps), need "
                    f"{self.min_fraction*100:.0f}%")
            self.start(t)
            return None

        ear = np.asarray(self._ear, dtype=np.float64)
        # 75th percentile: above the blinks, below any landmark outliers.
        ear_open = float(np.percentile(ear, 75))
        open_mask = ear >= ear_open * 0.9
        ear_std = float(ear[open_mask].std()) if open_mask.sum() > 5 else float(ear.std())

        cal = Calibration(
            ear_open=ear_open,
            ear_std=max(ear_std, 1e-3),
            mar_rest=float(np.median(self._mar)) if self._mar else 0.05,
            yaw_zero=float(np.median(self._yaw)) if self._yaw else 0.0,
            pitch_zero=float(np.median(self._pitch)) if self._pitch else 0.0,
            roll_zero=float(np.median(self._roll)) if self._roll else 0.0,
            gaze_h_zero=float(np.median(self._gh)) if self._gh else 0.0,
            gaze_v_zero=float(np.median(self._gv)) if self._gv else 0.0,
            interocular_px=float(np.median(self._iod)) if self._iod else 100.0,
            n_samples=len(self._ear),
            complete=True,
        )
        self._t0 = None
        return cal


# --------------------------------------------------------------------------- #
# Blink / closure tracking
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BlinkEvent:
    start_t: float
    end_t: float
    duration_s: float
    min_ear: float
    kind: str  # "blink" | "long_closure" | "microsleep"


class BlinkTracker:
    """Hysteretic closure detector with live microsleep reporting."""

    def __init__(self, features_cfg: dict[str, Any]) -> None:
        bl = features_cfg.get("blink", {})
        self.closed_fraction = float(features_cfg.get("ear_closed_fraction", 0.65))
        self.reopen_fraction = float(features_cfg.get("ear_reopen_fraction", 0.75))
        self.min_duration = float(bl.get("min_duration_s", 0.05))
        self.max_normal = float(bl.get("max_normal_duration_s", 0.40))
        self.microsleep = float(bl.get("microsleep_duration_s", 0.50))
        self.rate_window = float(bl.get("rate_window_s", 60.0))

        self._closed = False
        self._closure_start: Optional[float] = None
        self._closure_min_ear = 1.0
        self._events: Deque[BlinkEvent] = deque()
        self._microsleep_latched = False
        # The event appended when a microsleep latched mid-closure, held so the
        # reopen can finalise it rather than record the same closure twice.
        self._latched_event: Optional[BlinkEvent] = None
        self.ongoing_closure_s = 0.0

    def reset(self) -> None:
        self._closed = False
        self._closure_start = None
        self._microsleep_latched = False
        self._latched_event = None
        self.ongoing_closure_s = 0.0
        self._events.clear()

    def update(self, t: float, ear: float, ear_open: float) -> Optional[BlinkEvent]:
        """Feed one smoothed EAR sample. Returns a completed event, if any."""
        close_th = ear_open * self.closed_fraction
        open_th = ear_open * self.reopen_fraction
        event: Optional[BlinkEvent] = None

        if not self._closed:
            if 0.0 < ear < close_th:
                self._closed = True
                self._closure_start = t
                self._closure_min_ear = ear
                self._microsleep_latched = False
                self._latched_event = None
        else:
            self._closure_min_ear = min(self._closure_min_ear, ear)
            self.ongoing_closure_s = t - (self._closure_start or t)
            if ear > open_th:
                start = self._closure_start if self._closure_start is not None else t
                dur = t - start
                self._closed = False
                self._closure_start = None
                self.ongoing_closure_s = 0.0
                if self._latched_event is not None:
                    # This closure is ALREADY in the window: it was recorded the
                    # moment it latched, mid-shut, so the alert could fire during
                    # the event. Finalise that record instead of appending a
                    # second one. Appending counted every microsleep twice, and
                    # because the score saturates at 2 events per 60 s, a single
                    # real closure pinned the microsleep component at its maximum
                    # for a full minute: the driver was told they were DROWSY
                    # with their eyes measurably wider than their own baseline.
                    ev = self._latched_event
                    ev.end_t = t
                    ev.duration_s = dur
                    ev.min_ear = self._closure_min_ear
                    ev.kind = self._classify(dur)
                    event = ev
                    self._latched_event = None
                elif dur >= self.min_duration:
                    event = BlinkEvent(
                        start_t=start, end_t=t, duration_s=dur,
                        min_ear=self._closure_min_ear,
                        kind=self._classify(dur),
                    )
                    self._events.append(event)

        # Latch a microsleep DURING the closure so the alert can fire now.
        if self._closed and not self._microsleep_latched and \
                self.ongoing_closure_s >= self.microsleep:
            self._microsleep_latched = True
            start = self._closure_start if self._closure_start is not None else t
            event = BlinkEvent(
                start_t=start, end_t=t, duration_s=self.ongoing_closure_s,
                min_ear=self._closure_min_ear, kind="microsleep",
            )
            self._events.append(event)
            self._latched_event = event

        cutoff = t - self.rate_window
        while self._events and self._events[0].end_t < cutoff:
            self._events.popleft()
        return event

    def _classify(self, dur: float) -> str:
        if dur >= self.microsleep:
            return "microsleep"
        if dur > self.max_normal:
            return "long_closure"
        return "blink"

    # -- window statistics -------------------------------------------------- #

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def microsleep_in_progress(self) -> bool:
        """Eye shut right now, past the configured microsleep threshold."""
        return self._closed and self.ongoing_closure_s >= self.microsleep

    def blink_rate_per_min(self) -> float:
        n = sum(1 for e in self._events if e.kind == "blink")
        return n * 60.0 / self.rate_window

    def mean_blink_duration_s(self) -> float:
        d = [e.duration_s for e in self._events if e.kind == "blink"]
        return float(np.mean(d)) if d else 0.0

    def microsleep_count(self) -> int:
        return sum(1 for e in self._events if e.kind == "microsleep")

    def long_closure_count(self) -> int:
        return sum(1 for e in self._events if e.kind in ("long_closure", "microsleep"))


# --------------------------------------------------------------------------- #
# Yawn and head trackers
# --------------------------------------------------------------------------- #


class YawnTracker:
    """A yawn is a sustained wide mouth, not a momentarily wide one.

    Speech and laughter both cross any MAR threshold you pick; requiring the
    threshold to hold for a full second removes almost all of it.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        y = cfg.get("yawn", {})
        self.threshold = float(y.get("mar_threshold", 0.60))
        self.min_duration = float(y.get("min_duration_s", 1.0))
        self.window_s = float(y.get("window_s", 300.0))
        self._open_since: Optional[float] = None
        self._events: Deque[float] = deque()

    def update(self, t: float, mar: float) -> bool:
        """Returns True on the frame a yawn is confirmed."""
        confirmed = False
        if mar >= self.threshold:
            if self._open_since is None:
                self._open_since = t
            elif (t - self._open_since) >= self.min_duration:
                # Confirm once per continuous opening.
                if not self._events or self._events[-1] < self._open_since:
                    self._events.append(t)
                    confirmed = True
        else:
            self._open_since = None

        cutoff = t - self.window_s
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        return confirmed

    def count(self) -> int:
        return len(self._events)

    def rate_per_hour(self) -> float:
        return len(self._events) * 3600.0 / self.window_s


@dataclass(slots=True)
class _GlanceRegion:
    """A head pose window where a long-ish glance is a normal driving task.

    Angles are calibration-relative, so they describe where the target sits
    relative to THIS driver's forward pose, not absolute camera angles. The
    sign convention is the measured one in solve_head_pose: yaw < 0 is a turn
    toward the driver's own left.
    """

    name: str
    yaw_min: float
    yaw_max: float
    pitch_min: float
    pitch_max: float
    dwell_s: float

    @classmethod
    def from_cfg(cls, d: dict[str, Any], default_dwell: float) -> "_GlanceRegion":
        yaw = d.get("yaw", [-180.0, 180.0])
        pitch = d.get("pitch", [-180.0, 180.0])
        return cls(
            name=str(d.get("name", "region")),
            yaw_min=float(min(yaw)), yaw_max=float(max(yaw)),
            pitch_min=float(min(pitch)), pitch_max=float(max(pitch)),
            # A region may only ever be MORE permissive than the base rule;
            # a misconfigured region must not silently shorten the NHTSA dwell.
            dwell_s=max(float(d.get("dwell_s", default_dwell)), default_dwell),
        )

    def contains(self, yaw: float, pitch: float) -> bool:
        return (self.yaw_min <= yaw <= self.yaw_max
                and self.pitch_min <= pitch <= self.pitch_max)


class HeadTracker:
    """Off-road glance timing and nodding.

    The 2 s single-glance criterion comes from NHTSA's visual-manual driver
    distraction guidelines; it is a defensible number to cite rather than a
    threshold picked to make the demo work.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        h = cfg.get("head", {})
        self.yaw_limit = float(h.get("yaw_limit_deg", 25.0))
        self.pitch_limit = float(h.get("pitch_limit_deg", 20.0))
        self.off_road_alert_s = float(h.get("off_road_alert_s", 2.0))
        self.nod_window_s = float(h.get("nod_window_s", 10.0))
        self.nod_pitch_std = float(h.get("nod_pitch_std_deg", 6.0))
        self.regions = [_GlanceRegion.from_cfg(r, self.off_road_alert_s)
                        for r in h.get("permitted_regions", [])]
        self._pitch_window = TimeWindow(self.nod_window_s)
        self._off_since: Optional[float] = None
        self.current_glance_s = 0.0
        self._glance_dwell = self.off_road_alert_s
        self.glance_region = ""
        self._long_glances: Deque[float] = deque()
        self.glance_window_s = 120.0

    def region_for(self, yaw: float, pitch: float) -> Optional["_GlanceRegion"]:
        """The permitted region containing this pose, if any. First match wins."""
        for r in self.regions:
            if r.contains(yaw, pitch):
                return r
        return None

    def update(self, t: float, yaw: float, pitch: float, valid: bool) -> bool:
        """``yaw``/``pitch`` are calibration-relative. Returns off_road flag."""
        if not valid:
            return False
        self._pitch_window.push(t, pitch)

        off = abs(yaw) > self.yaw_limit or abs(pitch) > self.pitch_limit
        if off:
            # A look toward a mirror is a driving task; the same angle toward a
            # phone is not. The angle alone cannot separate them, so a named
            # region earns a longer dwell before the glance counts as off-road.
            region = self.region_for(yaw, pitch)
            dwell = region.dwell_s if region is not None else self.off_road_alert_s
            if self._off_since is None:
                self._off_since = t
                self._glance_dwell = dwell
                self.glance_region = region.name if region is not None else ""
            else:
                # Take the SHORTEST dwell seen during this glance. Sweeping from
                # a phone angle through a mirror zone must not buy extra time,
                # while sweeping from a mirror to a phone must shorten it: the
                # permissive direction has to be the one that cannot be entered
                # part-way through.
                if dwell < self._glance_dwell:
                    self._glance_dwell = dwell
                    self.glance_region = region.name if region is not None else ""
            self.current_glance_s = t - self._off_since
            if self.current_glance_s >= self._glance_dwell:
                if not self._long_glances or self._long_glances[-1] < self._off_since:
                    self._long_glances.append(t)
        else:
            self._off_since = None
            self.current_glance_s = 0.0
            self._glance_dwell = self.off_road_alert_s
            self.glance_region = ""

        cutoff = t - self.glance_window_s
        while self._long_glances and self._long_glances[0] < cutoff:
            self._long_glances.popleft()
        return off

    @property
    def glance_dwell_s(self) -> float:
        """The dwell this glance must exceed, after any region allowance."""
        return self._glance_dwell

    @property
    def off_road_alarm(self) -> bool:
        return self.current_glance_s >= self._glance_dwell

    def pitch_std(self) -> float:
        return self._pitch_window.std()

    def nodding(self) -> bool:
        return (self._pitch_window.span_s >= self.nod_window_s * 0.5
                and self._pitch_window.std() > self.nod_pitch_std)

    def long_glance_count(self) -> int:
        return len(self._long_glances)


# --------------------------------------------------------------------------- #
# Composite extractor
# --------------------------------------------------------------------------- #


@dataclass
class FeatureFrame:
    """Everything the state estimator needs from one frame."""

    t: float = 0.0
    face_found: bool = False
    ear_raw: float = 0.0
    ear: float = 0.0                 # smoothed
    ear_norm: float = 1.0            # ear / calibrated open EAR
    eye_closed: bool = False
    ongoing_closure_s: float = 0.0
    # Decided here, by the tracker that owns the configured threshold, rather
    # than re-derived downstream from ongoing_closure_s against a second copy
    # of the same number.
    microsleep_now: bool = False
    perclos: float = 0.0
    blink_rate_per_min: float = 0.0
    mean_blink_duration_s: float = 0.0
    microsleep_count: int = 0
    long_closure_count: int = 0
    mar: float = 0.0
    yawn_count: int = 0
    yawn_rate_per_hour: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    pose_valid: bool = False
    pitch_std: float = 0.0
    nodding: bool = False
    gaze_h: float = 0.0
    gaze_v: float = 0.0
    gaze_valid: bool = False
    off_road: bool = False          # outside the forward cone right now
    off_road_alarm: bool = False    # ...and for longer than off_road_alert_s
    off_road_glance_s: float = 0.0
    # Name of the permitted region this glance falls in ("" = none), and the
    # dwell it must exceed. Logged so a suppressed alert can be explained.
    glance_region: str = ""
    glance_dwell_s: float = 0.0
    long_glance_count: int = 0
    interocular_px: float = 0.0
    blink_event: Optional[str] = None

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["blink_event"] = d["blink_event"] or ""
        return d


class FeatureExtractor:
    """Landmarks in, FeatureFrame out. Owns all the per-driver state."""

    def __init__(self, features_cfg: dict[str, Any], calib_cfg: dict[str, Any]) -> None:
        self.cfg = features_cfg
        self.ear_ewma = Ewma(float(features_cfg.get("ear_smoothing_alpha", 0.4)))
        self.blink = BlinkTracker(features_cfg)
        self.yawn = YawnTracker(features_cfg)
        self.head = HeadTracker(features_cfg)
        self.perclos_window = TimeWindow(float(features_cfg.get("perclos_window_s", 60.0)))
        self.perclos_fraction = float(features_cfg.get("perclos_baseline_fraction", 0.80))
        self.calibrator = Calibrator(calib_cfg)
        self.calibration = Calibration()

    # -- calibration passthrough ------------------------------------------- #

    def start_calibration(self, t: float) -> None:
        self.calibrator.start(t)
        self.ear_ewma.reset()
        self.blink.reset()
        self.perclos_window.clear()

    @property
    def calibrating(self) -> bool:
        return self.calibrator.active

    def set_calibration(self, cal: Calibration) -> None:
        self.calibration = cal

    # -- main entry point --------------------------------------------------- #

    def update(self, t: float, landmarks) -> FeatureFrame:
        if landmarks is None or not landmarks.ok:
            return FeatureFrame(t=t, face_found=False)

        pts = landmarks.points
        ear_r, ear_l = both_eye_ear(pts)
        # Use the more open eye. A single occluded or badly tracked eye is the
        # most common landmark failure, and max() is far more robust than the
        # usual mean. Genuine one-eyed closure is not a thing in drowsiness.
        ear_raw = max(ear_r, ear_l)
        mar = mouth_aspect_ratio(pts)
        pose = solve_head_pose(pts, landmarks.image_size)
        gaze = gaze_offset(pts)
        iod = interocular_px(pts)

        if self.calibrator.active:
            self.calibrator.feed(t, ear_raw, mar, pose, gaze, iod)
            cal = self.calibrator.finish(t)
            if cal is not None:
                self.calibration = cal
            # During calibration report raw values and no alarms.
            return FeatureFrame(
                t=t, face_found=True, ear_raw=ear_raw, ear=ear_raw,
                mar=mar, yaw=pose.yaw, pitch=pose.pitch, roll=pose.roll,
                pose_valid=pose.valid, gaze_h=gaze[0], gaze_v=gaze[1],
                gaze_valid=gaze[2], interocular_px=iod,
            )

        cal = self.calibration
        ear = self.ear_ewma.update(ear_raw)
        ear_norm = ear / cal.ear_open if cal.ear_open > 1e-6 else 1.0

        event = self.blink.update(t, ear, cal.ear_open)
        self.perclos_window.push(t, ear_norm)
        perclos = self.perclos_window.time_fraction_below(self.perclos_fraction)
        self.yawn.update(t, mar)

        yaw = pose.yaw - cal.yaw_zero
        pitch = pose.pitch - cal.pitch_zero
        roll = pose.roll - cal.roll_zero
        off_road = self.head.update(t, yaw, pitch, pose.valid)

        return FeatureFrame(
            t=t,
            face_found=True,
            ear_raw=ear_raw,
            ear=ear,
            ear_norm=ear_norm,
            eye_closed=self.blink.is_closed,
            ongoing_closure_s=self.blink.ongoing_closure_s,
            microsleep_now=self.blink.microsleep_in_progress,
            perclos=perclos,
            blink_rate_per_min=self.blink.blink_rate_per_min(),
            mean_blink_duration_s=self.blink.mean_blink_duration_s(),
            microsleep_count=self.blink.microsleep_count(),
            long_closure_count=self.blink.long_closure_count(),
            mar=mar,
            yawn_count=self.yawn.count(),
            yawn_rate_per_hour=self.yawn.rate_per_hour(),
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            pose_valid=pose.valid,
            pitch_std=self.head.pitch_std(),
            nodding=self.head.nodding(),
            gaze_h=gaze[0] - cal.gaze_h_zero,
            gaze_v=gaze[1] - cal.gaze_v_zero,
            gaze_valid=gaze[2],
            off_road=off_road,
            off_road_alarm=self.head.off_road_alarm,
            off_road_glance_s=self.head.current_glance_s,
            glance_region=self.head.glance_region,
            glance_dwell_s=self.head.glance_dwell_s,
            long_glance_count=self.head.long_glance_count(),
            interocular_px=iod,
            blink_event=event.kind if event else None,
        )
