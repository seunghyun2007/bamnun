"""End-to-end test of the pipeline below the landmark model.

Landmark inference itself needs the downloaded .task bundle and a real face,
so it is exercised on the Pi rather than here. Everything downstream of it,
which is where all the decision logic lives, is driven from synthetic
LandmarkResult objects through the real FeatureExtractor, StateEstimator,
RestPlanner and EscalationPolicy.

This is the test that would have caught the microsleep-override and
de-escalation defects before they reached hardware, so it earns its place.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import EscalationPolicy          # noqa: E402
from bamnun.capture import ArraySource, Frame       # noqa: E402
from bamnun.features import (                     # noqa: E402
    FeatureExtractor, FeatureFrame, both_eye_ear, gaze_offset, solve_head_pose,
)
from bamnun.landmarks import (                      # noqa: E402
    LEFT_EYE_EAR, LEFT_EYE_INNER, LEFT_EYE_OUTER, LEFT_EYE_RING,
    LEFT_IRIS_CENTER, LandmarkResult, MOUTH_BOTTOM, MOUTH_LEFT, MOUTH_RIGHT,
    MOUTH_TOP, NOSE_TIP, CHIN, RIGHT_EYE_EAR, RIGHT_EYE_INNER,
    RIGHT_EYE_OUTER, RIGHT_EYE_RING, RIGHT_IRIS_CENTER,
)
from bamnun.predictor import RestPlanner            # noqa: E402
from bamnun.session import load_config              # noqa: E402
from bamnun.state import StateEstimator             # noqa: E402

IMG_W, IMG_H = 640, 480
N_LM = 478


FOCAL = float(IMG_W)          # the same pinhole guess solve_head_pose makes
DEPTH_MM = 520.0              # driver's face about half a metre from the lens


def _rot(yaw_deg: float, pitch_deg: float, roll_deg: float = 0.0) -> np.ndarray:
    y, p, r = np.radians([yaw_deg, pitch_deg, roll_deg])
    Ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    Rz = np.array([[np.cos(r), -np.sin(r), 0], [np.sin(r), np.cos(r), 0], [0, 0, 1]])
    return Rz @ Rx @ Ry


def _project(model_pts: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Rotate a 3D model and project it through the assumed pinhole camera.

    Building the synthetic face this way rather than by sliding a flat face
    sideways matters: a lateral translation is not a rotation, and solvePnP is
    right to report zero yaw for it. Projecting a genuinely rotated head gives
    the pose test an actual ground truth to check against.
    """
    cam = model_pts @ R.T
    cam = cam.copy()
    cam[:, 2] += DEPTH_MM
    u = FOCAL * cam[:, 0] / cam[:, 2] + IMG_W / 2.0
    v = FOCAL * cam[:, 1] / cam[:, 2] + IMG_H / 2.0
    return np.stack([u, v], axis=1)


# Reuse the production model table rather than a copy, so a change to the
# object frame cannot silently desynchronise the test from the code.
from bamnun.landmarks import PNP_MODEL_3D as _MODEL  # noqa: E402


