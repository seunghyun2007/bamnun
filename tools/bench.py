#!/usr/bin/env python3
"""Measure the per-stage cost of the pipeline.

    python tools/bench.py --seconds 30 --source picamera

Prints a per-stage latency breakdown and the achievable end-to-end frame rate,
plus the Pi's throttle flags, because a thermally throttled Pi 5 silently
halves its clock and the symptom looks like slow code rather than a cooling
problem.

The numbers this prints belong in the report. "Runs at 24 fps on a Pi 5,
landmark inference 31 ms, everything else under 2 ms" is a concrete
engineering result; "runs in real time" is not.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.capture import open_source              # noqa: E402
from bamnun.features import FeatureExtractor        # noqa: E402
from bamnun.landmarks import FaceLandmarker         # noqa: E402
from bamnun.predictor import RestPlanner            # noqa: E402
from bamnun.session import load_config, repo_root   # noqa: E402
from bamnun.state import StateEstimator             # noqa: E402


def throttle_flags() -> str:
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
    except Exception:
        return "vcgencmd unavailable (not a Pi?)"
    try:
        val = int(out.split("=")[1], 16)
    except Exception:
        return out
    bits = {
        0: "under-voltage NOW", 1: "ARM freq capped NOW", 2: "THROTTLED NOW",
        3: "soft temp limit NOW", 16: "under-voltage occurred",
        17: "freq capped occurred", 18: "throttling occurred",
        19: "soft temp limit occurred",
    }
    active = [msg for bit, msg in bits.items() if val & (1 << bit)]
    return f"{out} -> {', '.join(active) if active else 'clean'}"


def temp_c() -> str:
    try:
        return subprocess.run(["vcgencmd", "measure_temp"], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return "n/a"


def pct(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    k = min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))
    return s[k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--source", default=None)
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    overrides = {}
    if args.source or args.device is not None:
        cap = {}
        if args.source:
            cap["source"] = args.source
        if args.device is not None:
            cap["device"] = int(args.device) if str(args.device).isdigit() else args.device
        overrides["capture"] = cap
    cfg = load_config(overrides=overrides)

    src = open_source(cfg["capture"])
    lmk = FaceLandmarker(cfg["landmarks"], repo_root=repo_root())
    fx = FeatureExtractor(cfg["features"], cfg["calibration"])
    est = StateEstimator(cfg["state"])
    pl = RestPlanner(cfg["predictor"])

    t_cap, t_lmk, t_feat, t_state, t_plan, t_total = [], [], [], [], [], []
    faces = 0
    n = 0

    print(f"source={cfg['capture']['source']} resolution={src.resolution}")
    print(f"temp before: {temp_c()}")
    print(f"throttle:    {throttle_flags()}")
    print(f"\nrunning {args.seconds:.0f} s ...")

    t_end = time.monotonic() + args.seconds
    try:
        while time.monotonic() < t_end:
            w0 = time.perf_counter()
            frame = src.read()
            w1 = time.perf_counter()
            if frame is None:
                break

            lms = lmk.process(frame)
            w2 = time.perf_counter()
            ff = fx.update(frame.timestamp, lms)
            w3 = time.perf_counter()
            st = est.update(ff, calibrated=True)
            w4 = time.perf_counter()
            pl.push(frame.timestamp, st.score)
            if n % 300 == 0:
                pl.plan(frame.timestamp)
            w5 = time.perf_counter()

            t_cap.append((w1 - w0) * 1e3)
            t_lmk.append((w2 - w1) * 1e3)
            t_feat.append((w3 - w2) * 1e3)
            t_state.append((w4 - w3) * 1e3)
            t_plan.append((w5 - w4) * 1e3)
            t_total.append((w5 - w0) * 1e3)
            faces += 1 if lms is not None else 0
            n += 1
    finally:
        lmk.close()
        src.close()

    if not n:
        print("no frames", file=sys.stderr)
        return 1

    print(f"\n{'stage':<22}{'mean ms':>9}{'p50':>8}{'p95':>8}{'max':>8}")
    for name, xs in (("capture", t_cap), ("landmarks", t_lmk),
                     ("features", t_feat), ("state", t_state),
                     ("predictor (amortised)", t_plan), ("TOTAL", t_total)):
        print(f"{name:<22}{statistics.fmean(xs):>9.2f}{pct(xs,50):>8.2f}"
              f"{pct(xs,95):>8.2f}{max(xs):>8.2f}")

    wall = sum(t_total) / 1e3
    print(f"\nframes           {n}")
    print(f"face detected    {faces} ({100.0*faces/n:.1f}%)")
    print(f"throughput       {n/wall:.1f} fps (pipeline-limited)")
    print(f"temp after:      {temp_c()}")
    print(f"throttle:        {throttle_flags()}")
    if faces / n < 0.9:
        print("\nWARNING: face detection below 90%. Under IR that usually means "
              "too little light, too much gain, or the focus is not pinned. "
              "Run tools/focus_sweep.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
