"""State fusion, escalation policy and rest-planning tests."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import (  # noqa: E402
    Actuator, AtomizerActuator, EscalationPolicy, NullActuator, PeltierFanActuator,
)
from bamnun.features import FeatureFrame  # noqa: E402
from bamnun.predictor import (  # noqa: E402
    RestPlanner, theil_sen_slope, two_process_alertness,
)
from bamnun.state import StateEstimator, _ramp  # noqa: E402


STATE_CFG = {
    "weights": {"perclos": 0.35, "blink_duration": 0.20, "microsleep": 0.25,
                "yawn": 0.10, "head_nod": 0.10},
    "levels": [
        {"name": "alert", "min_score": 0.00, "dwell_s": 0.0},
        {"name": "mild", "min_score": 0.35, "dwell_s": 3.0},
        {"name": "drowsy", "min_score": 0.55, "dwell_s": 2.0},
        {"name": "severe", "min_score": 0.75, "dwell_s": 1.0},
    ],
    "recovery_hysteresis": 0.08,
    "no_face_grace_s": 1.5,
}

ALERT_CFG = {
    "enabled": True,
    "stages": [
        {"name": "none", "actuators": []},
        {"name": "notify", "actuators": ["chime"], "cooldown_s": 45.0},
        {"name": "rouse", "actuators": ["chime", "scent"], "cooldown_s": 90.0},
        {"name": "shock", "actuators": ["voice", "scent", "thermal"], "cooldown_s": 30.0},
    ],
    "actuators": {
        "chime": {"type": "null"},
        "voice": {"type": "null"},
        "scent": {"type": "atomizer", "gpio_pin": 23, "duration_s": 0.3,
                  "refractory_s": 120.0, "max_per_hour": 3},
        "thermal": {"type": "peltier_fan", "precool_s": 20.0, "burst_s": 4.0,
                    "refractory_s": 60.0},
    },
}


def ff(t=0.0, **kw) -> FeatureFrame:
    base = dict(t=t, face_found=True, pose_valid=True, gaze_valid=True,
                interocular_px=120.0, ear_norm=1.0)
    base.update(kw)
    return FeatureFrame(**base)


# --------------------------------------------------------------------------- #
# Ramp and fusion
# --------------------------------------------------------------------------- #


def test_ramp_clamps_both_ends():
    assert _ramp(-5, 0, 10) == 0.0
    assert _ramp(15, 0, 10) == 1.0
    assert _ramp(5, 0, 10) == pytest.approx(0.5)
    assert _ramp(5, 3, 3) == 0.0          # degenerate range must not divide by zero


def test_weights_are_normalised():
    est = StateEstimator({"weights": {"a": 2.0, "b": 2.0}, "levels": STATE_CFG["levels"]})
    assert sum(est.weights.values()) == pytest.approx(1.0)


def test_fully_alert_driver_scores_near_zero():
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, perclos=0.02, mean_blink_duration_s=0.13,
                      pitch_std=1.0), calibrated=True)
    assert s.score < 0.05
    assert s.level == 0
    assert s.kss < 1.5


def test_high_perclos_raises_score_and_kss():
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, perclos=0.30, mean_blink_duration_s=0.45,
                      microsleep_count=2, pitch_std=10.0,
                      yawn_rate_per_hour=12.0), calibrated=True)
    assert s.score == pytest.approx(1.0, abs=1e-6)
    assert s.kss == pytest.approx(9.0, abs=1e-6)


def test_component_breakdown_is_exposed():
    """The poster needs per-term contributions, so they must be reported."""
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, perclos=0.175), calibrated=True)
    assert set(s.components) == {"perclos", "blink_duration", "microsleep",
                                 "yawn", "head_nod"}
    assert s.components["perclos"] == pytest.approx(0.5, abs=1e-6)
    assert s.score == pytest.approx(0.35 * 0.5, abs=1e-6)


def test_ongoing_closure_overrides_the_window_average():
    """An eye shut right now must not be averaged away by a calm 60 s window."""
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, perclos=0.0, ongoing_closure_s=0.8, microsleep_now=True), calibrated=True)
    assert s.microsleep_now
    assert s.score >= 0.90
    assert s.emergency


# --------------------------------------------------------------------------- #
# Level machine
# --------------------------------------------------------------------------- #


def test_dwell_time_is_enforced_before_escalation():
    est = StateEstimator(STATE_CFG)
    # perclos comp 1.0 (x0.35) + blink comp 0.3 (x0.20) = 0.41 -> level 1,
    # whose dwell is 3 s.
    mild = dict(perclos=0.30, mean_blink_duration_s=0.24)
    assert est.update(ff(t=0.0, **mild), calibrated=True).score == pytest.approx(0.41, abs=1e-6)
    for t in (0.0, 1.0, 2.9):
        s = est.update(ff(t=t, **mild), calibrated=True)
        assert s.level == 0, f"escalated at t={t} before the 3 s dwell elapsed"
    s = est.update(ff(t=3.1, **mild), calibrated=True)
    assert s.level == 1


def test_hysteresis_prevents_flapping_on_the_way_down():
    est = StateEstimator(STATE_CFG)
    hi = dict(perclos=0.30, mean_blink_duration_s=0.45, microsleep_count=2,
              yawn_rate_per_hour=12.0, pitch_std=10.0)
    t = 0.0
    for _ in range(12):
        s = est.update(ff(t=t, **hi), calibrated=True)
        t += 1.0
    assert s.level == 3
    # Nudge the score into the hysteresis band: below level 3's 0.75 entry
    # threshold but not yet below 0.75 - 0.08. It must stay at level 3.
    # 0.35 + 0.20 + 0.25*0.5 + 0 + 0.10*0.125 = 0.6875
    s = est.update(ff(t=t, perclos=0.30, mean_blink_duration_s=0.45,
                      microsleep_count=1, pitch_std=3.0), calibrated=True)
    assert s.score == pytest.approx(0.6875, abs=1e-6)
    assert 0.67 < s.score < 0.75
    assert s.level == 3, "de-escalated without clearing the hysteresis band"
    # Now push it clearly below the band and it should fall.
    s = est.update(ff(t=t + 1.0, perclos=0.30), calibrated=True)
    assert s.score == pytest.approx(0.35, abs=1e-6)
    assert s.level == 1


def test_escalation_climbs_one_stage_per_cooldown():
    """The ladder must be paced by the cooldowns, not by the frame rate."""
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    hi = dict(perclos=0.30, mean_blink_duration_s=0.45, microsleep_count=2,
              yawn_rate_per_hour=12.0, pitch_std=10.0)

    # 5 s of frames at 20 Hz. Level reaches 3 after the 1 s dwell, but only
    # the first stage may have fired: stage 1's cooldown is 45 s.
    t = 0.0
    for _ in range(100):
        pol.update(est.update(ff(t=t, **hi), calibrated=True))
        t += 0.05
    assert pol.stage == 1, f"ladder was skipped at frame rate (stage={pol.stage})"

    # Advance past each stage's own cooldown (45 s, then 90 s) and the stage
    # should step up exactly once per wait.
    t += 46.0
    pol.update(est.update(ff(t=t, **hi), calibrated=True))
    assert pol.stage == 2
    t += 46.0                     # not yet past stage 2's 90 s cooldown
    pol.update(est.update(ff(t=t, **hi), calibrated=True))
    assert pol.stage == 2, "stepped up before stage 2's cooldown expired"
    t += 46.0
    pol.update(est.update(ff(t=t, **hi), calibrated=True))
    assert pol.stage == 3


def test_active_microsleep_bypasses_the_ladder():
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=0.0, perclos=0.0, ongoing_closure_s=1.0, microsleep_now=True), calibrated=True)
    d = pol.update(s)
    assert s.microsleep_now
    # The dwell timer must not delay this: it fires on the first frame.
    assert s.level == len(STATE_CFG["levels"]) - 1
    assert pol.stage == len(ALERT_CFG["stages"]) - 1
    assert "voice" in [a.actuator for a in d.fired]


def test_short_microsleep_still_reaches_the_top_level():
    """A 0.6 s closure is shorter than the top level's 1 s dwell."""
    est = StateEstimator(STATE_CFG)
    t = 0.0
    reached = False
    for _ in range(12):            # 0.6 s at 20 Hz
        s = est.update(ff(t=t, perclos=0.0, ongoing_closure_s=0.55, microsleep_now=True), calibrated=True)
        reached |= s.level == len(STATE_CFG["levels"]) - 1
        t += 0.05
    assert reached, "dwell timer swallowed a genuine microsleep"