def synth_face(ear: float = 0.30, mar: float = 0.05, iris_dx: float = 0.0,
               yaw_deg: float = 0.0, pitch_deg: float = 0.0) -> np.ndarray:
    """A projected, rotatable synthetic face.

    ``ear`` is reproduced exactly by construction regardless of the projection,
    because the six EAR points are laid out around each projected eye with the
    vertical gap set to ``ear`` times the horizontal one.
    """
    pts = np.zeros((N_LM, 3), dtype=np.float32)
    proj = _project(_MODEL, _rot(yaw_deg, pitch_deg))
    nose, chin, l_eye, r_eye, m_right, m_left = proj

    pts[NOSE_TIP] = (*nose, 0.0)
    pts[CHIN] = (*chin, 0.0)

    interocular = float(np.linalg.norm(l_eye - r_eye))
    eye_w = max(interocular * 0.34, 4.0)          # eye aperture ~1/3 of IOD
    h = ear * eye_w

    # MediaPipe's two EAR index sets do NOT share a corner order. The right
    # set starts at the OUTER corner (33) and ends at the inner one (133); the
    # left set starts at the INNER corner (362) and ends at the outer one
    # (263). Assuming index 0 is always the outer corner puts the left eye's
    # outer corner an eye-width toward the nose, which is a landmark that
    # solvePnP uses, so the recovered head pose came out tens of degrees wrong
    # with a sign flip near zero. Spell the roles out per eye.
    for outer_proj, toward, outer_idx, inner_idx, upper, lower in (
        (r_eye, l_eye, RIGHT_EYE_EAR[0], RIGHT_EYE_EAR[3],
         (RIGHT_EYE_EAR[1], RIGHT_EYE_EAR[2]), (RIGHT_EYE_EAR[5], RIGHT_EYE_EAR[4])),
        (l_eye, r_eye, LEFT_EYE_EAR[3], LEFT_EYE_EAR[0],
         (LEFT_EYE_EAR[1], LEFT_EYE_EAR[2]), (LEFT_EYE_EAR[5], LEFT_EYE_EAR[4])),
    ):
        direction = toward - outer_proj
        direction = direction / (np.linalg.norm(direction) + 1e-9)
        inner = outer_proj + direction * eye_w
        centre = (outer_proj + inner) / 2.0
        pts[outer_idx] = (*outer_proj, 0.0)
        pts[inner_idx] = (*inner, 0.0)
        q1 = centre - direction * eye_w * 0.25
        q2 = centre + direction * eye_w * 0.25
        # upper[k] pairs with lower[k] in the EAR formula, so the two members
        # of each pair must share an x position.
        pts[upper[0]] = (q1[0], q1[1] - h / 2, 0.0)
        pts[lower[0]] = (q1[0], q1[1] + h / 2, 0.0)
        pts[upper[1]] = (q2[0], q2[1] - h / 2, 0.0)
        pts[lower[1]] = (q2[0], q2[1] + h / 2, 0.0)

    for iris_idx, ear_idx in ((RIGHT_IRIS_CENTER, RIGHT_EYE_EAR),
                              (LEFT_IRIS_CENTER, LEFT_EYE_EAR)):
        outer = pts[ear_idx[0]][:2]
        inner = pts[ear_idx[3]][:2]
        centre = (outer + inner) / 2.0
        half_w = float(np.linalg.norm(inner - outer)) / 2.0
        # Displace along IMAGE x, not along the outer-to-inner direction: that
        # direction is mirrored between the two eyes, so an earlier version of
        # this helper moved the two irises toward each other and the averaged
        # gaze offset cancelled to exactly zero for every input.
        pts[iris_idx] = (centre[0] + iris_dx * half_w, centre[1], 0.0)

    # Fill the full eyelid rings too. They are not used by any metric, only by
    # the overlay, but leaving them at the origin made the rendered preview
    # draw lines from each eye to the top-left corner of the frame.
    for ring, ear_idx in ((RIGHT_EYE_RING, RIGHT_EYE_EAR),
                          (LEFT_EYE_RING, LEFT_EYE_EAR)):
        # FOUR of the six EAR points are also ring members (for the right eye:
        # 33, 144, 153, 158, 160), so the ellipse below overwrites them and
        # changes the EAR the fixture was built to produce. Save all six and
        # put them back.
        saved = {idx: pts[idx].copy() for idx in ear_idx}
        c0 = pts[ear_idx[0]][:2]
        c1 = pts[ear_idx[3]][:2]
        centre = (c0 + c1) / 2.0
        rx = float(np.linalg.norm(c1 - c0)) / 2.0
        ry = max(h / 2.0, 1.0)
        n = len(ring)
        for k, idx in enumerate(ring):
            theta = 2.0 * np.pi * k / n
            pts[idx] = (centre[0] + rx * np.cos(theta),
                        centre[1] + ry * np.sin(theta), 0.0)
        for idx, val in saved.items():
            pts[idx] = val

    mouth_w = float(np.linalg.norm(m_left - m_right))
    pts[MOUTH_LEFT] = (*m_left, 0.0)
    pts[MOUTH_RIGHT] = (*m_right, 0.0)
    mouth_c = (m_left + m_right) / 2.0
    pts[MOUTH_TOP] = (mouth_c[0], mouth_c[1] - mar * mouth_w / 2, 0.0)
    pts[MOUTH_BOTTOM] = (mouth_c[0], mouth_c[1] + mar * mouth_w / 2, 0.0)
    return pts


