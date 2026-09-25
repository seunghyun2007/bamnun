#!/usr/bin/env python3
"""Drive the state, prediction and alert layers from a synthetic driver.

    python tools/simulate.py --minutes 45 --out runs/sim.csv

Why this exists. You cannot debug a 45-minute drowsiness trajectory with a
webcam and your own eyelids, and you certainly cannot reproduce it on demand
for a judge. This generates a physiologically-shaped EAR signal for a driver
who becomes progressively drowsy: blink rate and duration rise, PERCLOS
climbs, yawns appear, microsleeps begin, with a couple of distraction glances
thrown in. It then runs the real StateEstimator, RestPlanner and
EscalationPolicy over it.

Two things come out of it. First, a regression test: the escalation ladder and
the rest plan are exercised end to end with no hardware. Second, the poster
figure, which is the score trajectory with the alert stages marked on it.

It is a simulation of the SIGNAL, not of the detector. Every threshold, fusion
weight and timer under test is the real production code path.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import EscalationPolicy          # noqa: E402
from bamnun.features import FeatureExtractor, Calibration, FeatureFrame  # noqa: E402
from bamnun.predictor import RestPlanner            # noqa: E402
from bamnun.session import load_config              # noqa: E402
from bamnun.state import StateEstimator             # noqa: E402


def synth_ear_stream(minutes: float, fps: float, ear_open: float = 0.30,
                     seed: int = 7):
    """Yield (t, ear, mar, yaw, pitch) for a driver getting sleepy.

    Drowsiness ramps 0 -> 1 over the drive. As it rises:
      * blink rate goes from ~15/min to ~28/min then falls again (both are
        observed: rate rises then collapses as microsleeps take over),
      * blink duration goes from 120 ms to 380 ms,
      * microsleeps of 0.6 to 2.5 s start appearing past 0.6 drowsiness,
      * a yawn becomes likely past 0.35,
      * two deliberate off-road glances are inserted early on to exercise the
        distraction channel independently of drowsiness.
    """
    rng = random.Random(seed)
    dt = 1.0 / fps
    n = int(minutes * 60.0 * fps)

    closure_until = -1.0
    closure_depth = 0.0
    next_blink = 1.0
    yawn_until = -1.0
    glances = [(120.0, 2.6), (300.0, 3.4)]   # (start_s, duration_s)

    for i in range(n):
        t = i * dt
        drowsy = min(1.0, t / (minutes * 60.0))

        rate = 15.0 + 13.0 * math.sin(math.pi * min(drowsy, 1.0)) \
            if drowsy < 0.8 else 8.0
        mean_gap = 60.0 / max(rate, 1.0)
        dur = 0.12 + 0.26 * drowsy

        if t >= next_blink and t > closure_until:
            micro = drowsy > 0.6 and rng.random() < 0.18
            this_dur = rng.uniform(0.6, 2.5) if micro else max(0.05, rng.gauss(dur, 0.04))
            closure_until = t + this_dur
            closure_depth = rng.uniform(0.82, 0.95)
            next_blink = closure_until + max(0.3, rng.expovariate(1.0 / mean_gap))

        if t < closure_until:
            # Smooth eyelid trajectory rather than a square wave, so the EWMA
            # and hysteresis logic are exercised the way they will be in real
            # data.
            span = closure_until - (next_blink - max(0.3, mean_gap)) or 0.2
            phase = min(1.0, max(0.0, (t - (closure_until - span)) / max(span, 1e-3)))
            shape = math.sin(math.pi * min(1.0, phase * 1.0))
            ear = ear_open * (1.0 - closure_depth * max(shape, 0.75))
        else:
            ear = ear_open * (1.0 - 0.06 * drowsy) + rng.gauss(0.0, 0.004)

        if t > yawn_until and drowsy > 0.35 and rng.random() < 0.0006:
            yawn_until = t + rng.uniform(1.6, 3.2)
        mar = 0.72 if t < yawn_until else 0.05 + rng.gauss(0.0, 0.01)

        yaw, pitch = rng.gauss(0.0, 2.0), rng.gauss(0.0, 1.5)
        for gs, gd in glances:
            if gs <= t < gs + gd:
                yaw = 38.0
        pitch += 7.0 * drowsy * math.sin(2 * math.pi * t / 3.0) * (1.0 if drowsy > 0.5 else 0.0)

        yield (t, max(ear, 0.01), mar, yaw, pitch)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=45.0)
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--out", default="runs/sim.csv")
    ap.add_argument("--hours-awake", type=float, default=14.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    cfg["alerts"]["enabled"] = True

    extractor = FeatureExtractor(cfg["features"], cfg["calibration"])
    extractor.set_calibration(Calibration(ear_open=0.30, ear_std=0.01, complete=True,
                                          n_samples=999))
    estimator = StateEstimator(cfg["state"])
    planner = RestPlanner(cfg["predictor"])
    planner.set_driver_context(args.hours_awake)
    policy = EscalationPolicy(cfg["alerts"])

    out_path = Path(__file__).resolve().parents[1] / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    timeline = []
    plan = None

    for (t, ear, mar, yaw, pitch) in synth_ear_stream(
            args.minutes, args.fps, seed=args.seed):
        # Feed the real trackers directly. This bypasses only the landmark
        # geometry, which the unit tests cover separately.
        ear_s = extractor.ear_ewma.update(ear)
        cal = extractor.calibration
        ear_norm = ear_s / cal.ear_open
        ev = extractor.blink.update(t, ear_s, cal.ear_open)
        extractor.perclos_window.push(t, ear_norm)
        perclos = extractor.perclos_window.time_fraction_below(extractor.perclos_fraction)
        extractor.yawn.update(t, mar)
        off = extractor.head.update(t, yaw, pitch, True)

        ff = FeatureFrame(
            t=t, face_found=True, ear_raw=ear, ear=ear_s, ear_norm=ear_norm,
            eye_closed=extractor.blink.is_closed,
            ongoing_closure_s=extractor.blink.ongoing_closure_s,
            microsleep_now=extractor.blink.microsleep_in_progress,
            perclos=perclos,
            blink_rate_per_min=extractor.blink.blink_rate_per_min(),
            mean_blink_duration_s=extractor.blink.mean_blink_duration_s(),
            microsleep_count=extractor.blink.microsleep_count(),
            long_closure_count=extractor.blink.long_closure_count(),
            mar=mar, yawn_count=extractor.yawn.count(),
            yawn_rate_per_hour=extractor.yawn.rate_per_hour(),
            yaw=yaw, pitch=pitch, pose_valid=True,
            pitch_std=extractor.head.pitch_std(), nodding=extractor.head.nodding(),
            gaze_h=0.0, gaze_v=0.0, gaze_valid=True,
            off_road=off, off_road_alarm=extractor.head.off_road_alarm,
            off_road_glance_s=extractor.head.current_glance_s,
            long_glance_count=extractor.head.long_glance_count(),
            interocular_px=120.0,
            blink_event=ev.kind if ev else None,
        )

        state = estimator.update(ff, calibrated=True)
        planner.push(t, state.score)
        if int(t) % 30 == 0 and abs(t - round(t)) < 1.0 / args.fps:
            plan = planner.plan(t)

        decision = policy.update(state)
        if decision.fired:
            timeline.append((t, decision.stage_name,
                             [a.actuator for a in decision.fired],
                             round(state.score, 3)))

        if int(t * 2) != int((t - 1 / args.fps) * 2):   # 2 Hz sampling for the csv
            rows.append({
                "t": round(t, 2), "ear": round(ear_s, 4),
                "ear_norm": round(ear_norm, 4), "perclos": round(perclos, 4),
                "blink_rate": round(ff.blink_rate_per_min, 2),
                "blink_dur": round(ff.mean_blink_duration_s, 3),
                "microsleeps": ff.microsleep_count, "yawns": ff.yawn_count,
                "pitch_std": round(ff.pitch_std, 2),
                "score": round(state.score, 4), "level": state.level,
                "level_name": state.level_name, "kss": round(state.kss, 2),
                "distracted": int(state.distracted), "stage": policy.stage,
                "rest_at_min": (round(plan.rest_at_s / 60, 1)
                                if plan and plan.rest_at_s is not None else ""),
                "unsafe_in_min": (round(plan.time_to_unsafe_s / 60, 1)
                                  if plan and plan.time_to_unsafe_s else ""),
            })

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    if not args.quiet:
        print(f"\nwrote {out_path}  ({len(rows)} rows, {args.minutes:.0f} simulated minutes)")
        print("\nalert timeline")
        print(f"{'time':>9}  {'stage':<8} {'score':>6}  actuators")
        for (t, stage, acts, score) in timeline:
            print(f"{int(t)//60:5d}m{int(t)%60:02d}s  {stage:<8} {score:>6.3f}  "
                  f"{', '.join(acts)}")
        print(f"\ntotal actuations: {len(policy.history)}")
        if plan:
            print(f"final rest plan: {plan.summary()}  "
                  f"(slope {plan.slope_per_min:+.4f}/min, conf {plan.confidence:.2f})")

    policy.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