# --------------------------------------------------------------------------- #
# Distraction channel
# --------------------------------------------------------------------------- #


def test_distraction_is_independent_of_drowsiness():
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, perclos=0.01, off_road=True, off_road_alarm=True,
                      off_road_glance_s=2.4),
                   calibrated=True)
    assert s.distracted and "off-road" in s.distraction_reason
    assert s.score < 0.05, "distraction leaked into the drowsiness score"
    assert s.level == 0


def test_short_glance_is_not_distraction():
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, off_road=True, off_road_glance_s=1.2), calibrated=True)
    assert not s.distracted


def test_gaze_off_road_with_head_forward_is_caught():
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, gaze_h=0.8, off_road=False), calibrated=True)
    assert s.distracted and s.distraction_reason == "gaze off-road"


def test_distraction_alone_fires_stage_one():
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    s = est.update(ff(t=1.0, perclos=0.0, off_road=True, off_road_alarm=True,
                     off_road_glance_s=3.0),
                   calibrated=True)
    d = pol.update(s)
    assert d.stage == 1
    assert [a.actuator for a in d.fired] == ["chime"]


# --------------------------------------------------------------------------- #
# Face loss
# --------------------------------------------------------------------------- #


def test_face_loss_within_grace_is_not_distraction():
    est = StateEstimator(STATE_CFG)
    est.update(ff(t=0.0), calibrated=True)
    s = est.update(FeatureFrame(t=1.0, face_found=False), calibrated=True)
    assert s.face_lost and not s.distracted
    assert s.confidence == 0.0


