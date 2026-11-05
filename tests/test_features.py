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
    Ewma, HeadTracker, TimeWindow, both_eye_ear, eye_aspect_ratio, interocular_px,
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