def lm(pts: np.ndarray, t: float) -> LandmarkResult:
    norm = pts.copy()
    norm[:, 0] /= IMG_W
    norm[:, 1] /= IMG_H
    return LandmarkResult(points=pts, normalized=norm,
                          image_size=(IMG_W, IMG_H), timestamp=t)


# --------------------------------------------------------------------------- #
# Geometry that needs cv2
# --------------------------------------------------------------------------- #


def test_head_pose_frontal_face_is_the_identity():
    """A driver looking straight ahead must read as zero on all three axes.

    Regression for a y-up object frame against OpenCV's y-down camera frame,
    which produced yaw 176 / roll -167 for a frontal face.
    """
    pose = solve_head_pose(synth_face(), (IMG_W, IMG_H))
    assert pose.valid
    assert pose.yaw == pytest.approx(0.0, abs=0.5)
    assert pose.pitch == pytest.approx(0.0, abs=0.5)
    assert pose.roll == pytest.approx(0.0, abs=0.5)


@pytest.mark.parametrize("yaw", [-45, -30, -15, -5, 0, 5, 15, 30, 45])
def test_head_pose_recovers_yaw_ground_truth(yaw):
    pose = solve_head_pose(synth_face(yaw_deg=yaw), (IMG_W, IMG_H))
    assert pose.valid
    assert pose.yaw == pytest.approx(yaw, abs=1.0)
    # No cross-talk into the other axes: the original bug showed the input
    # yaw almost entirely in the pitch channel.
    assert pose.pitch == pytest.approx(0.0, abs=1.0)
    assert pose.roll == pytest.approx(0.0, abs=1.0)


@pytest.mark.parametrize("pitch", [-25, -10, 0, 10, 25])
def test_head_pose_recovers_pitch_ground_truth(pitch):
    pose = solve_head_pose(synth_face(pitch_deg=pitch), (IMG_W, IMG_H))
    assert pose.valid
    assert pose.pitch == pytest.approx(pitch, abs=1.0)
    assert pose.yaw == pytest.approx(0.0, abs=1.0)


def test_head_pose_is_monotonic_in_yaw():
    """Monotonicity is what the off-road glance threshold actually relies on."""
    yaws = [solve_head_pose(synth_face(yaw_deg=y), (IMG_W, IMG_H)).yaw
            for y in range(-40, 41, 10)]
    assert all(b > a for a, b in zip(yaws, yaws[1:])), yaws


def test_ear_is_unaffected_by_head_rotation():
    """Eye closure must not be confused by a turned head."""
    for yaw in (-30, 0, 30):
        for pitch in (-15, 0, 15):
            pts = synth_face(ear=0.27, yaw_deg=yaw, pitch_deg=pitch)
            r, l = both_eye_ear(pts)
            assert r == pytest.approx(0.27, abs=1e-3)
            assert l == pytest.approx(0.27, abs=1e-3)


def test_gaze_offset_sign_and_centre():
    h, v, ok = gaze_offset(synth_face(iris_dx=0.0))
    assert ok and abs(h) < 1e-6
    right, _, _ = gaze_offset(synth_face(iris_dx=0.6))
    left, _, _ = gaze_offset(synth_face(iris_dx=-0.6))
    assert right > 0.3 and left < -0.3