def test_prolonged_face_loss_flags_distraction():
    est = StateEstimator(STATE_CFG)
    est.update(ff(t=0.0), calibrated=True)
    est.update(FeatureFrame(t=1.0, face_found=False), calibrated=True)
    s = est.update(FeatureFrame(t=4.0, face_found=False), calibrated=True)
    assert s.distracted and s.distraction_reason == "driver not visible"


def test_confidence_drops_when_face_is_too_small():
    est = StateEstimator(STATE_CFG)
    near = est.update(ff(t=1.0, interocular_px=120.0), calibrated=True)
    far = est.update(ff(t=2.0, interocular_px=25.0), calibrated=True)
    assert far.confidence < near.confidence


# --------------------------------------------------------------------------- #
# Alert suppression rules
# --------------------------------------------------------------------------- #


def test_no_alerts_before_calibration():
    """A false positive in front of a judge is worse than a miss."""
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    hi = dict(perclos=0.30, mean_blink_duration_s=0.45, microsleep_count=2)
    t = 0.0
    for _ in range(8):
        s = est.update(ff(t=t, **hi), calibrated=False)
        d = pol.update(s)
        assert d.stage == 0 and not d.fired
        t += 1.0


def test_actuator_refractory_period_is_respected():
    a = AtomizerActuator("scent", {"gpio_pin": 23, "duration_s": 0.3,
                                   "refractory_s": 120.0})
    assert a.fire(0.0, "rouse") is not None
    assert a.fire(30.0, "rouse") is None
    assert a.fire(119.0, "rouse") is None
    assert a.fire(121.0, "rouse") is not None


def test_actuator_hourly_budget_is_respected():
    a = AtomizerActuator("scent", {"refractory_s": 1.0, "max_per_hour": 3})
    fired = [a.fire(float(i) * 10.0, "rouse") for i in range(6)]
    assert sum(1 for f in fired if f is not None) == 3
    # and the budget frees up after an hour
    assert a.fire(3700.0, "rouse") is not None


def test_suppressed_actuators_are_reported_not_silently_dropped():
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    hi = dict(perclos=0.30, mean_blink_duration_s=0.45, microsleep_count=2,
              yawn_rate_per_hour=12.0, pitch_std=10.0)
    t, suppressed_seen = 0.0, False
    for _ in range(40):
        s = est.update(ff(t=t, **hi), calibrated=True)
        d = pol.update(s)
        if d.suppressed:
            suppressed_seen = True
        t += 5.0
    assert suppressed_seen, "scent refractory never surfaced in the decision"


def test_thermal_precools_before_it_is_needed():
    """The Peltier needs lead time; the policy must arm it one stage early."""
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    thermal = next(a for a in pol.actuators.values()
                   if isinstance(a, PeltierFanActuator))
    assert thermal._precooling_since is None
    s = est.update(ff(t=1.0, perclos=0.25, mean_blink_duration_s=0.40,
                      microsleep_count=1), calibrated=True)
    for t in (2.0, 5.0, 8.0):
        s = est.update(ff(t=t, perclos=0.25, mean_blink_duration_s=0.40,
                          microsleep_count=1), calibrated=True)
        pol.update(s)
    assert thermal._precooling_since is not None, "thermal never pre-cooled"


