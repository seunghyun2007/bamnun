"""The pieces of src/bamnun/eyes.py, one at a time (docs/SPEC.md, section 15)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.eyes import (BlinkDetector, Calibration, Conditions, EyeInputs,  # noqa: E402
                         NodDetector, Personal, RollingPerclos)


# -- blinks ------------------------------------------------------------------ #

def _blink(det, fps, half_s, t0=1.0, rest=1.0):
    """A triangular blink whose half-amplitude duration is ``half_s``."""
    ev, t, total = None, 0.0, 2.0 * half_s
    while t < t0 + total + 1.0:
        x = (t - t0) / total
        o = rest if not 0 <= x <= 1 else rest * abs(1 - 2 * x)
        ev = det.update(t, o, True) or ev
        t += 1.0 / fps
    return ev


@pytest.mark.parametrize("fps", [15.0, 30.0])
@pytest.mark.parametrize("half_s", [0.12, 0.35])
def test_blink_duration_is_timed_between_frames(fps, half_s):
    """At 15 fps a frame is 67 ms; interpolated crossings still time a
    120 ms blink to within ~20 ms (flaw F10)."""
    ev = _blink(BlinkDetector({}), fps, half_s)
    assert ev is not None
    assert ev.half_s == pytest.approx(half_s, abs=0.025)
    assert ev.kind == ("long" if half_s >= 0.30 else "blink")


def test_a_single_frame_blink_at_15_fps_is_still_seen():
    """The old EWMA smoothing erased 1-2 frame blinks (flaw F9)."""
    det = BlinkDetector({})
    for t, o in ((0.0, 1.0), (0.067, 1.0), (0.133, 0.1), (0.2, 1.0), (0.267, 1.0)):
        det.update(t, o, True)
    assert len(det.judged()) == 1


def test_a_held_closure_is_not_a_blink():
    det = BlinkDetector({})
    ev = None
    for i in range(80):
        t = i / 30.0
        ev = det.update(t, 1.0 if t < 0.3 or t > 2.0 else 0.1, True) or ev
    assert ev.kind == "held" and det.judged() == []


def test_blinks_in_unreliable_frames_are_not_judged():
    det = BlinkDetector({})
    for i in range(30):
        t = i / 30.0
        det.update(t, 0.1 if 10 <= i <= 12 else 1.0, reliable=not (10 <= i <= 12))
    assert det.events and det.judged() == []


# -- PERCLOS ------------------------------------------------------------------ #

def test_perclos_counts_only_reliable_time():
    p = RollingPerclos(60.0, 0.20)
    t = 0.0
    while t < 30.0:
        closed = 10.0 <= t < 13.0            # 3 s shut, counted
        laugh = 20.0 <= t < 25.0             # 5 s "shut" while laughing, not counted
        p.push(t, 0.05 if closed or laugh else 1.0, reliable=not laugh)
        t += 1 / 30
    assert p.value == pytest.approx(3.0 / 25.0, abs=0.01)


# -- nods ---------------------------------------------------------------------- #

def _pitch_run(det, segments, fps=30.0, eyes=1.0):
    """segments: (seconds, start_deg, end_deg, eyes); returns nods seen."""
    t = getattr(det, "_t", 0.0)
    nods = []
    for secs, a, b, o in segments:
        n = max(1, int(secs * fps))
        for i in range(n):
            p = a + (b - a) * (i + 1) / n
            ev = det.update(t, p, o)
            if ev:
                nods.append(ev)
            t += 1 / fps
    det._t = t
    return nods


def test_slow_drop_with_heavy_eyes_and_a_jerk_back_is_a_nod():
    det = NodDetector({})
    nods = _pitch_run(det, [(1.0, 0, 0, 1.0), (1.5, 0, 22, 0.3), (0.15, 22, 0, 0.9), (1.0, 0, 0, 1.0)])
    assert len(nods) == 1 and nods[0].depth >= 20 and nods[0].recovery_speed >= 60


def test_a_glance_at_the_dashboard_is_not_a_nod():
    det = NodDetector({})
    nods = _pitch_run(det, [(1.0, 0, 0, 1.0), (0.25, 0, 20, 0.6), (1.2, 20, 20, 0.6),
                            (0.25, 20, 0, 1.0), (1.0, 0, 0, 1.0)])
    assert nods == []


def test_holding_the_head_down_then_looking_up_is_not_a_nod():
    det = NodDetector({})
    nods = _pitch_run(det, [(0.3, 0, 35, 0.5), (3.0, 35, 35, 0.5), (0.15, 35, 0, 1.0), (1.0, 0, 0, 1.0)])
    assert nods == []


def test_a_shallow_wobble_is_not_a_nod():
    det = NodDetector({})
    det.wobble = 2.0
    nods = _pitch_run(det, [(1.0, 0, 9, 1.0), (0.1, 9, 0, 1.0), (1.0, 0, 0, 1.0)])
    assert nods == []


def test_face_lost_while_the_head_goes_down_is_a_head_drop():
    det = NodDetector({})
    _pitch_run(det, [(1.0, 0, 0, 1.0), (0.8, 0, 18, 0.4)])
    assert det.lost(det._t + 0.05)
    assert det.head_drop_since is not None and det.count() == 1


def test_face_lost_with_the_head_level_is_not_a_head_drop():
    det = NodDetector({})
    _pitch_run(det, [(2.0, 0, 1, 1.0)])
    assert not det.lost(det._t + 0.05)


# -- conditions ------------------------------------------------------------------ #

def _cond(frames, cal=None):
    c, cal = Conditions({}), cal or Calibration(complete=True)
    reasons = []
    for t, x, mar in frames:
        c.update(t, x, mar, cal)
        reasons.append(c.reason(t, x, 0.0, 0.0, 10.0))
    return c, reasons


def test_a_smile_makes_frames_unreliable_for_eyes():
    x = EyeInputs(ear_l=0.2, ear_r=0.2, blink_l=0.3, blink_r=0.3, smile=0.7, cheek=0.5, jaw=0.05)
    _, reasons = _cond([(i / 30, x, 0.05) for i in range(10)])
    assert set(reasons) == {"smile"}


def test_talking_is_recognised_from_jaw_movement():
    frames = [(i / 30, EyeInputs(blink_l=0.05, blink_r=0.05, smile=0.0, cheek=0.0,
                                 jaw=0.12 + 0.12 * math.sin(2 * math.pi * 4.5 * i / 30)), 0.1)
              for i in range(45)]
    _, reasons = _cond(frames)
    assert reasons[-1] == "talk"


def test_a_yawn_is_counted_once_and_masks_the_eyes():
    frames = [(i / 30, EyeInputs(blink_l=0.05, blink_r=0.05, smile=0.0, cheek=0.0,
                                 jaw=0.8 if 30 <= i < 150 else 0.02), 0.6) for i in range(200)]
    c, reasons = _cond(frames)
    assert len(c.yawns) == 1 and "yawn" in reasons


def test_a_sudden_lighting_change_masks_the_next_second():
    frames = [(i / 30, EyeInputs(brightness=140.0 if i < 60 else 60.0), 0.05) for i in range(120)]
    _, reasons = _cond(frames)
    assert reasons[59] == "" and reasons[62] == "lighting" and reasons[119] == ""


# -- openness ---------------------------------------------------------------------- #

def test_a_covered_eye_is_dropped_and_the_other_used():
    p = Personal({})
    x = EyeInputs(ear_l=0.05, ear_r=0.30, width_l=0.3, width_r=1.0)
    assert p.ear(x) == pytest.approx(0.30)


def test_openness_is_personal_so_small_and_large_eyes_read_the_same():
    p = Personal({"blendshape_weight": 0.0})
    for open_, closed in ((0.20, 0.085), (0.36, 0.10)):
        cal = Calibration(ear_open=open_, ear_closed=closed, complete=True)
        half = closed + 0.5 * (open_ - closed)
        o, _, _ = p.openness(EyeInputs(ear_l=half, ear_r=half), 0.0, 0.0, cal)
        assert o == pytest.approx(0.5, abs=1e-6)


def test_a_turned_head_does_not_read_as_wider_eyes():
    """Yaw narrows the eye, which raises EAR; compensation removes it (F7)."""
    p = Personal({"blendshape_weight": 0.0})
    cal = Calibration(ear_open=0.30, ear_closed=0.10, complete=True)
    turned = 0.30 / math.cos(math.radians(25))
    o, _, _ = p.openness(EyeInputs(ear_l=turned, ear_r=turned), 25.0, 0.0, cal)
    assert o == pytest.approx(1.0, abs=0.02)