def test_gaze_offset_handles_a_closed_eye_without_exploding():
    """A nearly shut eye must not yield an enormous normalised offset."""
    _, v, ok = gaze_offset(synth_face(ear=0.02, iris_dx=0.0))
    assert ok and abs(v) < 2.0


# --------------------------------------------------------------------------- #
# Capture abstraction
# --------------------------------------------------------------------------- #


def test_array_source_iterates_and_stops():
    imgs = [np.zeros((4, 4, 3), np.uint8) for _ in range(5)]
    with ArraySource(imgs, dt=0.1) as src:
        frames = list(src)
    assert [f.index for f in frames] == [0, 1, 2, 3, 4]
    assert frames[-1].timestamp == pytest.approx(0.4, abs=1e-9)
    assert src.resolution == (4, 4)


def test_frame_gray_to_rgb_conversion():
    gray = Frame(image=np.full((8, 8), 120, np.uint8), timestamp=0.0, index=0)
    assert gray.is_gray
    rgb = gray.as_rgb()
    assert rgb.shape == (8, 8, 3)
    assert rgb[0, 0].tolist() == [120, 120, 120]


# --------------------------------------------------------------------------- #
# Full pipeline
# --------------------------------------------------------------------------- #


def run_sequence(extractor, estimator, policy, planner, frames, t0=0.0, dt=0.05):
    """Feed (ear, mar, iris_dx, yaw_deg) tuples and collect the outputs."""
    out = []
    t = t0
    for (ear, mar, iris_dx, yaw_deg) in frames:
        pts = synth_face(ear=ear, mar=mar, iris_dx=iris_dx, yaw_deg=yaw_deg)
        ff = extractor.update(t, lm(pts, t))
        if extractor.calibrating:
            out.append((t, ff, None, None))
            t += dt
            continue
        st = estimator.update(ff, calibrated=extractor.calibration.complete)
        planner.push(t, st.score)
        dec = policy.update(st)
        out.append((t, ff, st, dec))
        t += dt
    return out


def build_stack():
    cfg = load_config()
    cfg["alerts"]["actuators"]["chime"]["type"] = "null"
    cfg["alerts"]["actuators"]["voice"]["type"] = "null"
    extractor = FeatureExtractor(cfg["features"], cfg["calibration"])
    estimator = StateEstimator(cfg["state"])
    policy = EscalationPolicy(cfg["alerts"])
    planner = RestPlanner(cfg["predictor"])
    return cfg, extractor, estimator, policy, planner


def test_calibration_then_alert_driver_produces_no_alerts():
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    # 13 s of open eyes at 20 Hz covers the 12 s calibration window.
    frames = [(0.30, 0.05, 0.0, 0.0)] * 260
    run_sequence(ex, est, pol, pl, frames)
    assert ex.calibration.complete
    assert ex.calibration.ear_open == pytest.approx(0.30, abs=0.01)

    out = run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 200, t0=13.0)
    assert all(st.level == 0 for (_, _, st, _) in out)
    assert not any(d.fired for (_, _, _, d) in out)
    assert pol.stage == 0


def test_pipeline_detects_a_sustained_closure_and_alerts():
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)
    assert ex.calibration.complete

    # 3 s of eyes shut.
    out = run_sequence(ex, est, pol, pl, [(0.05, 0.05, 0.0, 0.0)] * 60, t0=13.0)
    assert any(ff.eye_closed for (_, ff, _, _) in out)
    assert any(st.microsleep_now for (_, _, st, _) in out)
    fired = [d for (_, _, _, d) in out if d.fired]
    assert fired, "sustained closure produced no alert"
    assert pol.stage == len(cfg["alerts"]["stages"]) - 1