def test_de_escalation_stands_the_thermal_down():
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    thermal = next(a for a in pol.actuators.values()
                   if isinstance(a, PeltierFanActuator))
    hi = dict(perclos=0.30, mean_blink_duration_s=0.45, microsleep_count=2,
              yawn_rate_per_hour=12.0, pitch_std=10.0)
    t = 0.0
    for _ in range(8):
        pol.update(est.update(ff(t=t, **hi), calibrated=True))
        t += 1.0
    assert thermal._precooling_since is not None
    for _ in range(8):
        pol.update(est.update(ff(t=t, perclos=0.0), calibrated=True))
        t += 1.0
    assert pol.stage == 0
    assert thermal._precooling_since is None


def test_de_escalation_does_not_immediately_re_fire():
    """Regression: a closure ending used to produce an alert burst.

    Sequence that broke it: microsleep override jumps to the top stage, the
    closure ends, the policy drops one stage, and because de-escalation
    cleared the cooldown the lower stage fired on the very next frame.
    """
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    hi = dict(perclos=0.30, mean_blink_duration_s=0.45, microsleep_count=1,
              pitch_std=3.0)
    t = 0.0
    # Closure in progress -> override to the top stage.
    for _ in range(10):
        pol.update(est.update(ff(t=t, ongoing_closure_s=1.0, microsleep_now=True, **hi), calibrated=True))
        t += 0.05
    assert pol.stage == 3

    # Closure ends. Score falls to ~0.69 -> level 2 after hysteresis.
    fired_after = []
    for _ in range(40):                 # 2 s of frames
        d = pol.update(est.update(ff(t=t, **hi), calibrated=True))
        if d.fired:
            fired_after.append((t, d.stage_name, [a.actuator for a in d.fired]))
        t += 0.05
    assert fired_after == [], f"alert burst after de-escalation: {fired_after}"


def test_microsleep_override_does_not_fire_every_frame():
    """Regression: the override re-entered the top stage on every frame."""
    pol = EscalationPolicy(ALERT_CFG)
    est = StateEstimator(STATE_CFG)
    t, n_fires = 0.0, 0
    for _ in range(50):                 # 2.5 s of continuous closure at 20 Hz
        d = pol.update(est.update(ff(t=t, ongoing_closure_s=1.5, microsleep_now=True), calibrated=True))
        if d.fired:
            n_fires += 1
        t += 0.05
    assert n_fires == 1, f"override fired {n_fires} times during one closure"


def test_disabled_policy_never_fires():
    cfg = dict(ALERT_CFG)
    cfg["enabled"] = False
    pol = EscalationPolicy(cfg)
    est = StateEstimator(STATE_CFG)
    d = pol.update(est.update(ff(t=1.0, ongoing_closure_s=3.0, microsleep_now=True), calibrated=True))
    assert not d.fired


# --------------------------------------------------------------------------- #
# Predictor
# --------------------------------------------------------------------------- #


def test_theil_sen_recovers_a_known_slope():
    t = np.arange(0.0, 100.0, 1.0)
    y = 0.1 + 0.004 * t
    slope, intercept = theil_sen_slope(t, y)
    assert slope == pytest.approx(0.004, abs=1e-9)
    assert intercept == pytest.approx(0.1, abs=1e-9)


def test_theil_sen_is_robust_to_outliers():
    """Microsleep overrides pin the score at 0.9; the slope must survive them."""
    t = np.arange(0.0, 100.0, 1.0)
    y = 0.1 + 0.004 * t
    y[10:20] = 0.9                      # 10% of samples are saturated spikes
    slope, _ = theil_sen_slope(t, y)
    ls_slope = np.polyfit(t, y, 1)[0]
    assert abs(slope - 0.004) < abs(ls_slope - 0.004)
    assert slope == pytest.approx(0.004, abs=1e-3)


def test_theil_sen_degenerate_inputs():
    assert theil_sen_slope(np.array([]), np.array([]))[0] == 0.0
    assert theil_sen_slope(np.zeros(5), np.ones(5))[0] == 0.0


