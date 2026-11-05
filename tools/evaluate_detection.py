#!/usr/bin/env python3
"""Evaluate drowsiness detection on every scenario (and labelled recordings).

    python tools/evaluate_detection.py                 # all cases x 4 eye types, ~3 min each
    python tools/evaluate_detection.py --quick         # what the test suite runs
    python tools/evaluate_detection.py --json out.json --set state.weights.perclos=0.3
    python tools/evaluate_detection.py --recordings runs/recordings

Prints a Markdown table (detection rate, false alarms per hour, reaction
time, resting score) that goes straight into docs/detection-audit.md.
See src/bamnun/evaluation.py for what each column means.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from bamnun import scenarios  # noqa: E402
from bamnun.evaluation import evaluate, summarise, table  # noqa: E402
from bamnun.session import deep_update, load_config  # noqa: E402


def parse_set(items):
    out: dict = {}
    for it in items:
        key, _, val = it.partition("=")
        try:
            v = json.loads(val)
        except ValueError:
            v = val
        d = out
        parts = key.split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = v
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="one eye type per case, shorter bodies")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--body", type=float, default=180.0, help="seconds per case after calibration")
    ap.add_argument("--only", action="append", default=[], help="just these cases")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--config", default=None)
    ap.add_argument("--json", default=None, help="also write the rows here")
    ap.add_argument("--recordings", default=None, help="also evaluate labelled recordings in this folder")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.set:
        cfg = deep_update(cfg, parse_set(args.set))
    t0 = time.time()
    if args.quick:
        cases = list(quick_cases())
    else:
        eyes = ("small", "medium", "large", "glasses")
        cases = [scenarios.build(n, e, s, 600.0 if n == "progressive" else args.body, fps)
                 for n in (args.only or scenarios.all_names()) for e in eyes
                 for fps in (30.0, 15.0) for s in range(1, args.seeds + 1)]
    rows = summarise(evaluate(cases, cfg))
    print(table(rows))
    hours = sum(c.body_s for c in cases) / 3600
    print(f"\n{len(cases)} runs, {hours:.1f} simulated hours, {time.time() - t0:.0f} s")
    if args.recordings:
        from replay_session import evaluate_recordings
        rec_rows = evaluate_recordings(Path(args.recordings), cfg)
        if rec_rows:
            print("\nRecordings:\n" + table(rec_rows))
            rows += rec_rows
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


def quick_cases():
    """Every case once, rotating through the eye types, shorter bodies."""
    eyes = ("medium", "small", "large", "glasses")
    for i, name in enumerate(scenarios.all_names()):
        for fps in (30.0, 15.0):
            yield scenarios.build(name, eyes[i % len(eyes)], seed=7,
                                  body_s=300.0 if name == "progressive" else 120.0, fps=fps)


if __name__ == "__main__":
    raise SystemExit(main())
