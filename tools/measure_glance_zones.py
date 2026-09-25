#!/usr/bin/env python3
"""Measure the permitted-glance regions for a real cabin.

    python tools/measure_glance_zones.py --config config/laptop.yaml

The regions in config/default.yaml are reasonable guesses for a left-hand-drive
cabin and nothing more. Guessed angles are the wrong thing to quote a
false-positive rate against, so measure them in the rig you will actually
demonstrate: sit in the driving position, look at each target in turn, and hold
while this samples the head pose.

The angles are CALIBRATION-RELATIVE, so a calibration must already exist for
the driver doing the measuring. Run the app once and calibrate first; this tool
reads runs/calibration.json and refuses to guess without it. Recalibrate if the
seat or the mount moves, because every number here is an offset from the
forward pose recorded then.

Output is a YAML block ready to paste over features.head.permitted_regions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun.capture import open_source              # noqa: E402
from bamnun.features import Calibration, FeatureExtractor  # noqa: E402
from bamnun.landmarks import FaceLandmarker         # noqa: E402
from bamnun.session import load_config              # noqa: E402

# Ordered as a driver would naturally sweep them. "forward" is measured first
# as a control: it should come back near zero, and if it does not, the
# calibration on file does not match how the driver is sitting now.
TARGETS = [
    ("forward", "the road straight ahead"),
    ("rearview", "the rear-view mirror"),
    ("left_mirror", "the driver-side mirror"),
    ("right_mirror", "the passenger-side mirror"),
    ("cluster", "the instrument cluster / speedometer"),
]


def _sample(source, landmarker, features, seconds: float) -> list[tuple[float, float]]:
    """Collect (yaw, pitch) for a few seconds, skipping untracked frames."""
    got: list[tuple[float, float]] = []
    t_end = time.monotonic() + seconds
    for frame in source:
        ff = features.update(frame.timestamp, landmarker.process(frame))
        if ff.face_found and ff.pose_valid:
            got.append((ff.yaw, ff.pitch))
        if time.monotonic() >= t_end:
            break
    return got


def _span(vals: list[float], pad: float) -> tuple[float, float]:
    """A window around the samples, padded, ignoring the tails.

    The 10th/90th percentiles rather than min/max: the driver's eyes reach the
    target before their head settles, so the first and last frames of a hold
    are transients that would otherwise widen every region.
    """
    vals = sorted(vals)
    lo = vals[int(0.10 * (len(vals) - 1))]
    hi = vals[int(0.90 * (len(vals) - 1))]
    return (round(lo - pad, 1), round(hi + pad, 1))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None, help="YAML merged over the default")
    p.add_argument("--hold", type=float, default=4.0, help="seconds to sample per target")
    p.add_argument("--pad", type=float, default=8.0,
                   help="degrees of margin added around each measured window")
    p.add_argument("--dwell", type=float, default=3.0,
                   help="dwell_s written for every measured region")
    args = p.parse_args(argv)

    cfg = load_config(args.config)

    cal_path = ROOT / str(cfg["calibration"].get("save_path", "runs/calibration.json"))
    if not cal_path.exists():
        print(f"no calibration at {cal_path}\n\n"
              "The regions are offsets from this driver's forward pose, so a\n"
              "calibration must exist first. Run the app, press 'c', then retry:\n"
              "  python -m bamnun.app --config config/laptop.yaml",
              file=sys.stderr)
        return 1

    features = FeatureExtractor(cfg["features"], cfg["calibration"])
    features.set_calibration(Calibration.from_dict(json.loads(cal_path.read_text())))
    source = open_source(cfg["capture"])
    landmarker = FaceLandmarker(cfg["landmarks"], repo_root=ROOT)

    print(f"calibration: {cal_path}")
    print(f"sampling {args.hold:.0f}s per target, {args.pad:.0f} deg of padding\n")

    measured: dict[str, dict] = {}
    for name, description in TARGETS:
        input(f"  look at {description:38} and press Enter, then HOLD ... ")
        samples = _sample(source, landmarker, features, args.hold)
        if len(samples) < 10:
            print(f"    only {len(samples)} tracked frames; skipping {name}. "
                  f"The face is probably out of view at this angle.\n")
            continue
        yaw = [s[0] for s in samples]
        pitch = [s[1] for s in samples]
        measured[name] = {"yaw": _span(yaw, args.pad), "pitch": _span(pitch, args.pad),
                          "n": len(samples),
                          "median": (statistics.median(yaw), statistics.median(pitch))}
        my, mp = measured[name]["median"]
        print(f"    {len(samples):3d} frames   median yaw {my:+6.1f}  pitch {mp:+6.1f}\n")

    if "forward" in measured:
        my, mp = measured["forward"]["median"]
        if abs(my) > 10.0 or abs(mp) > 10.0:
            print(f"WARNING: forward measured at yaw {my:+.1f} pitch {mp:+.1f}, not ~0.\n"
                  f"         The calibration on file does not match how you are\n"
                  f"         sitting now. Recalibrate before trusting the rest.\n")

    print("\n# paste over features.head.permitted_regions in your config:")
    print("    permitted_regions:")
    for name, _ in TARGETS:
        if name == "forward" or name not in measured:
            continue
        m = measured[name]
        print(f"      - {{name: {name}, yaw: [{m['yaw'][0]}, {m['yaw'][1]}], "
              f"pitch: [{m['pitch'][0]}, {m['pitch'][1]}], dwell_s: {args.dwell}}}")

    if "cluster" in measured:
        print("\n# NOTE: the cluster window overlaps the phone-in-lap pose this\n"
              "# system exists to catch. Check it against a real phone glance\n"
              "# before enabling it, and leave it commented out if they collide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