def test_two_process_model_rises_with_time_awake():
    a = two_process_alertness(4.0, 12.0)
    b = two_process_alertness(12.0, 12.0)
    c = two_process_alertness(20.0, 12.0)
    assert a < b < c


def test_two_process_model_has_an_afternoon_dip():
    """The 12-hour harmonic should make mid-afternoon worse than late afternoon."""
    dip = two_process_alertness(8.0, 14.5)
    peak = two_process_alertness(8.0, 16.5)
    assert dip > peak


def test_two_process_model_is_bounded():
    for h in range(0, 24):
        for awake in (0.0, 8.0, 40.0):
            v = two_process_alertness(awake, float(h))
            assert 0.0 <= v <= 1.0 and math.isfinite(v)


def test_planner_refuses_to_guess_without_history():
    p = RestPlanner({"enabled": True, "min_history_s": 120.0})
    p.push(0.0, 0.1)
    p.push(10.0, 0.12)
    plan = p.plan(10.0)
    assert not plan.valid and "history" in plan.reason


def test_planner_predicts_a_crossing_for_a_rising_driver():
    cfg = {"enabled": True, "trend_window_s": 900.0, "min_history_s": 120.0,
           "unsafe_score": 0.55, "blend_measured_weight": 0.7,
           "min_rest_lead_time_s": 300.0, "rest_interval_cap_s": 7200.0}
    p = RestPlanner(cfg)
    p.set_driver_context(14.0)
    t = 0.0
    while t <= 600.0:                     # 10 min climbing 0.10 -> 0.40
        p.push(t, 0.10 + 0.0005 * t)
        t += 1.0
    plan = p.plan(600.0)
    assert plan.valid
    assert plan.slope_per_min == pytest.approx(0.03, abs=0.005)
    assert plan.time_to_unsafe_s is not None
    assert 0 < plan.time_to_unsafe_s < 3600
    assert plan.rest_at_s is not None and plan.rest_at_s < plan.time_to_unsafe_s
    assert plan.curve_score and plan.curve_score[0] == pytest.approx(plan.current_score,
                                                                     abs=0.02)


def test_planner_curve_is_continuous_at_the_present():
    """Anchoring the model to the measurement: no jump at t = 0."""
    p = RestPlanner({"enabled": True, "min_history_s": 60.0})
    for t in range(0, 300):
        p.push(float(t), 0.30)
    plan = p.plan(299.0)
    assert plan.valid
    assert abs(plan.curve_score[0] - plan.current_score) < 0.02


def test_planner_says_rest_now_when_already_unsafe():
    p = RestPlanner({"enabled": True, "min_history_s": 60.0, "unsafe_score": 0.55})
    for t in range(0, 200):
        p.push(float(t), 0.70)
    plan = p.plan(199.0)
    assert plan.valid and plan.recommend_rest_now
    assert plan.time_to_unsafe_s == 0.0
    assert "now" in plan.summary()


def test_planner_flat_alert_driver_gets_no_urgent_rest():
    p = RestPlanner({"enabled": True, "min_history_s": 60.0, "unsafe_score": 0.55,
                     "rest_interval_cap_s": 3600.0})
    p.set_driver_context(2.0)             # well rested
    for t in range(0, 400):
        p.push(float(t), 0.05)
    plan = p.plan(399.0)
    assert plan.valid
    assert not plan.recommend_rest_now


def test_planner_sustained_unsafe_exposure_forces_rest_now():
    """Regression: an oscillating severe driver was told no rest was needed.

    A score that swings between 0.35 and 0.90 can fit a NEGATIVE trend, and
    the trend-only planner concluded there was no crossing within two hours
    for a driver who had spent a third of the last ten minutes unsafe.
    """
    cfg = {"enabled": True, "trend_window_s": 600.0, "min_history_s": 120.0,
           "unsafe_score": 0.55, "unsafe_exposure_fraction": 0.20}
    p = RestPlanner(cfg)
    # Descending sawtooth: slope is negative, exposure is high.
    for i in range(600):
        t = float(i)
        p.push(t, 0.90 if (i % 3 == 0) else 0.40 - 0.0001 * t)
    plan = p.plan(599.0)
    assert plan.valid
    assert plan.slope_per_min <= 0.0, "test needs a non-positive trend to be meaningful"
    assert plan.unsafe_fraction >= 0.20
    assert plan.recommend_rest_now, "sustained unsafe exposure did not force a stop"
    assert "unsafe for" in plan.reason


