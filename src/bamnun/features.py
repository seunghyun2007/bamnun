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

from .eyes import (BlinkDetector, Calibration, Calibrator, Conditions, EyeInputs,  # noqa: F401
                   NodDetector, Personal, RollingPerclos)

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
# Head tracker (looking away)
# --------------------------------------------------------------------------- #


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
    """Everything the state estimator needs from one frame.

    Eye measures are on the driver's personal openness scale (SPEC.md, 15):
    1.0 = their normal open level, 0.0 = their closed level.
    """

    t: float = 0.0
    face_found: bool = False
    ear_raw: float = 0.0
    ear: float = 0.0                 # pose-corrected EAR used for openness
    ear_norm: float = 1.0            # openness now (personal scale, fused)
    eye_closed: bool = False         # inside a blink or closure right now
    ongoing_closure_s: float = 0.0
    microsleep_now: bool = False
    shut_now: bool = False           # shut longer than a normal blink ("Eyes closed")
    openness: float = 1.0            # typical openness over the last 45 s (heavy lids)
    slow_blink_fraction: float = 0.0 # share of recent blinks that were long (0.3-0.5 s)
    long_blinks_per_min: float = 0.0
    mean_reopen_s: float = 0.0       # mean reopening amplitude-velocity ratio
    reopen_ratio: float = 1.0        # ... relative to the driver's normal
    looking_down: bool = False
    reliable: bool = True            # eye measures can be trusted in this frame
    unreliable: str = ""             # why not: smile, talk, yawn, lighting, edge, ...
    expression: str = ""
    yawn_now: bool = False
    o_ear: Optional[float] = None    # openness from EAR alone
    o_bs: Optional[float] = None     # openness from the eyeBlink blendshape alone
    perclos: float = 0.0             # P80 on the personal scale, reliable time only
    blink_rate_per_min: float = 0.0
    blink_rate_baseline: float = 17.0
    mean_blink_duration_s: float = 0.0   # median half-amplitude duration of recent blinks
    blink_baseline_s: float = 0.12       # this driver's normal blink
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
    nod_count: int = 0               # nods in the last nod_window_s
    head_drop: bool = False          # the face went down with the head and is lost
    gaze_h: float = 0.0
    gaze_v: float = 0.0
    gaze_valid: bool = False
    off_road: bool = False          # outside the forward cone right now
    off_road_alarm: bool = False    # ...and for longer than off_road_alert_s
    off_road_glance_s: float = 0.0
    glance_region: str = ""
    glance_dwell_s: float = 0.0
    long_glance_count: int = 0
    interocular_px: float = 0.0
    blink_event: Optional[str] = None

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["blink_event"] = d["blink_event"] or ""
        for k in ("o_ear", "o_bs"):
            if d[k] is None:
                d[k] = ""
        return d


