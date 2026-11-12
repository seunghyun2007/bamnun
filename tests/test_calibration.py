"""The calibrator learns the driver (docs/SPEC.md, section 15; audit F24-F28)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.eyes import Calibration, Calibrator, EyeInputs  # noqa: E402
from bamnun.features import HeadPose  # noqa: E402
from bamnun.session import load_config  # noqa: E402

FPS = 30.0


def look(cal, seconds, ear=0.28, t0=0.0, blink_every=3.0, blink_s=0.12, yaw=-8.0, pitch=6.0,
         wobble=0.0, brightness=130.0, iod_frac=0.12):
    """Feed a look-ahead; returns (Calibration or None, end time)."""
    t, res = t0, None
    while t < t0 + seconds and res is None:
        ph = (t - t0) % blink_every if blink_every else 99
        e = ear * (0.35 if blink_every and 0.5 <= ph < 0.5 + blink_s else 1.0)
        y = yaw + wobble * math.sin(2 * math.pi * 0.7 * t)
        p = pitch + wobble * math.cos(2 * math.pi * 0.5 * t)
        x = EyeInputs(ear_l=e, ear_r=e, blink_l=0.05 if e == ear else 0.8, blink_r=0.05 if e == ear else 0.8,
                      brightness=brightness, iod_frac=iod_frac)
        cal.feed(t, e, 0.05, HeadPose(y, p, 0.0, True), (0.0, 0.0, True), 150.0, x)
        res = cal.finish(t)
        t += 1 / FPS
    return res, t


def test_a_good_look_ahead_learns_the_driver():
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    cal, _ = look(c, 30.0)
    assert cal is not None and cal.complete
    assert cal.ear_open == pytest.approx(0.28, abs=0.005)       # the median, not a high percentile
    assert cal.yaw_zero == pytest.approx(-8.0, abs=0.5) and cal.pitch_zero == pytest.approx(6.0, abs=0.5)
    assert cal.n_blinks >= 3 and 0.08 <= cal.blink_half_s <= 0.2
    assert 15 <= cal.blink_rate <= 25
    assert cal.bs_open == pytest.approx(0.05, abs=0.01)
    assert cal.closed_estimated            # until the eyes-closed step


def test_it_waits_for_blinks_before_finishing():
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    cal, t = look(c, 30.0, blink_every=9.0)       # blinks at 0.5, 9.5 and 18.5 s
    assert cal is not None and t > 18.5, "finished before seeing 3 blinks"
    assert cal.n_blinks == 3


def test_a_dark_face_fails_with_a_plain_reason():
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    cal, _ = look(c, 16.0, brightness=20.0)
    assert cal is None and c.failure_code == "dark" and "dark" in c.last_failure.lower()


def test_a_moving_head_asks_to_hold_still():
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    cal, _ = look(c, 16.0, wobble=9.0)
    assert cal is None and c.failure_code == "still"


def test_a_camera_off_to_the_side_is_fine():
    """The old calibrator rejected absolute angles past 20 deg (F25)."""
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    cal, _ = look(c, 30.0, yaw=-24.0, pitch=18.0)
    assert cal is not None and cal.yaw_zero == pytest.approx(-24.0, abs=0.5)


@pytest.mark.parametrize("hint,kw", [("closer", {"iod_frac": 0.03}), ("dark", {"brightness": 20.0}),
                                     ("face_camera", {"yaw": 60.0})])
def test_live_hints(hint, kw):
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    look(c, 1.0, **kw)
    assert c.hint == hint


def _closed_step(c, cal, ear, bs=0.85, seconds=3.0):
    c.start_closed(100.0)
    t = 100.0
    while t < 100.0 + seconds:
        x = EyeInputs(ear_l=ear, ear_r=ear, blink_l=bs, blink_r=bs)
        c.feed_closed(t, x, HeadPose(cal.yaw_zero, cal.pitch_zero, 0.0, True))
        t += 1 / FPS
    return c.finish_closed(cal)


def test_the_closed_step_learns_the_closed_level():
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    cal, _ = look(c, 30.0)
    ok, code, why = _closed_step(c, cal, ear=0.09)
    assert ok and not cal.closed_estimated
    assert cal.ear_closed == pytest.approx(0.09, abs=0.005) and cal.bs_closed == pytest.approx(0.85, abs=0.02)
    assert cal.quality["separation"] == "ok"


def test_eyes_that_dont_close_apart_fail_with_a_reason():
    c = Calibrator(load_config()["calibration"])
    c.start(0.0)
    cal, _ = look(c, 30.0)
    ok, code, why = _closed_step(c, cal, ear=0.25, bs=0.15)
    assert not ok and code == "separation" and "apart" in why
    assert cal.closed_estimated


def test_an_old_calibration_file_is_upgraded():
    old = {"ear_open": 0.29, "ear_std": 0.015, "yaw_zero": -10.7, "pitch_zero": -1.9,
           "n_samples": 289, "complete": True}
    cal = Calibration.from_dict(old)
    assert cal.version == 2 and cal.closed_estimated and cal.complete
    assert cal.ear_open == pytest.approx(0.29 * 0.94) and cal.ear_closed == pytest.approx(cal.ear_open * 0.33)


def test_the_summary_has_what_the_phone_shows():
    s = Calibration(ear_open=0.21, ear_closed=0.09, blink_half_s=0.11, blink_rate=16.0,
                    complete=True, closed_estimated=False).summary()
    assert s["eye_size"] == "small" and s["blink_ms"] == 110 and s["separation"] == pytest.approx(0.57, abs=0.01)
    assert set(s) >= {"head", "wobble", "quality", "closed_estimated", "blink_rate"}