def test_pipeline_flags_a_long_off_road_glance():
    """A glance long enough to clear its dwell is flagged.

    +40 deg falls inside the ``right_mirror`` permitted region, so it must now
    outlast that region's 3 s dwell rather than the bare 2 s one. Four seconds
    of staring at the passenger mirror is distraction by anyone's definition.
    """
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)

    # Head turned hard for 4 s, eyes wide open the whole time.
    out = run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 40.0)] * 80, t0=13.0)
    assert any(st.distracted for (_, _, st, _) in out), "long glance not flagged"
    # Drowsiness must stay clean: the channels are independent.
    assert max(st.score for (_, _, st, _) in out) < 0.15


def test_a_mirror_glance_is_not_flagged_at_the_bare_two_second_dwell():
    """The false positive the regions exist to remove.

    2.5 s toward the passenger mirror used to trip the 2 s NHTSA dwell and
    accuse an attentive driver of distraction for checking the mirror before a
    lane change. Inside a permitted region it must ride out to 3 s.
    """
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)

    out = run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 40.0)] * 50, t0=13.0)
    assert not any(st.distracted for (_, _, st, _) in out), (
        "a 2.5 s mirror check was flagged as distraction"
    )
    regions = {ff.glance_region for (_, ff, _, _) in out if ff.off_road}
    assert regions == {"right_mirror"}


def test_a_glance_outside_every_region_still_flags_at_two_seconds():
    """The regions must not have weakened the base rule.

    -60 deg is past the left-mirror window, so no allowance applies and the
    bare NHTSA dwell governs.
    """
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)

    out = run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, -60.0)] * 50, t0=13.0)
    assert any(st.distracted for (_, _, st, _) in out), (
        "a 2.5 s glance outside every permitted region was not flagged"
    )
    assert all(ff.glance_region == "" for (_, ff, _, _) in out if ff.off_road)


def test_pipeline_recovers_when_the_driver_looks_back():
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 40.0)] * 60, t0=13.0)
    out = run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 60, t0=16.0)
    assert not out[-1][2].distracted
    assert out[-1][1].off_road_glance_s == 0.0


def test_narrow_eyed_driver_is_calibrated_not_alarmed():
    """The headline robustness claim, end to end.

    A driver whose fully-open EAR is 0.17 would read as permanently asleep
    against the literature's fixed 0.21 threshold. After calibration the
    pipeline must report them as alert, and must still catch a real blink.
    """
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.17, 0.05, 0.0, 0.0)] * 260)
    assert ex.calibration.ear_open == pytest.approx(0.17, abs=0.01)

    out = run_sequence(ex, est, pol, pl, [(0.17, 0.05, 0.0, 0.0)] * 400, t0=13.0)
    assert not any(ff.eye_closed for (_, ff, _, _) in out)
    assert max(ff.perclos for (_, ff, _, _) in out) < 0.05
    assert not any(d.fired for (_, _, _, d) in out)

    # A genuine closure on the same driver is still detected.
    closed = run_sequence(ex, est, pol, pl, [(0.06, 0.05, 0.0, 0.0)] * 40, t0=33.0)
    assert any(ff.eye_closed for (_, ff, _, _) in closed)


def test_yawn_propagates_into_the_fused_score():
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)

    out = run_sequence(ex, est, pol, pl, [(0.30, 0.75, 0.0, 0.0)] * 60, t0=13.0)
    assert out[-1][1].yawn_count == 1
    assert out[-1][2].components["yawn"] > 0.0


def test_face_loss_mid_stream_is_handled():
    cfg, ex, est, pol, pl = build_stack()
    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)

    t = 13.0
    states = []
    for i in range(80):                # 4 s with no landmarks at all
        ff = ex.update(t, None)
        st = est.update(ff, calibrated=True)
        pol.update(st)
        states.append(st)
        t += 0.05
    assert all(s.face_lost for s in states)
    assert not states[0].distracted            # inside the grace period
    assert states[-1].distracted               # beyond it
    assert all(s.confidence == 0.0 for s in states)


