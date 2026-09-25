#!/usr/bin/env python3
"""Fetch the MediaPipe Face Landmarker bundle into models/.

    python tools/download_models.py

The 'face_landmarker_v2_with_blendshapes' bundle is the one that includes iris
refinement (478 landmarks rather than 468) and the blendshape head. It is
about 3.7 MB.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
DEST = MODELS / "face_landmarker.task"


def main() -> int:
    MODELS.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and DEST.stat().st_size > 1_000_000:
        print(f"already present: {DEST} ({DEST.stat().st_size/1e6:.1f} MB)")
        return 0

    print(f"downloading {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=60) as resp, open(DEST, "wb") as fh:
            total = 0
            while chunk := resp.read(1 << 16):
                fh.write(chunk)
                total += len(chunk)
                print(f"\r  {total/1e6:5.1f} MB", end="", flush=True)
        print()
    except Exception as exc:  # noqa: BLE001
        print(f"\ndownload failed: {exc}", file=sys.stderr)
        print(
            "\nIf this machine has no route to storage.googleapis.com, download the\n"
            "file on another machine and copy it to:\n"
            f"  {DEST}\n",
            file=sys.stderr,
        )
        return 1

    digest = hashlib.sha256(DEST.read_bytes()).hexdigest()[:16]
    print(f"saved {DEST} ({DEST.stat().st_size/1e6:.1f} MB, sha256:{digest}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
