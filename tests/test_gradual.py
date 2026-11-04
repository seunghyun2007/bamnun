"""Gradual drowsiness (docs/SPEC.md, section 14).

Drives the real FeatureExtractor and StateEstimator with the shipped config
and a synthetic eyelid: a calibrated open EAR of 0.30, blinks of a chosen
length every few seconds, squints, glances down, and a microsleep.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import EscalationPolicy  # noqa: E402
from bamnun.features import Calibration, FeatureExtractor, HeadPose  # noqa: E402
from bamnun.session import load_config  # noqa: E402
from bamnun.state import StateEstimator  # noqa: E402

FPS = 30.0
OPEN = 0.30          # calibrated open-eye EAR
SHUT = 0.05          # EAR of a closed eye (about a sixth of open)


class Driver:
    """A synthetic driver fed through the real pipeline, frame by frame."""

    def __init__(self):
        cfg = load_config()
        self.cfg = cfg
        self.fx = FeatureExtractor(cfg["features"], cfg["calibration"])
        self.fx.set_calibration(Calibration(ear_open=OPEN, ear_std=0.01, complete=True, n_samples=999))
        self.est = StateEstimator(cfg["state"])
        alerts = cfg["alerts"]
        for spec in alerts["actuators"].values():
            spec["type"] = "null"
        self.policy = EscalationPolicy(alerts)
        self.t = 0.0
        self.log = []                   # (t, state, frame, stage)

    def frame(self, ear, pitch=0.0):
        ff = self.fx.measure(self.t, ear, 0.1, HeadPose(0.0, pitch, 0.0, True), (0.0, 0.0, True), 120.0)
        st = self.est.update(ff, calibrated=True)
        d = self.policy.update(st)
        self.log.append((self.t, st, ff, d.stage))
        self.t += 1.0 / FPS
        return st

    def drive(self, seconds, open_level=1.0, blink_s=0.12, blink_every=4.0, pitch=0.0):
        """Eyes at ``open_level`` of normal, with a blink every ``blink_every`` s."""
        end, last = self.t + seconds, None
        while self.t < end:
            phase = self.t % blink_every
            if blink_s and phase < blink_s:
                # Lid shape: close over the first third, held, reopen over the last third.
                x = phase / blink_s
                depth = min(1.0, 3 * x, 3 * (1 - x))
                ear = OPEN * open_level - (OPEN * open_level - SHUT) * depth
            else:
                ear = OPEN * open_level
            last = self.frame(ear, pitch)
        return last

    def score_at(self, t):
        return min(self.log, key=lambda r: abs(r[0] - t))[1].score

    def labels(self, since=0.0):
        return {r[1].label for r in self.log if r[0] >= since}


def test_normal_blinking_stays_alert():
    d = Driver()
    s = d.drive(180)
    assert s.level == 0 and s.label == "alert"
    assert max(r[1].score for r in d.log) < 0.12
    # A normal blink never shows "Eyes closed" (the chip that disagreed with
    # the laptop overlay).
    assert d.labels() == {"alert"}
    assert max(r[3] for r in d.log) == 0


def test_slight_squint_gives_a_small_rise():
    d = Driver()
    base = d.drive(60).score
    s = d.drive(90, open_level=0.85)
    assert s.score > base + 0.02, "a held squint should register"
    assert s.score < 0.25 and s.level == 0, "a slight squint alone is not 'a bit tired'"
    assert not any(r[1].microsleep_now for r in d.log)


def test_hard_squint_rises_gradually_and_is_not_a_microsleep():
    d = Driver()
    d.drive(60)
    t0 = d.t
    s = d.drive(90, open_level=0.50, blink_s=0.0)
    assert d.score_at(t0 + 1.0) < 0.10, "it must not jump the moment the eyes narrow"
    assert d.score_at(t0 + 10) < d.score_at(t0 + 30) <= d.score_at(t0 + 60) + 1e-9
    assert not any(r[1].microsleep_now for r in d.log), "a squint is not a microsleep"
    assert 1 <= s.level <= 2, "sustained hard squinting is a mild-to-moderate sign, not extreme"
    assert max(r[3] for r in d.log) <= 2


def test_slow_blinks_over_a_minute_raise_the_score_steadily():
    d = Driver()
    d.drive(60)
    t0 = d.t
    s = d.drive(90, blink_s=0.40)
    a, b, c = d.score_at(t0 + 20), d.score_at(t0 + 50), d.score_at(t0 + 90)
    assert a < b < c, (a, b, c)
    assert s.level >= 1, "a minute of slow blinks is an early drowsiness sign"
    assert not any(r[1].microsleep_now for r in d.log), "0.4 s blinks are not microsleeps"
    # The ladder answers with its first step, not its last.
    assert 1 <= max(r[3] for r in d.log) <= 2


def test_looking_down_at_the_dashboard_briefly_is_not_drowsy():
    d = Driver()
    d.drive(30)
    for _ in range(6):                 # a 3 s look down every 20 s, for 2 minutes
        d.drive(3, open_level=0.60, blink_s=0.0, pitch=17.0)
        d.drive(17)
    assert max(r[1].score for r in d.log) < 0.15
    assert d.log[-1][1].level == 0
    assert "eyes_closed" not in d.labels()


def test_microsleep_jumps_straight_to_the_top():
    d = Driver()
    d.drive(30)
    t0 = d.t
    top = len(d.policy.stages) - 1
    while d.t < t0 + 0.6:
        st = d.frame(SHUT)
    assert st.microsleep_now and st.label == "eyes_closed"
    assert st.score >= 0.9
    assert d.policy.stage == top, "the safety bypass must not wait for the ladder"
    hit = next(r for r in d.log if r[3] == top)
    assert hit[0] - t0 < 0.7


def test_score_falls_back_slowly_after_the_driver_recovers():
    d = Driver()
    d.drive(60)
    d.drive(90, open_level=0.50, blink_s=0.0)
    peak = d.log[-1][1].score
    t0 = d.t
    d.drive(120)
    assert d.score_at(t0 + 5) > peak * 0.6, "it should not drop the instant the eyes open"
    assert d.log[-1][1].score < 0.12 and d.log[-1][1].level == 0


@pytest.mark.parametrize("narrow", [0.20, 0.36])
def test_thresholds_follow_the_drivers_own_open_level(narrow):
    """Narrow or wide eyes, glasses: only the change from the driver's own
    calibrated level counts, never the absolute EAR."""
    d = Driver()
    d.fx.set_calibration(Calibration(ear_open=narrow, ear_std=0.01, complete=True, n_samples=999))
    t_end = d.t + 120
    while d.t < t_end:
        phase = d.t % 4.0
        x = phase / 0.12 if phase < 0.12 else None
        ear = narrow if x is None else narrow - (narrow - narrow / 6) * min(1, 3 * x, 3 * (1 - x))
        d.frame(ear)
    assert d.log[-1][1].level == 0 and max(r[1].score for r in d.log) < 0.12


def test_glancing_down_at_a_phone_with_lids_almost_shut_is_not_a_microsleep():
    d = Driver()
    d.drive(30)
    t0 = d.t
    while d.t < t0 + 1.2:                  # head down, lids nearly closed, 1.2 s
        d.frame(SHUT, pitch=25.0)
    assert not any(r[1].microsleep_now for r in d.log)
    assert d.policy.stage < len(d.policy.stages) - 1


def test_head_dropping_with_eyes_shut_still_trips_the_bypass():
    d = Driver()
    d.drive(30)
    t0 = d.t
    while d.t < t0 + 1.7:                  # nodding off: head down AND eyes shut
        st = d.frame(SHUT, pitch=25.0)
    assert st.microsleep_now
    assert d.policy.stage == len(d.policy.stages) - 1


# --------------------------------------------------------------------------- #
# tools/replay_session.py: the tuning tool runs the same pipeline
# --------------------------------------------------------------------------- #


def _replay_tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "replay_session", Path(__file__).resolve().parents[1] / "tools" / "replay_session.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _measures(segments):
    """Cached-measurement arrays like replay_session writes, from (seconds, ear) parts."""
    import numpy as np
    rows, t = [], 0.0
    for seconds, level in segments:
        end = t + seconds
        while t < end:
            phase = t % 4.0
            ear = OPEN * level if phase >= 0.12 else SHUT
            rows.append((t, 1, ear, 0.1, 0.0, 0.0, 0.0, 1, 0.0, 0.0, 1, 120.0))
            t += 1.0 / FPS
    a = np.array(rows)
    tool = _replay_tool()
    return tool, {k: a[:, j] for j, k in enumerate(tool.FIELDS)}


def test_replay_tool_calibrates_then_scores_and_summarises_marked_stretches():
    tool, m = _measures([(70, 1.0), (60, 0.5)])
    rows = tool.replay(m, load_config(), calibrate_s=12.0)
    assert rows[0]["calibrating"] == 1 and rows[-1]["calibrating"] == 0
    s = tool.summary(rows, [(12.0, "normal"), (70.0, "hard_squint")])
    normal, squint = s
    assert normal["stretch"] == "normal" and normal["max_score"] < 12
    assert squint["end_score"] > normal["max_score"] + 10
    assert squint["microsleeps"] == 0


def test_replay_overrides_reach_the_pipeline():
    tool, m = _measures([(70, 1.0), (60, 0.5)])
    cfg = load_config()
    base = tool.replay(m, cfg)[-1]["score"]
    from bamnun.session import deep_update
    heavier = tool.replay(m, deep_update(load_config(), tool.parse_set(["state.weights.squint=0.9"])))[-1]["score"]
    assert heavier > base
    assert tool.parse_set(["a.b=1.5", "a.c=x"]) == {"a": {"b": 1.5, "c": "x"}}