def test_microsleep_threshold_actually_comes_from_the_config():
    """Regression: state.py hardcoded `ongoing_closure_s >= 0.5`.

    That was a second copy of features.blink.microsleep_duration_s, so editing
    the config changed how events were labelled but not when the alert fired.
    Raise the threshold and a closure that used to trigger must not.
    """
    cfg = load_config()
    cfg["features"]["blink"]["microsleep_duration_s"] = 1.5
    ex = FeatureExtractor(cfg["features"], cfg["calibration"])
    est = StateEstimator(cfg["state"])
    pol = EscalationPolicy(cfg["alerts"])
    pl = RestPlanner(cfg["predictor"])

    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)

    # 0.9 s closure: past the old hardcoded 0.5 s, inside the new 1.5 s.
    out = run_sequence(ex, est, pol, pl, [(0.05, 0.05, 0.0, 0.0)] * 18, t0=13.0)
    assert any(ff.eye_closed for (_, ff, _, _) in out)
    assert not any(st.microsleep_now for (_, _, st, _) in out), \
        "config threshold ignored; microsleep fired at the hardcoded 0.5 s"

    # Keep going past 1.5 s and it must fire.
    out = run_sequence(ex, est, pol, pl, [(0.05, 0.05, 0.0, 0.0)] * 30, t0=13.9)
    assert any(st.microsleep_now for (_, _, st, _) in out)


def test_off_road_threshold_actually_comes_from_the_config():
    """Same bug class: state.py compared against its own literal 2.0 s."""
    cfg = load_config()
    cfg["features"]["head"]["off_road_alert_s"] = 4.0
    ex = FeatureExtractor(cfg["features"], cfg["calibration"])
    est = StateEstimator(cfg["state"])
    pol = EscalationPolicy(cfg["alerts"])
    pl = RestPlanner(cfg["predictor"])

    ex.start_calibration(0.0)
    run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 0.0)] * 260)

    # 2.5 s glance: past the old literal 2.0 s, inside the new 4.0 s.
    out = run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 40.0)] * 50, t0=13.0)
    assert any(ff.off_road for (_, ff, _, _) in out)
    assert not any(st.distracted for (_, _, st, _) in out), \
        "config threshold ignored; distraction fired at the hardcoded 2.0 s"

    out = run_sequence(ex, est, pol, pl, [(0.30, 0.05, 0.0, 40.0)] * 50, t0=15.5)
    assert any(st.distracted for (_, _, st, _) in out)


def test_gaze_off_road_threshold_is_configurable():
    cfg = load_config()
    cfg["state"]["gaze_off_road_threshold"] = 0.9
    est = StateEstimator(cfg["state"])
    s = est.update(FeatureFrame(t=1.0, face_found=True, pose_valid=True,
                                gaze_valid=True, interocular_px=120.0,
                                ear_norm=1.0, gaze_h=0.7), calibrated=True)
    assert not s.distracted
    est2 = StateEstimator(load_config()["state"])   # default 0.55
    s2 = est2.update(FeatureFrame(t=1.0, face_found=True, pose_valid=True,
                                  gaze_valid=True, interocular_px=120.0,
                                  ear_norm=1.0, gaze_h=0.7), calibrated=True)
    assert s2.distracted


def test_config_loads_and_has_every_block_the_code_reads():
    cfg = load_config()
    for key in ("capture", "landmarks", "features", "calibration", "state",
                "predictor", "alerts", "logging", "ui"):
        assert key in cfg, f"config is missing the {key!r} block"
    stage_actuators = {a for s in cfg["alerts"]["stages"]
                       for a in (s.get("actuators") or [])}
    assert stage_actuators <= set(cfg["alerts"]["actuators"]), \
        "a stage references an actuator that is not defined"