def test_planner_low_exposure_does_not_trigger_the_safety_net():
    cfg = {"enabled": True, "trend_window_s": 600.0, "min_history_s": 120.0,
           "unsafe_score": 0.55, "unsafe_exposure_fraction": 0.20}
    p = RestPlanner(cfg)
    for i in range(600):
        p.push(float(i), 0.90 if (i % 40 == 0) else 0.20)
    plan = p.plan(599.0)
    assert plan.unsafe_fraction < 0.20
    assert not plan.recommend_rest_now


def test_planner_current_score_uses_the_last_minute():
    """Stability of the reported 'current' must not depend on session length."""
    cfg = {"enabled": True, "trend_window_s": 1800.0, "min_history_s": 60.0}
    short, long = RestPlanner(cfg), RestPlanner(cfg)
    for i in range(200):
        short.push(float(i), 0.10)
    for i in range(1500):
        long.push(float(i), 0.10)
    # Both end with the same recent behaviour, so both must report the same.
    for i in range(60):
        short.push(200.0 + i, 0.40)
        long.push(1500.0 + i, 0.40)
    assert short.plan(259.0).current_score == pytest.approx(0.40, abs=1e-6)
    assert long.plan(1559.0).current_score == pytest.approx(0.40, abs=1e-6)


def test_planner_confidence_grows_with_clean_history():
    cfg = {"enabled": True, "min_history_s": 60.0, "trend_window_s": 1200.0}
    clean = RestPlanner(cfg)
    noisy = RestPlanner(cfg)
    rng = np.random.default_rng(3)
    for t in range(0, 600):
        clean.push(float(t), 0.20 + 0.0002 * t)
        noisy.push(float(t), 0.20 + 0.0002 * t + rng.normal(0, 0.30))
    assert clean.plan(599.0).confidence > noisy.plan(599.0).confidence


# --------------------------------------------------------------------------- #
# Face lost at the end of a glance is not an absent driver
# --------------------------------------------------------------------------- #

TURN_CFG = dict(STATE_CFG, turn_away_yaw_deg=35.0, lost_glance_grace_s=4.0)


def _lose_face(est, *, last_yaw: float, for_s: float, dt: float = 0.05):
    """Show one valid frame at ``last_yaw``, then drop tracking for ``for_s``."""
    t = 0.0
    est.update(ff(t=t, yaw=last_yaw), calibrated=True)
    out = []
    t += dt
    while t <= for_s:
        out.append(est.update(ff(t=t, face_found=False, pose_valid=False),
                              calibrated=True))
        t += dt
    return out


def test_face_lost_after_a_shoulder_check_is_not_reported_as_absent():
    """MediaPipe drops the face past ~45 deg, so a blind-spot check ends in a
    loss. Charging it the 1.5 s absent-driver grace accused an attentive
    driver of leaving the seat for looking where the mirror is."""
    est = StateEstimator(TURN_CFG)
    out = _lose_face(est, last_yaw=-55.0, for_s=3.0)
    assert not any(s.distracted for s in out), (
        "a 3 s shoulder check was reported as a distraction"
    )
    assert all(s.face_lost for s in out)
    assert all(s.confidence == 0.0 for s in out)


def test_a_face_that_vanishes_head_on_is_still_reported_quickly():
    """The guard must not blunt the real case: an empty seat, or a camera
    blocked while the driver was facing forward, still trips at 1.5 s."""
    est = StateEstimator(TURN_CFG)
    out = _lose_face(est, last_yaw=0.0, for_s=3.0)
    flagged = [s for s in out if s.distracted]
    assert flagged, "a forward-facing driver vanishing was never flagged"
    assert flagged[0].face_lost_s == pytest.approx(1.55, abs=0.1)
    assert flagged[0].distraction_reason == "driver not visible"


def test_a_turned_away_face_is_eventually_flagged_too():
    """The longer grace is a delay, not an exemption: a head turned away for
    good is a driver who has stopped watching the road."""
    est = StateEstimator(TURN_CFG)
    out = _lose_face(est, last_yaw=-55.0, for_s=6.0)
    flagged = [s for s in out if s.distracted]
    assert flagged, "a 6 s turned-away loss was never flagged"
    assert flagged[0].face_lost_s == pytest.approx(4.05, abs=0.1)
    assert "turned away" in flagged[0].distraction_reason
