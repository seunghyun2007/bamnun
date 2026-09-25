#!/usr/bin/env python3
"""Find the IMX708 lens position that maximises sharpness at driving distance.

    python tools/focus_sweep.py --min 2.0 --max 8.0 --steps 25

Run this BEFORE anything else on the Pi, and put the winning value into
``capture.picamera.lens_position`` in the config.

Why it matters more than it sounds. Camera Module 3 is a voice-coil autofocus
module. Left on auto at 50 cm in a low-contrast IR scene it hunts, and every
hunt cycle changes the apparent size of the eyelid aperture, which the EAR
reads as a slow blink. Pinning the focus removes an entire class of false
positive. The config ships with AfMode=0 for that reason; this tool tells you
what to pin it to.

Sharpness is the variance of the Laplacian over the central crop, which is the
standard cheap focus measure. Also reports mean brightness and the fraction of
saturated pixels, because under IR illumination the useful failure is usually
not blur but a blown-out forehead.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def sharpness(gray: np.ndarray) -> float:
    import cv2

    h, w = gray.shape[:2]
    crop = gray[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    return float(cv2.Laplacian(crop, cv2.CV_64F).var())


def main() -> int:
    import cv2

    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=1.0, help="min lens position, dioptres")
    ap.add_argument("--max", type=float, default=10.0)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--settle", type=float, default=0.45, help="seconds per step")
    ap.add_argument("--exposure", type=int, default=8000, help="microseconds")
    ap.add_argument("--gain", type=float, default=4.0)
    ap.add_argument("--save", default="runs/focus_sweep.csv")
    args = ap.parse_args()

    from bamnun.capture import PiCameraSource

    cfg = {
        "source": "picamera", "fps": 30, "grayscale_input": False,
        "picamera": {
            "sensor_mode_size": [1536, 864],
            "lock_exposure": True, "exposure_time_us": args.exposure,
            "analogue_gain": args.gain, "lock_awb": True,
            "manual_focus": True, "lens_position": args.min,
            "noise_reduction": "off",   # NR inflates the Laplacian variance
        },
    }

    print("Point the camera at the driver's seat, from the mounting position "
          "you intend to use.\nHold still.\n")
    src = PiCameraSource(cfg)
    rows = []
    try:
        positions = np.linspace(args.min, args.max, args.steps)
        print(f"{'lens':>6} {'sharpness':>11} {'mean':>7} {'sat%':>6}")
        for lp in positions:
            src.set_lens_position(float(lp))
            time.sleep(args.settle)
            frame = src.read()
            if frame is None:
                break
            img = frame.image
            gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            s = sharpness(gray)
            mean = float(gray.mean())
            sat = float((gray >= 250).mean() * 100.0)
            rows.append((float(lp), s, mean, sat))
            print(f"{lp:6.2f} {s:11.1f} {mean:7.1f} {sat:6.2f}")
    finally:
        src.close()

    if not rows:
        print("no frames captured", file=sys.stderr)
        return 1

    best = max(rows, key=lambda r: r[1])
    out = Path(__file__).resolve().parents[1] / args.save
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("lens_position,sharpness,mean_brightness,saturated_pct\n")
        for r in rows:
            fh.write(f"{r[0]:.4f},{r[1]:.4f},{r[2]:.3f},{r[3]:.4f}\n")

    print(f"\nsharpest at lens_position = {best[0]:.2f} (approx "
          f"{100.0/max(best[0], 1e-6):.0f} cm)")
    print(f"put that into config: capture.picamera.lens_position: {best[0]:.2f}")
    if best[3] > 1.0:
        print(f"WARNING: {best[3]:.1f}% of pixels saturated at the best focus. "
              "Reduce exposure or move the IR emitters back.")
    if best[2] < 40:
        print(f"WARNING: mean brightness only {best[2]:.0f}. Add IR light or "
              "raise gain; do not raise exposure past ~12 ms or head motion "
              "will smear the eyelids.")
    print(f"csv: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