class FeatureExtractor:
    """Landmarks in, FeatureFrame out. Owns all the per-driver state."""

    # The evaluation harness passes simulator frames as ``extra``.
    accepts_extra = True

    def __init__(self, features_cfg: dict[str, Any], calib_cfg: dict[str, Any]) -> None:
        self.cfg = features_cfg
        eyes = dict(features_cfg.get("eyes") or {})
        self.personal = Personal(eyes)
        self.conditions = Conditions(eyes)
        self.blinks = BlinkDetector(eyes)
        self.nods = NodDetector(features_cfg.get("nod") or {})
        self.head = HeadTracker(features_cfg)
        self.perclos_meter = RollingPerclos(float(features_cfg.get("perclos_window_s", 60.0)),
                                            float(eyes.get("perclos_closed_level", 0.20)))
        self.open_window_s = float(features_cfg.get("openness_window_s", 45.0))
        self.look_down_pitch = float(features_cfg.get("look_down_pitch_deg", 10.0))
        self.shut_level = float(eyes.get("shut_level", 0.25))
        self.shut_each = float(eyes.get("shut_each_level", 0.40))
        self.shut_label_s = float(eyes.get("eyes_closed_label_s", 0.30))
        self.micro_s = float(eyes.get("microsleep_s", 0.50))
        self.micro_down_s = float(eyes.get("microsleep_looking_down_s", 1.5))
        self.micro_other_s = float(eyes.get("microsleep_unreliable_s", 1.0))
        self.head_drop_micro_s = float((features_cfg.get("nod") or {}).get("head_drop_microsleep_s", 0.5))
        self.min_blinks = int(eyes.get("min_blinks_for_stats", 5))
        self.calibrator = Calibrator(calib_cfg)
        self.calibration = Calibration()
        self.candidate: Optional[Calibration] = None
        self.hold = False
        self._closing = False
        self._reset_live()

    def _reset_live(self) -> None:
        self._open: Deque[tuple[float, float]] = deque()
        self._open_cache = (-1e9, 1.0)
        self._shut_since: Optional[float] = None
        self._micro_latched = False
        self._micro: Deque[float] = deque()
        self._reliable_s: Deque[tuple[float, float]] = deque()
        self._last_t: Optional[float] = None
        self.blinks.events.clear()
        self.blinks.closed = False

    # -- calibration ---------------------------------------------------------- #

    def start_calibration(self, t: float, hold: bool = False) -> None:
        """Start the look-ahead step.

        ``hold`` is the guided recalibration from the phone: with a
        calibration already in place, detection carries on with the old one
        while the new one is measured, and the result waits in ``candidate``
        until the eyes-closed step passes and the caller commits it.
        """
        self.hold = bool(hold and self.calibration.complete)
        self.candidate = None
        self._closing = False
        self.calibrator.failure_code = None
        self.calibrator.last_failure = None
        self.calibrator.start(t)
        if not self.hold:
            self._reset_live()

    def start_closed(self, t: float) -> None:
        """Start the eyes-closed step (after the look-ahead step finished)."""
        self._closing = True
        self.calibrator.start_closed(t)

    def finish_closed(self) -> tuple[bool, str, str]:
        """Learn the closed level from the eyes-closed step. (ok, code, reason)"""
        self._closing = False
        target = self.candidate if self.hold else self.calibration
        if target is None or not target.complete:
            return False, "no_calibration", "Run the look-ahead step first."
        res = self.calibrator.finish_closed(target)
        if not self.hold:
            self._reset_live()
        return res

    def calibrate_closed(self, t: float, frame) -> None:
        """Evaluation helper: one eyes-closed frame (starts the step if needed)."""
        if not self._closing:
            self.start_closed(t)
        self.measure(t, 0.0, getattr(frame, "mar", 0.05),
                     HeadPose(frame.yaw, frame.pitch, frame.roll, True), (0.0, 0.0, True),
                     getattr(frame, "iod", 120.0), extra=frame)

    def end_closed(self) -> tuple[bool, str, str]:
        return self.finish_closed() if self._closing else (True, "", "")

    def cancel_calibration(self) -> None:
        """Stop measuring; whatever calibration was in place stays."""
        self.calibrator._t0 = None
        self.calibrator._closed = None
        self._closing = False
        self.candidate = None
        self.hold = False

    def commit_candidate(self) -> bool:
        if self.candidate is None:
            return False
        self.calibration = self.candidate
        self.candidate = None
        self.hold = False
        self._reset_live()
        return True

    @property
    def calibrating(self) -> bool:
        """Calibrating with no usable baseline: detection is paused."""
        return self.calibrator.active and not self.hold

    @property
    def measuring(self) -> bool:
        return self.calibrator.active or self._closing

    def set_calibration(self, cal: Calibration) -> None:
        self.calibration = cal
        self._reset_live()

    # -- frames ----------------------------------------------------------------- #

    def update(self, t: float, landmarks, brightness: Optional[float] = None) -> FeatureFrame:
        if landmarks is None or not landmarks.ok:
            return self.no_face(t)
        pts = landmarks.points
        ear_r, ear_l = both_eye_ear(pts)
        mar = mouth_aspect_ratio(pts)
        pose = solve_head_pose(pts, landmarks.image_size)
        gaze = gaze_offset(pts)
        iod = interocular_px(pts)
        x = EyeInputs.from_landmarks(landmarks, ear_r=ear_r, ear_l=ear_l, iod=iod, brightness=brightness)
        return self.measure(t, max(ear_r, ear_l), mar, pose, gaze, iod, extra=x)

    def no_face(self, t: float) -> FeatureFrame:
        """No face this frame. If it went down with the head, it's a head drop."""
        if self.calibrator.active:
            self.calibrator.observe(t, None)
        if not self.calibration.complete or self.calibrating:
            return FeatureFrame(t=t, face_found=False)
        dropped = self.nods.lost(t)
        micro = False
        if dropped and self.nods.head_drop_since is not None:
            micro = t - self.nods.head_drop_since >= self.head_drop_micro_s
            if micro and not self._micro_latched:
                self._micro_latched = True
                self._micro.append(t)
        else:
            self._micro_latched = False
        return FeatureFrame(t=t, face_found=False, head_drop=dropped, microsleep_now=micro,
                            shut_now=micro, nod_count=self.nods.count(),
                            microsleep_count=len(self._micro))

    @staticmethod
    def _inputs(extra, ear_raw: float, iod: float) -> EyeInputs:
        if isinstance(extra, EyeInputs):
            return extra
        if extra is None:
            return EyeInputs(ear_l=ear_raw, ear_r=ear_raw)
        f = extra          # a simulator frame
        hide_l = f.width_l < 0.5 * f.width_r
        hide_r = f.width_r < 0.5 * f.width_l
        return EyeInputs(
            ear_l=f.ear_l, ear_r=f.ear_r, width_l=f.width_l / max(f.width_l, f.width_r),
            width_r=f.width_r / max(f.width_l, f.width_r), edge=bool(f.edge),
            edge_l=bool(f.edge and hide_l), edge_r=bool(f.edge and hide_r),
            blink_l=f.blink_l, blink_r=f.blink_r, squint_l=f.squint_l, squint_r=f.squint_r,
            jaw=f.jaw, smile=f.smile, cheek=f.cheek, mouth_width=0.0,
            brightness=f.brightness, iod_frac=f.iod / 1280.0,
        )

    def measure(self, t: float, ear_raw: float, mar: float, pose: HeadPose,
                gaze: tuple[float, float, bool] = (0.0, 0.0, False),
                iod: float = 120.0, extra=None) -> FeatureFrame:
        """Everything after the landmark geometry, for one frame with a face."""
        x = self._inputs(extra, ear_raw, iod)
        if self._closing:
            self.calibrator.observe(t, x, pose.yaw, pose.pitch)
            self.calibrator.feed_closed(t, x, pose)
        if self.calibrator.active:
            self.calibrator.feed(t, ear_raw, mar, pose, gaze, iod, x)
            cal = self.calibrator.finish(t)
            if cal is not None:
                if self.hold:
                    self.candidate = cal
                else:
                    self.calibration = cal
                    self._reset_live()
        # The eyes-closed step's frames are calibration, not driving: they
        # must not reach PERCLOS, blinks or the microsleep counter.
        if (self.calibrator.active and not self.hold) or not self.calibration.complete or self._closing:
            return FeatureFrame(t=t, face_found=True, ear_raw=ear_raw, ear=ear_raw, mar=mar,
                                yaw=pose.yaw, pitch=pose.pitch, roll=pose.roll,
                                pose_valid=pose.valid, gaze_h=gaze[0], gaze_v=gaze[1],
                                gaze_valid=gaze[2], interocular_px=iod)
        return self._detect(t, ear_raw, mar, pose, gaze, iod, x)

    def _detect(self, t, ear_raw, mar, pose, gaze, iod, x: EyeInputs) -> FeatureFrame:
        cal = self.calibration
        dt = 0.0 if self._last_t is None else max(0.0, min(0.5, t - self._last_t))
        self._last_t = t
        yaw = pose.yaw - cal.yaw_zero
        pitch = pose.pitch - cal.pitch_zero
        roll = pose.roll - cal.roll_zero
        off_road = self.head.update(t, yaw, pitch, pose.valid)

        o, o_ear, o_bs = self.personal.openness(x, pose.yaw, pose.pitch, cal)
        self.conditions.update(t, x, mar, cal)
        look_down = max(self.look_down_pitch, 3.0 * cal.pitch_wobble)
        reason = self.conditions.reason(t, x, yaw, pitch, look_down) if pose.valid else "pose"
        if not reason and off_road:
            reason = "off_road"
        if pose.valid and abs(pose.yaw) > self.conditions.max_camera_yaw:
            # Turned too far from the camera to see the eyes at all. Overrides
            # off_road: an off-road glance still counts (head.update above),
            # but these lids must not count as a closure.
            reason = "turned"
        if not reason and o_ear is not None and o_bs is not None and abs(o_ear - o_bs) > self.personal.disagree:
            # Glare or a landmark error: the two estimates disagree. Take the
            # more open one, so a reflection can't fake a closure.
            reason = "disagree"
            o = max(o_ear, o_bs)
        reliable = not reason and o is not None
        looking_down = reason == "looking_down"

        # Nods and head drops.
        self.nods.wobble = cal.pitch_wobble
        nod = self.nods.update(t, pitch, o) if pose.valid else None

        # Blinks (all frames tracked; only reliable ones count). Measured
        # from where the lids currently rest: with heavy lids at 55 % a blink
        # still closes from 55 % to 0, and must still be seen and timed.
        rest = max(self._open_cache[1], 0.35)
        ev = self.blinks.update(t, None if o is None else o / rest, reliable)

        # Shut eyes and the microsleep bypass.
        shut = o is not None and o <= self.shut_level
        if o_ear is not None and o_bs is not None:
            shut = shut and o_ear <= self.shut_each and o_bs <= self.shut_each
        if reason == "turned":
            shut = False                 # unseen, not shut
        if shut:
            if self._shut_since is None:
                self._shut_since = t
        else:
            self._shut_since = None
            self._micro_latched = False
        shut_s = t - self._shut_since if self._shut_since is not None else 0.0
        need = (self.micro_s if not reason or reason in ("off_road", "disagree")
                else self.micro_down_s if reason == "looking_down"
                else float("inf") if reason == "turned" else self.micro_other_s)
        micro = shut_s >= need
        if micro and not self._micro_latched:
            self._micro_latched = True
            self._micro.append(t)
        while self._micro and self._micro[0] < t - 60.0:
            self._micro.popleft()

        # PERCLOS and heavy lids over reliable time.
        self.perclos_meter.push(t, o, reliable)
        # Every reliable frame: blinks are ~3 % of frames and the median
        # ignores them, while a held squint (which keeps the blink detector
        # "closed") must count.
        if reliable:
            self._open.append((t, o))
        while self._open and self._open[0][0] < t - self.open_window_s:
            self._open.popleft()
        if t - self._open_cache[0] >= 0.5:
            vals = [v for _, v in self._open]
            self._open_cache = (t, float(np.median(vals)) if len(vals) >= 30 else 1.0)
        typical = self._open_cache[1]
        if reliable:
            self._reliable_s.append((t, dt))
        while self._reliable_s and self._reliable_s[0][0] < t - 60.0:
            self._reliable_s.popleft()

        blinks = self.blinks.judged()
        enough = len(blinks) >= self.min_blinks
        rel_min = max(sum(d for _, d in self._reliable_s) / 60.0, 1e-6)
        avrs = [b.avr for b in blinks if b.avr > 0]
        longs = sum(1 for b in blinks if b.kind == "long")
        yawns = len(self.conditions.yawns)
        return FeatureFrame(
            t=t, face_found=True, ear_raw=ear_raw,
            ear=float(self.personal.ear(x) or 0.0), ear_norm=float(o if o is not None else 1.0),
            eye_closed=self.blinks.closed, ongoing_closure_s=max(self.blinks.ongoing_s(t), shut_s),
            microsleep_now=micro, shut_now=shut_s >= self.shut_label_s,
            openness=typical,
            slow_blink_fraction=(longs / len(blinks)) if enough else 0.0,
            long_blinks_per_min=(longs / rel_min) if enough and rel_min > 0.25 else 0.0,
            mean_reopen_s=float(np.median(avrs)) if enough and avrs else 0.0,
            reopen_ratio=(float(np.median(avrs)) / max(cal.reopen_avr, 1e-3)) if enough and avrs else 1.0,
            looking_down=looking_down, reliable=reliable, unreliable=reason,
            expression=self.conditions.expression, yawn_now=self.conditions.yawn_now,
            o_ear=o_ear, o_bs=o_bs,
            perclos=self.perclos_meter.value,
            blink_rate_per_min=(len(blinks) / rel_min) if rel_min > 0.25 else 0.0,
            blink_rate_baseline=cal.blink_rate,
            mean_blink_duration_s=float(np.median([b.half_s for b in blinks])) if enough else 0.0,
            blink_baseline_s=cal.blink_half_s,
            microsleep_count=len(self._micro),
            long_closure_count=sum(1 for b in self.blinks.events if b.kind in ("long", "microsleep")),
            mar=mar, yawn_count=yawns, yawn_rate_per_hour=yawns * 6.0,
            yaw=yaw, pitch=pitch, roll=roll, pose_valid=pose.valid,
            pitch_std=self.head.pitch_std(), nodding=nod is not None,
            nod_count=self.nods.count(),
            gaze_h=gaze[0] - cal.gaze_h_zero, gaze_v=gaze[1] - cal.gaze_v_zero, gaze_valid=gaze[2],
            off_road=off_road, off_road_alarm=self.head.off_road_alarm,
            off_road_glance_s=self.head.current_glance_s,
            glance_region=self.head.glance_region, glance_dwell_s=self.head.glance_dwell_s,
            long_glance_count=self.head.long_glance_count(), interocular_px=iod,
            blink_event=(ev.kind if ev is not None else None),
        )
