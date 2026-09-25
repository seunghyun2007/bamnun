"""Geometry and tracker tests driven by synthetic landmark arrays.

The point of these is that every threshold decision in the pipeline is
checkable against an input whose correct answer is known by construction. A
drowsiness detector that has only ever been tested by someone squinting at a
webcam has not been tested.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.features import (  # noqa: E402
    BlinkTracker, Calibration, Calibrator, Ewma, HeadTracker, TimeWindow,
    YawnTracker, both_eye_ear, eye_aspect_ratio, interocular_px,
    mouth_aspect_ratio, rotation_matrix_to_euler, solve_head_pose,
)
from bamnun.landmarks import (  # noqa: E402
    CHIN, LEFT_EYE_EAR, LEFT_EYE_OUTER, MOUTH_BOTTOM, MOUTH_LEFT, MOUTH_RIGHT,
    MOUTH_TOP, NOSE_TIP, PNP_LANDMARKS, PNP_MODEL_3D, RIGHT_EYE_EAR,
    RIGHT_EYE_OUTER,
)

N_LM = 478


def make_points(opening: float = 0.30, mouth_open: float = 0.05,
                eye_half_width: float = 15.0) -> np.ndarray:
    """Build a landmark array whose EAR equals ``opening`` by construction.

    For the six-point EAR with both vertical pairs at the same height h and a
    width w:  EAR = (h + h) / (2w) = h / w.  So set h = opening * w.
    """
    pts = np.zeros((N_LM, 3), dtype=np.float32)
    w = 2.0 * eye_half_width
    h = opening * w

    for idx_set, cx in ((RIGHT_EYE_EAR, 200.0), (LEFT_EYE_EAR, 300.0)):
        p1, p2, p3, p4, p5, p6 = idx_set
        cy = 150.0
        pts[p1] = (cx - eye_half_width, cy, 0.0)
        pts[p4] = (cx + eye_half_width, cy, 0.0)
        pts[p2] = (cx - eye_half_width / 2, cy - h / 2, 0.0)
        pts[p3] = (cx + eye_half_width / 2, cy - h / 2, 0.0)
        pts[p6] = (cx - eye_half_width / 2, cy + h / 2, 0.0)
        pts[p5] = (cx + eye_half_width / 2, cy + h / 2, 0.0)

    mw = 60.0
    pts[MOUTH_LEFT] = (220.0, 250.0, 0.0)
    pts[MOUTH_RIGHT] = (220.0 + mw, 250.0, 0.0)
    pts[MOUTH_TOP] = (250.0, 250.0 - mouth_open * mw / 2, 0.0)
    pts[MOUTH_BOTTOM] = (250.0, 250.0 + mouth_open * mw / 2, 0.0)
    return pts


# --------------------------------------------------------------------------- #
# Stateless geometry
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("target", [0.05, 0.12, 0.21, 0.30, 0.42])
def test_ear_matches_construction(target):
    pts = make_points(opening=target)
    assert eye_aspect_ratio(pts, RIGHT_EYE_EAR) == pytest.approx(target, abs=1e-5)
    assert eye_aspect_ratio(pts, LEFT_EYE_EAR) == pytest.approx(target, abs=1e-5)


def test_ear_is_scale_invariant():
    """The whole reason EAR is used: doubling the face must not change it."""
    small = eye_aspect_ratio(make_points(0.27, eye_half_width=10.0), RIGHT_EYE_EAR)
    large = eye_aspect_ratio(make_points(0.27, eye_half_width=40.0), RIGHT_EYE_EAR)
    assert small == pytest.approx(large, abs=1e-5)


def test_ear_degenerate_width_returns_zero():
    pts = make_points(0.3)
    pts[RIGHT_EYE_EAR[0]] = pts[RIGHT_EYE_EAR[3]]
    assert eye_aspect_ratio(pts, RIGHT_EYE_EAR) == 0.0


def test_both_eye_ear_and_max_selection():
    pts = make_points(0.30)
    # Collapse one eye only; the extractor uses max(), so the open eye wins.
    p1, p2, p3, p4, p5, p6 = RIGHT_EYE_EAR
    for i in (p2, p3, p5, p6):
        pts[i][1] = pts[p1][1]
    r, l = both_eye_ear(pts)
    assert r == pytest.approx(0.0, abs=1e-6)
    assert l == pytest.approx(0.30, abs=1e-5)
    assert max(r, l) == pytest.approx(0.30, abs=1e-5)


def test_mouth_aspect_ratio():
    assert mouth_aspect_ratio(make_points(mouth_open=0.70)) == pytest.approx(0.70, abs=1e-5)
    assert mouth_aspect_ratio(make_points(mouth_open=0.05)) == pytest.approx(0.05, abs=1e-5)


def test_interocular_distance():
    pts = make_points(eye_half_width=15.0)
    # outer corners are RIGHT_EYE_EAR[0] at x=185 and LEFT_EYE_EAR[3] at x=315
    assert interocular_px(pts) == pytest.approx(130.0, abs=1e-4)


def test_rotation_matrix_to_euler_identity():
    yaw, pitch, roll = rotation_matrix_to_euler(np.eye(3))
    assert (abs(yaw), abs(pitch), abs(roll)) == pytest.approx((0, 0, 0), abs=1e-9)


def _Ry(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a)],
                     [0, 1, 0],
                     [-math.sin(a), 0, math.cos(a)]])


def _Rx(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0],
                     [0, math.cos(a), -math.sin(a)],
                     [0, math.sin(a), math.cos(a)]])


def _Rz(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0],
                     [math.sin(a), math.cos(a), 0],
                     [0, 0, 1]])


def test_each_axis_lands_in_its_own_slot():
    """Regression: yaw used to be read out of the optical-axis rotation.

    The convention is R = Rz(roll) . Rx(pitch) . Ry(yaw) in a camera frame
    with y downward, so a pure rotation about each axis must appear in exactly
    one output slot and leave the other two at zero.
    """
    yaw, pitch, roll = rotation_matrix_to_euler(_Ry(30.0))
    assert (yaw, pitch, roll) == pytest.approx((30.0, 0.0, 0.0), abs=1e-6)

    yaw, pitch, roll = rotation_matrix_to_euler(_Rx(20.0))
    assert (yaw, pitch, roll) == pytest.approx((0.0, 20.0, 0.0), abs=1e-6)

    yaw, pitch, roll = rotation_matrix_to_euler(_Rz(15.0))
    assert (yaw, pitch, roll) == pytest.approx((0.0, 0.0, 15.0), abs=1e-6)


@pytest.mark.parametrize("y,p,r", [(0, 0, 0), (25, -10, 5), (-40, 15, -12),
                                   (60, 5, 0), (-5, -30, 20)])
def test_euler_round_trip(y, p, r):
    """Compose from known angles, decompose, and get them back."""
    R = _Rz(r) @ _Rx(p) @ _Ry(y)
    yaw, pitch, roll = rotation_matrix_to_euler(R)
    assert (yaw, pitch, roll) == pytest.approx((y, p, r), abs=1e-6)


def test_rotation_matrix_to_euler_gimbal_branch():
    """Pitch at +-90 degrees must not raise or return NaN."""
    for sign in (1.0, -1.0):
        yaw, pitch, roll = rotation_matrix_to_euler(_Rx(90.0 * sign))
        assert all(math.isfinite(v) for v in (yaw, pitch, roll))
        assert pitch == pytest.approx(90.0 * sign, abs=1e-6)
        assert yaw == 0.0


def test_pnp_model_is_expressed_in_the_camera_frame():
    """The 3D model must use the camera's axes: x right, y down, z from lens.

    These are not derived from the model; they are the geometry measured off a
    real sensor with a face square to the camera. Asserting them directly is
    the only kind of check that can catch a mirrored table, because every test
    that PROJECTS this model and then fits it cancels the error out.
    """
    row = {lm: PNP_MODEL_3D[i] for i, lm in enumerate(PNP_LANDMARKS)}

    # Subject's left eye images on the RIGHT, and vice versa.
    assert row[LEFT_EYE_OUTER][0] > 0, "263 lands on the image right -> x > 0"
    assert row[RIGHT_EYE_OUTER][0] < 0, "33 lands on the image left -> x < 0"
    # The mouth constants are image-relative, so 291 sits on the image right.
    assert row[MOUTH_RIGHT][0] > 0
    assert row[MOUTH_LEFT][0] < 0
    # y grows downward: the chin is below the nose.
    assert row[CHIN][1] > row[NOSE_TIP][1]
    # z grows away from the lens, and the nose is the nearest point on a face.
    assert row[NOSE_TIP][2] == min(p[2] for p in PNP_MODEL_3D)


def test_a_face_square_to_the_camera_reports_zero_yaw():
    """The regression that stopped calibration from ever completing.

    The image points are written out by hand in pixels rather than projected
    from PNP_MODEL_3D, so a mirrored model cannot cancel itself out here. A
    symmetric, centred face is by definition looking at the lens; it used to
    report yaw = 180, so all 360 frames of every calibration attempt fell
    outside the +-20 deg gate and the system could not calibrate anyone.
    """
    w, h = 1280, 720
    cx, cy = w / 2.0, h / 2.0
    pts = np.zeros((N_LM, 3), dtype=np.float64)
    pts[NOSE_TIP] = (cx, cy, 0.0)
    pts[CHIN] = (cx, cy + 96.0, 0.0)
    pts[LEFT_EYE_OUTER] = (cx + 66.0, cy - 50.0, 0.0)   # subject left, image right
    pts[RIGHT_EYE_OUTER] = (cx - 66.0, cy - 50.0, 0.0)
    pts[MOUTH_RIGHT] = (cx + 44.0, cy + 44.0, 0.0)      # 291, image right
    pts[MOUTH_LEFT] = (cx - 44.0, cy + 44.0, 0.0)

    pose = solve_head_pose(pts, (w, h))

    assert pose.valid
    assert abs(pose.yaw) < 20.0, (
        f"a symmetric centred face must read as facing the camera, got "
        f"yaw={pose.yaw:.1f}; anything near +-180 means the model is mirrored"
    )
    assert abs(pose.roll) < 20.0


def test_euler_tolerates_slightly_non_orthonormal_input():
    """Rodrigues output is numerically noisy; asin must not step outside [-1,1]."""
    R = _Rx(90.0)
    R[2, 1] = 1.0 + 1e-9
    yaw, pitch, roll = rotation_matrix_to_euler(R)
    assert all(math.isfinite(v) for v in (yaw, pitch, roll))
    assert pitch == pytest.approx(90.0, abs=1e-4)


# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #


def test_ewma_first_sample_is_exact():
    e = Ewma(0.3)
    assert e.update(5.0) == 5.0
    assert e.update(5.0) == pytest.approx(5.0)


def test_ewma_converges():
    e = Ewma(0.5)
    e.update(0.0)
    for _ in range(40):
        e.update(1.0)
    assert e.value == pytest.approx(1.0, abs=1e-6)


def test_time_window_evicts_old_samples():
    win = TimeWindow(5.0)
    for i in range(20):
        win.push(float(i), float(i))
    assert win.span_s == pytest.approx(5.0, abs=1e-9)
    assert win.values().min() >= 14.0


def test_time_fraction_below_uniform_sampling():
    win = TimeWindow(10.0)
    # 10 s of samples at 1 Hz; the first 3 s are "closed".
    for i in range(11):
        win.push(float(i), 0.5 if i < 3 else 1.0)
    # Intervals [0,1),[1,2),[2,3) are below -> 3 of 10 seconds.
    assert win.time_fraction_below(0.8) == pytest.approx(0.3, abs=1e-9)


def test_time_fraction_above_complements_below():
    win = TimeWindow(100.0)
    for i in range(11):
        win.push(float(i), 0.5 if i < 3 else 1.0)
    below = win.time_fraction_below(0.8)
    above = win.time_fraction_above(0.8)
    assert below + above == pytest.approx(1.0, abs=1e-9)
    assert above == pytest.approx(0.7, abs=1e-9)


def test_time_fraction_below_is_time_weighted_not_sample_weighted():
    """A dropped-frame gap must not distort PERCLOS.

    Two samples below threshold, but one of them holds for 8 s and the other
    for 1 s. Sample-counting would say 2/3; the correct answer is 9/10.
    """
    win = TimeWindow(100.0)
    win.push(0.0, 0.5)     # below, holds 8 s
    win.push(8.0, 0.5)     # below, holds 1 s
    win.push(9.0, 1.0)     # above, holds 1 s
    win.push(10.0, 1.0)
    assert win.time_fraction_below(0.8) == pytest.approx(0.9, abs=1e-9)


# --------------------------------------------------------------------------- #
# Blink tracker
# --------------------------------------------------------------------------- #


def blink_cfg(**kw):
    cfg = {
        "ear_closed_fraction": 0.65,
        "ear_reopen_fraction": 0.75,
        "blink": {
            "min_duration_s": 0.05,
            "max_normal_duration_s": 0.40,
            "microsleep_duration_s": 0.50,
            "rate_window_s": 60.0,
        },
    }
    cfg.update(kw)
    return cfg


def feed_closure(tracker, t0, duration, dt=0.02, ear_open=0.30,
                 closed_ear=0.10, open_ear=0.30):
    """Drive one closure of exactly ``duration`` and return events seen."""
    events = []
    t = t0
    # open before
    for _ in range(5):
        ev = tracker.update(t, open_ear, ear_open)
        if ev:
            events.append(ev)
        t += dt
    close_start = t
    while t < close_start + duration:
        ev = tracker.update(t, closed_ear, ear_open)
        if ev:
            events.append(ev)
        t += dt
    # reopen
    for _ in range(5):
        ev = tracker.update(t, open_ear, ear_open)
        if ev:
            events.append(ev)
        t += dt
    return events, t


def test_normal_blink_is_classified_as_blink():
    tr = BlinkTracker(blink_cfg())
    events, _ = feed_closure(tr, 0.0, 0.20)
    kinds = [e.kind for e in events]
    assert kinds == ["blink"]
    assert events[0].duration_s == pytest.approx(0.20, abs=0.03)


def test_long_closure_classified_separately():
    tr = BlinkTracker(blink_cfg())
    events, _ = feed_closure(tr, 0.0, 0.45)
    assert [e.kind for e in events] == ["long_closure"]


def test_microsleep_is_reported_while_eye_is_still_closed():
    """The safety-critical behaviour: do not wait for the eye to reopen."""
    tr = BlinkTracker(blink_cfg())
    t, dt, ear_open = 0.0, 0.02, 0.30
    for _ in range(5):
        tr.update(t, 0.30, ear_open)
        t += dt
    fired_at = None
    close_start = t
    while t < close_start + 3.0:            # eye stays shut for three seconds
        ev = tr.update(t, 0.08, ear_open)
        if ev and ev.kind == "microsleep" and fired_at is None:
            fired_at = t - close_start
        t += dt
    assert fired_at is not None, "microsleep never reported during the closure"
    assert fired_at == pytest.approx(0.50, abs=0.05)
    assert tr.is_closed


def test_microsleep_reported_exactly_once_per_closure():
    tr = BlinkTracker(blink_cfg())
    t, dt = 0.0, 0.02
    for _ in range(5):
        tr.update(t, 0.30, 0.30)
        t += dt
    n = 0
    for _ in range(200):                   # 4 s closed
        ev = tr.update(t, 0.08, 0.30)
        if ev and ev.kind == "microsleep":
            n += 1
        t += dt
    assert n == 1


def test_closure_counts_once_in_the_window_after_the_eye_reopens():
    """The reported regression: one closure must not count as two microsleeps.

    The test above stops while the eye is still shut, so it never sees the
    reopen. That is exactly where the second record was appended: the closure
    was logged once when it latched mid-shut, and again with kind=_classify()
    when the eye opened. Since the score saturates at MICROSLEEP_RANGE = 2
    events per 60 s, one real closure drove the microsleep component to its
    maximum and held the driver at DROWSY for a full minute with their eyes
    measurably wider than their own calibrated baseline.
    """
    tr = BlinkTracker(blink_cfg())
    t, dt, ear_open = 0.0, 0.02, 0.30

    def run(ear: float, seconds: float) -> None:
        nonlocal t
        for _ in range(int(seconds / dt)):
            tr.update(t, ear, ear_open)
            t += dt

    run(0.30, 1.0)
    run(0.08, 1.0)          # a single 1 s closure: one microsleep
    run(0.30, 1.0)          # and the eye reopens

    assert tr.microsleep_count() == 1, (
        f"one closure produced {tr.microsleep_count()} microsleeps in the "
        f"60 s window: {[(e.kind, round(e.duration_s, 2)) for e in tr._events]}"
    )
    # The surviving record must carry the FULL closure, not the latch instant.
    assert tr._events[0].duration_s == pytest.approx(1.0, abs=0.1)

    run(0.08, 1.0)
    run(0.30, 1.0)
    assert tr.microsleep_count() == 2, "a second closure must still be counted"


def test_an_ordinary_blink_never_registers_as_a_microsleep():
    """Guards the fix from the other side: blinks must still be blinks."""
    tr = BlinkTracker(blink_cfg())
    t, dt, ear_open = 0.0, 0.02, 0.30
    for ear, seconds in ((0.30, 0.4), (0.08, 0.16), (0.30, 0.4)):
        for _ in range(int(seconds / dt)):
            tr.update(t, ear, ear_open)
            t += dt
    assert tr.microsleep_count() == 0
    assert [e.kind for e in tr._events] == ["blink"]


def test_sub_threshold_flicker_is_not_a_blink():
    """Single-frame landmark noise must not register."""
    tr = BlinkTracker(blink_cfg())
    events, _ = feed_closure(tr, 0.0, 0.02)   # 20 ms, below min_duration 50 ms
    assert events == []


def test_hysteresis_prevents_double_counting_on_the_boundary():
    """EAR hovering between the close and reopen thresholds stays one closure."""
    tr = BlinkTracker(blink_cfg())
    ear_open = 0.30
    close_th = ear_open * 0.65      # 0.195
    reopen_th = ear_open * 0.75     # 0.225
    t, dt = 0.0, 0.02
    for _ in range(5):
        tr.update(t, ear_open, ear_open)
        t += dt
    events = []
    # dip below close threshold, then hover between the two thresholds
    for ear in [0.15] + [0.21, 0.20, 0.21, 0.20] * 6:
        ev = tr.update(t, ear, ear_open)
        if ev:
            events.append(ev)
        t += dt
    assert tr.is_closed, "hovering inside the hysteresis band reopened the eye"
    for _ in range(5):
        ev = tr.update(t, ear_open, ear_open)
        if ev:
            events.append(ev)
        t += dt
    assert len(events) == 1


def test_calibrated_threshold_handles_narrow_eyes():
    """A driver whose open EAR is 0.18 must not read as permanently closed.

    This is the concrete failure of the literature's fixed 0.21 threshold and
    the reason the config expresses closure as a fraction of baseline.
    """
    tr = BlinkTracker(blink_cfg())
    narrow_open = 0.18
    t, dt = 0.0, 0.02
    events = []
    for _ in range(300):                    # 6 s of wide-open narrow eyes
        ev = tr.update(t, narrow_open, narrow_open)
        if ev:
            events.append(ev)
        t += dt
    assert not tr.is_closed
    assert events == []
    # and a real blink on the same driver is still caught
    ev_list, _ = feed_closure(tr, t, 0.2, ear_open=narrow_open,
                              closed_ear=narrow_open * 0.4, open_ear=narrow_open)
    assert [e.kind for e in ev_list] == ["blink"]


def test_blink_rate_window():
    tr = BlinkTracker(blink_cfg())
    t = 0.0
    for _ in range(10):
        _, t = feed_closure(tr, t, 0.15)
        t += 1.0
    assert tr.blink_rate_per_min() == pytest.approx(10.0, abs=0.01)
    assert tr.mean_blink_duration_s() == pytest.approx(0.15, abs=0.03)


# --------------------------------------------------------------------------- #
# Yawn tracker
# --------------------------------------------------------------------------- #


def test_yawn_requires_sustained_opening():
    tr = YawnTracker({"yawn": {"mar_threshold": 0.6, "min_duration_s": 1.0,
                               "window_s": 300.0}})
    t, dt = 0.0, 0.05
    # brief wide mouth: speech, not a yawn
    for _ in range(10):      # 0.5 s
        tr.update(t, 0.75)
        t += dt
    tr.update(t, 0.05)
    assert tr.count() == 0

    # sustained
    t += dt
    confirmed = False
    for _ in range(40):      # 2 s
        confirmed |= tr.update(t, 0.75)
        t += dt
    assert confirmed and tr.count() == 1


def test_yawn_counted_once_per_opening():
    tr = YawnTracker({"yawn": {"mar_threshold": 0.6, "min_duration_s": 1.0,
                               "window_s": 300.0}})
    t, dt = 0.0, 0.05
    for _ in range(100):     # 5 s continuously open
        tr.update(t, 0.8)
        t += dt
    assert tr.count() == 1


# --------------------------------------------------------------------------- #
# Head tracker
# --------------------------------------------------------------------------- #


def head_cfg():
    return {"head": {"yaw_limit_deg": 25.0, "pitch_limit_deg": 20.0,
                     "off_road_alert_s": 2.0, "nod_window_s": 10.0,
                     "nod_pitch_std_deg": 6.0}}


def test_off_road_glance_timer_and_threshold():
    tr = HeadTracker(head_cfg())
    t, dt = 0.0, 0.05
    for _ in range(20):                     # 1 s looking away: allowed
        tr.update(t, 40.0, 0.0, True)
        t += dt
    assert tr.current_glance_s == pytest.approx(0.95, abs=0.06)
    assert not tr.off_road_alarm

    for _ in range(40):                     # now past 2 s
        tr.update(t, 40.0, 0.0, True)
        t += dt
    assert tr.off_road_alarm
    assert tr.long_glance_count() == 1

    tr.update(t, 0.0, 0.0, True)            # back to the road
    assert tr.current_glance_s == 0.0
    assert not tr.off_road_alarm


def test_repeated_short_glances_do_not_alarm():
    tr = HeadTracker(head_cfg())
    t, dt = 0.0, 0.05
    for _ in range(10):
        for _ in range(20):                 # 1 s away
            tr.update(t, 40.0, 0.0, True)
            t += dt
        for _ in range(20):                 # 1 s back
            tr.update(t, 0.0, 0.0, True)
            t += dt
    assert tr.long_glance_count() == 0


def test_nodding_needs_a_filled_window():
    tr = HeadTracker(head_cfg())
    t, dt = 0.0, 0.05
    for i in range(40):                     # only 2 s of history
        tr.update(t, 0.0, 15.0 * (1 if i % 2 else -1), True)
        t += dt
    assert not tr.nodding(), "declared nodding before the window filled"
    for i in range(200):                    # 10 s of oscillation
        tr.update(t, 0.0, 15.0 * (1 if i % 2 else -1), True)
        t += dt
    assert tr.nodding()
    assert tr.pitch_std() > 6.0


def test_invalid_pose_is_ignored():
    tr = HeadTracker(head_cfg())
    assert tr.update(0.0, 90.0, 90.0, False) is False
    assert tr.current_glance_s == 0.0


# --------------------------------------------------------------------------- #
# Calibrator
# --------------------------------------------------------------------------- #


def test_calibrator_rejects_blinks_from_the_open_baseline():
    """Blinks during calibration must not drag the open-eye EAR down."""
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 4.0, "min_open_samples": 50,
                      "max_yaw_deg": 12.0, "max_pitch_deg": 12.0})
    cal.start(0.0)
    t, dt = 0.0, 0.02
    pose = HeadPose(yaw=1.0, pitch=-1.0, roll=0.0, valid=True)
    n = int(4.0 / dt) + 1
    for i in range(n):
        # 15% of frames are blinks at EAR 0.08, the rest open at 0.30
        ear = 0.08 if (i % 20) < 3 else 0.30
        cal.feed(t, ear, 0.05, pose, (0.0, 0.0, True), 120.0)
        t += dt
    result = cal.finish(t)
    assert result is not None and result.complete
    assert result.ear_open == pytest.approx(0.30, abs=0.01), \
        "blink frames contaminated the open-eye baseline"
    assert result.yaw_zero == pytest.approx(1.0, abs=1e-6)


def test_calibrator_respects_the_configured_pose_gate():
    """Regression: max_yaw_deg/max_pitch_deg were read and then ignored.

    feed() hardcoded a 45-degree limit, so the documented 12-degree gate in
    the config had no effect and calibration happily accepted frames taken
    with the head well off-axis, biasing the pose zero it exists to establish.
    """
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 4.0, "min_open_samples": 10,
                      "max_yaw_deg": 15.0, "max_pitch_deg": 15.0})
    cal.start(0.0)
    t, dt = 0.0, 0.02
    # Alternate acceptable and unacceptable poses.
    for i in range(200):
        yaw = 5.0 if i % 2 == 0 else 30.0
        cal.feed(t, 0.30, 0.05, HeadPose(yaw=yaw, pitch=0.0, roll=0.0, valid=True),
                 (0.0, 0.0, True), 120.0)
        t += dt
    result = cal.finish(t)
    assert result is not None
    # Only the 5-degree frames should have been kept.
    assert result.n_samples == 100
    assert result.yaw_zero == pytest.approx(5.0, abs=1e-6)


def test_calibrator_accepts_a_pose_inside_the_gate():
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 2.0, "min_open_samples": 10,
                      "max_yaw_deg": 20.0, "max_pitch_deg": 20.0})
    cal.start(0.0)
    t = 0.0
    for _ in range(120):
        cal.feed(t, 0.30, 0.05,
                 HeadPose(yaw=-14.0, pitch=11.0, roll=3.0, valid=True),
                 (0.0, 0.0, True), 120.0)
        t += 0.02
    result = cal.finish(t)
    assert result is not None and result.n_samples == 120
    assert result.yaw_zero == pytest.approx(-14.0, abs=1e-6)
    assert result.pitch_zero == pytest.approx(11.0, abs=1e-6)


def test_calibrator_explains_a_pose_rejection_failure():
    """A restart must say why; a silent one looks like a hung progress bar."""
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 1.0, "min_open_samples": 100,
                      "max_yaw_deg": 15.0, "max_pitch_deg": 15.0})
    cal.start(0.0)
    t = 0.0
    for _ in range(60):
        cal.feed(t, 0.30, 0.05, HeadPose(yaw=60.0, pitch=0.0, roll=0.0, valid=True),
                 (0.0, 0.0, True), 120.0)
        t += 0.02
    assert cal.finish(1.5) is None
    assert cal.attempts == 1
    assert cal.last_failure and "head pose" in cal.last_failure


def test_calibrator_explains_a_no_face_failure():
    cal = Calibrator({"duration_s": 1.0, "min_open_samples": 100})
    cal.start(0.0)
    assert cal.finish(1.5) is None
    assert cal.last_failure and "no face" in cal.last_failure


def test_calibrator_explains_intermittent_tracking():
    """Plenty of frames, plenty well-posed, but tracking drops out too often.

    This is the fraction branch: the absolute floor is satisfied, so the
    complaint has to be about the proportion, and it must quote both numbers.
    """
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 10.0, "min_tracking_fraction": 0.40,
                      "min_open_samples": 30, "max_yaw_deg": 20.0,
                      "max_pitch_deg": 20.0})
    cal.start(0.0)
    t, dt = 0.0, 1.0 / 30.0
    for i in range(300):
        # 1 frame in 5 tracked: 60 usable, above the 30 floor, but only 20%.
        if i % 5 == 0:
            cal.feed(t, 0.30, 0.05, HeadPose(0.0, 0.0, 0.0, True), (0, 0, True), 120)
        else:
            cal.feed(t, 0.30, 0.05, HeadPose(80.0, 0.0, 0.0, True), (0, 0, True), 120)
        t += dt
    assert cal.finish(t + 1.0) is None
    assert cal.last_failure is not None
    # 80% were rejected for pose, so that is the cause it should name.
    assert "head pose" in cal.last_failure


def test_calibrator_counters_reset_between_attempts():
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 1.0, "min_open_samples": 100,
                      "max_yaw_deg": 15.0, "max_pitch_deg": 15.0})
    cal.start(0.0)
    for i in range(60):
        cal.feed(i * 0.02, 0.30, 0.05, HeadPose(60.0, 0.0, 0.0, True),
                 (0, 0, True), 120)
    cal.finish(1.5)                       # restarts internally
    assert cal._seen == 0 and cal._rejected_pose == 0
    # Second attempt, this time well posed, must succeed.
    t = 1.5
    for _ in range(120):
        cal.feed(t, 0.30, 0.05, HeadPose(2.0, 1.0, 0.0, True), (0, 0, True), 120)
        t += 0.02
    result = cal.finish(t)
    assert result is not None and result.complete


def test_calibration_completes_at_a_low_frame_rate():
    """Regression: the sample floor made calibration impossible under 10 fps.

    min_open_samples was 120 over a 12 s window, so a stream slower than 10
    usable frames per second could never reach the count. The window expired
    short, restarted, and looped forever. The only visible symptom was a
    progress bar returning to zero, which is exactly what it looked like on a
    laptop running MediaPipe on CPU with a preview window open.
    """
    from bamnun.features import HeadPose
    from bamnun.session import load_config

    cfg = load_config()["calibration"]
    for fps in (4.0, 6.0, 8.0, 10.0, 15.0, 30.0):
        cal = Calibrator(cfg)
        cal.start(0.0)
        dt = 1.0 / fps
        t = 0.0
        n = int(cal.duration_s * fps)
        for i in range(n + 1):
            ear = 0.08 if (i % 20) < 2 else 0.29     # perfect tracking, real blinks
            cal.feed(t, ear, 0.05, HeadPose(1.0, -1.0, 0.0, True),
                     (0.0, 0.0, True), 118.0)
            t += dt
        result = cal.finish(t)
        assert result is not None and result.complete, (
            f"calibration failed at {fps} fps with 100% tracking "
            f"(reason: {cal.last_failure})")
        assert result.ear_open == pytest.approx(0.29, abs=0.01)


def test_calibration_still_rejects_genuinely_bad_tracking():
    """The fraction test must not have made the check toothless."""
    from bamnun.features import HeadPose
    from bamnun.session import load_config

    cal = Calibrator(load_config()["calibration"])
    cal.start(0.0)
    t, dt = 0.0, 1.0 / 30.0
    for i in range(360):
        if i % 4 == 0:                      # only 25% of frames usable
            cal.feed(t, 0.29, 0.05, HeadPose(1.0, 0.0, 0.0, True), (0, 0, True), 118)
        else:
            cal.feed(t, 0.29, 0.05, HeadPose(70.0, 0.0, 0.0, True), (0, 0, True), 118)
        t += dt
    assert cal.finish(t) is None
    assert cal.last_failure is not None


def test_calibration_stats_report_the_three_failure_causes():
    from bamnun.features import HeadPose
    from bamnun.session import load_config

    cal = Calibrator(load_config()["calibration"])
    cal.start(0.0)
    t, dt = 0.0, 1.0 / 20.0
    for i in range(120):
        yaw = 2.0 if i % 2 == 0 else 60.0
        cal.feed(t, 0.29, 0.05, HeadPose(yaw, 3.0, 0.0, True), (0, 0, True), 118)
        t += dt
    s = cal.stats(t)
    assert s["seen"] == 120
    assert s["usable"] == 60
    assert s["rejected_pose"] == 60
    assert s["fraction"] == pytest.approx(0.5)
    assert s["fps"] == pytest.approx(20.0, rel=0.05)
    # Raw angles are retained even for rejected frames, so the message can
    # tell the driver what the pose actually was.
    assert s["raw_yaw"] == pytest.approx(31.0, abs=0.001)
    assert s["raw_pitch"] == pytest.approx(3.0, abs=0.001)


def test_calibration_low_fps_failure_message_names_the_frame_rate():
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 12.0, "min_tracking_fraction": 0.4,
                      "min_open_samples": 30, "max_yaw_deg": 20.0,
                      "max_pitch_deg": 20.0})
    cal.start(0.0)
    t, dt = 0.0, 1.0 / 2.0          # 2 fps: 24 frames, under the 30 floor
    for _ in range(24):
        cal.feed(t, 0.29, 0.05, HeadPose(1.0, 0.0, 0.0, True), (0, 0, True), 118)
        t += dt
    assert cal.finish(t) is None
    assert "fps" in cal.last_failure and "too slow" in cal.last_failure


def test_calibration_duration_is_twelve_seconds_by_default():
    """The number quoted to the driver must come from the config, not prose."""
    from bamnun.session import load_config

    cfg = load_config()
    assert cfg["calibration"]["duration_s"] == 12.0
    cal = Calibrator(cfg["calibration"])
    assert cal.duration_s == 12.0
    cal.start(100.0)
    assert cal.progress(100.0) == 0.0
    assert cal.progress(106.0) == pytest.approx(0.5)
    assert cal.progress(112.0) == 1.0
    assert cal.progress(999.0) == 1.0          # clamped


def test_calibrator_restarts_when_too_few_samples():
    from bamnun.features import HeadPose

    cal = Calibrator({"duration_s": 1.0, "min_open_samples": 500,
                      "max_yaw_deg": 12.0, "max_pitch_deg": 12.0})
    cal.start(0.0)
    for i in range(10):
        cal.feed(i * 0.1, 0.3, 0.05, HeadPose(0, 0, 0, True), (0, 0, True), 120)
    assert cal.finish(1.5) is None
    assert cal.active, "calibrator should restart rather than commit bad data"


def test_calibration_roundtrip():
    c = Calibration(ear_open=0.271, yaw_zero=3.2, complete=True, n_samples=500)
    assert Calibration.from_dict(c.to_dict()) == c


# --------------------------------------------------------------------------- #
# Permitted glance regions
# --------------------------------------------------------------------------- #

HEAD_CFG = {
    "head": {
        "yaw_limit_deg": 25.0, "pitch_limit_deg": 20.0, "off_road_alert_s": 2.0,
        "permitted_regions": [
            {"name": "right_mirror", "yaw": [22.0, 62.0],
             "pitch": [-18.0, 22.0], "dwell_s": 3.0},
        ],
    }
}


def _glance(tr, yaw, seconds, t0=0.0, dt=0.05):
    t = t0
    while t < t0 + seconds:
        tr.update(t, yaw, 0.0, True)
        t += dt
    return t


def test_a_region_may_lengthen_the_dwell_but_never_shorten_it():
    """A mistyped region must not quietly weaken the NHTSA criterion."""
    cfg = {"head": dict(HEAD_CFG["head"], permitted_regions=[
        {"name": "sloppy", "yaw": [22.0, 62.0], "pitch": [-18.0, 22.0],
         "dwell_s": 0.2},                      # shorter than off_road_alert_s
    ])}
    tr = HeadTracker(cfg)
    assert tr.regions[0].dwell_s == 2.0


def test_a_mirror_glance_survives_past_the_bare_dwell():
    tr = HeadTracker(HEAD_CFG)
    _glance(tr, 40.0, 2.5)
    assert tr.glance_region == "right_mirror"
    assert tr.glance_dwell_s == 3.0
    assert not tr.off_road_alarm
    _glance(tr, 40.0, 1.0, t0=2.5)
    assert tr.off_road_alarm, "a mirror glance must still alarm past 3 s"


def test_sweeping_from_a_mirror_to_a_phone_angle_keeps_the_shorter_dwell():
    """The permissive direction must not be enterable part-way through.

    Starting inside a mirror region and then turning further away should not
    carry the mirror's allowance along with it.
    """
    tr = HeadTracker(HEAD_CFG)
    t = _glance(tr, 40.0, 1.0)              # begins as a mirror check
    assert tr.glance_dwell_s == 3.0
    _glance(tr, 75.0, 0.2, t0=t)            # ...then keeps going, past the region
    assert tr.glance_dwell_s == 2.0
    assert tr.glance_region == ""


def test_leaving_the_off_road_cone_resets_the_allowance():
    tr = HeadTracker(HEAD_CFG)
    _glance(tr, 40.0, 1.0)
    tr.update(2.0, 0.0, 0.0, True)          # back to forward
    assert tr.glance_dwell_s == 2.0
    assert tr.glance_region == ""
    assert tr.current_glance_s == 0.0
