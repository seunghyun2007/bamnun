#!/usr/bin/env python3
"""Render the debug overlay in every driver state, as a contact sheet.

    python tools/render_overlay_demo.py --out runs/overlay_demo.png

Two uses. It shows what the exhibition demo actually looks like before any
hardware exists, so the layout can be argued about early. And it exercises
every branch of viz.py, which is otherwise the only module with no automated
coverage, against a synthetic face built the same way the test suite builds
one.

The background is a crude synthetic near-IR frame, not a real face. It is
there so the panel and banners can be judged against something; do not put
this image in the report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from bamnun.features import FeatureFrame            # noqa: E402
from bamnun.predictor import RestPlan               # noqa: E402
from bamnun.state import DriverState                # noqa: E402
from bamnun.viz import draw_overlay                 # noqa: E402
from bamnun.alerts import Actuation, AlertDecision  # noqa: E402

from test_integration import IMG_H, IMG_W, lm, synth_face  # noqa: E402


def ir_background(ear: float, yaw_deg: float) -> np.ndarray:
    """A rough monochrome stand-in for a NoIR frame: dark cabin, lit face."""
    import cv2

    img = np.full((IMG_H, IMG_W), 18, np.uint8)
    cx = int(IMG_W / 2 + yaw_deg * 2.2)
    cy = int(IMG_H / 2 + 6)

    # Head: a bright ellipse with a soft falloff, which is roughly what an
    # 850 nm flood at 50 cm gives you.
    head = np.zeros_like(img, dtype=np.float32)
    cv2.ellipse(head, (cx, cy), (118, 152), 0, 0, 360, 1.0, -1)
    head = cv2.GaussianBlur(head, (0, 0), 28)
    img = np.clip(img + head * 150, 0, 255).astype(np.uint8)

    # Eye sockets sit in shadow; that contrast is what the landmarks rely on.
    for dx in (-52, 52):
        cv2.ellipse(img, (cx + dx, cy - 34), (30, 16), 0, 0, 360, 55, -1)
    lid = max(2, int(16 * (1.0 - min(ear / 0.30, 1.0))))
    for dx in (-52, 52):
        cv2.ellipse(img, (cx + dx, cy - 34), (26, max(2, 13 - lid)), 0, 0, 360,
                    195, -1)
    cv2.ellipse(img, (cx, cy + 22), (16, 26), 0, 0, 360, 120, -1)      # nose
    cv2.ellipse(img, (cx, cy + 74), (38, 10), 0, 0, 360, 70, -1)       # mouth
    img = cv2.GaussianBlur(img, (5, 5), 0)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def plan_for(kind: str) -> RestPlan | None:
    if kind == "none":
        return None
    if kind == "pending":
        return RestPlan(valid=False, reason="need 120s of history, have 44s")
    if kind == "eta":
        return RestPlan(valid=True, reason="ok", current_score=0.38,
                        slope_per_min=0.021, time_to_unsafe_s=1380.0,
                        rest_at_s=1080.0, rest_duration_min=20,
                        confidence=0.71)
    return RestPlan(valid=True, reason="unsafe for 34% of the last 10 min",
                    current_score=0.72, slope_per_min=-0.004,
                    time_to_unsafe_s=0.0, recommend_rest_now=True,
                    rest_at_s=0.0, confidence=0.58, unsafe_fraction=0.34)


SCENES = [
    dict(label="1. calibrating", ear=0.30, yaw=0.0, calibrating=0.42,
         ff=dict(), st=dict(calibrated=False), plan="none", alert=None),

    dict(label="2. alert, on road", ear=0.30, yaw=0.0, calibrating=-1.0,
         ff=dict(ear_norm=1.0, perclos=0.02, blink_rate_per_min=16.0),
         st=dict(score=0.03, level=0, level_name="alert", kss=1.2,
                 confidence=0.98),
         plan="pending", alert=None),

    dict(label="3. mild, notify fired", ear=0.26, yaw=0.0, calibrating=-1.0,
         ff=dict(ear_norm=0.87, perclos=0.11, blink_rate_per_min=24.0,
                 mean_blink_duration_s=0.24, yawn_count=1),
         st=dict(score=0.41, level=1, level_name="mild", kss=4.3,
                 confidence=0.95),
         plan="eta",
         alert=("notify", ["chime"])),

    dict(label="4. drowsy, scent burst", ear=0.20, yaw=-4.0, calibrating=-1.0,
         ff=dict(ear_norm=0.66, perclos=0.19, blink_rate_per_min=11.0,
                 mean_blink_duration_s=0.37, microsleep_count=2, yawn_count=3,
                 pitch_std=7.4, nodding=True, pitch=-9.0),
         st=dict(score=0.62, level=2, level_name="drowsy", kss=6.0,
                 confidence=0.91),
         plan="now",
         alert=("rouse", ["chime", "scent"])),

    dict(label="5. microsleep, all stages", ear=0.03, yaw=2.0, calibrating=-1.0,
         ff=dict(ear_norm=0.10, eye_closed=True, ongoing_closure_s=1.7,
                 perclos=0.26, microsleep_count=4, mean_blink_duration_s=0.41,
                 pitch_std=8.1),
         st=dict(score=0.90, level=3, level_name="severe", kss=8.2,
                 microsleep_now=True, confidence=0.88),
         plan="now",
         alert=("shock", ["voice", "scent", "thermal"])),

    dict(label="6. eyes off road", ear=0.30, yaw=34.0, calibrating=-1.0,
         ff=dict(ear_norm=1.0, perclos=0.03, off_road=True,
                 off_road_glance_s=2.8, long_glance_count=1, yaw=34.0,
                 gaze_h=0.42),
         st=dict(score=0.05, level=0, level_name="alert", kss=1.4,
                 distracted=True, distraction_reason="head off-road 2.8s",
                 confidence=0.93),
         plan="eta",
         alert=("notify", ["chime"])),

    dict(label="7. driver not visible", ear=0.30, yaw=0.0, calibrating=-1.0,
         ff=dict(face_found=False),
         st=dict(score=0.0, level=1, level_name="mild", face_lost=True,
                 face_lost_s=3.4, distracted=True,
                 distraction_reason="driver not visible", confidence=0.0),
         plan="eta", alert=None, no_face=True),

    dict(label="8. recovered", ear=0.30, yaw=0.0, calibrating=-1.0,
         ff=dict(ear_norm=0.99, perclos=0.05, blink_rate_per_min=17.0,
                 mean_blink_duration_s=0.19),
         st=dict(score=0.12, level=0, level_name="alert", kss=2.0,
                 confidence=0.96),
         plan="eta", alert=None),
]


def build_scene(scene: dict, ui_cfg: dict):
    ear, yaw = scene["ear"], scene["yaw"]
    bg = ir_background(ear, yaw)
    no_face = scene.get("no_face", False)

    pts = synth_face(ear=ear, yaw_deg=yaw)
    landmarks = None if no_face else lm(pts, 0.0)

    ff_kw = dict(t=123.4, face_found=not no_face, pose_valid=not no_face,
                 gaze_valid=not no_face, interocular_px=0.0 if no_face else 118.0,
                 ear=ear, ear_raw=ear)
    ff_kw.update(scene["ff"])
    ff = FeatureFrame(**ff_kw)

    st_kw = dict(t=123.4, calibrated=True)
    st_kw.update(scene["st"])
    st = DriverState(**st_kw)

    alert = None
    if scene["alert"] is not None:
        stage_name, actuators = scene["alert"]
        alert = AlertDecision(
            t=123.4, stage=1, stage_name=stage_name, changed=True,
            fired=[Actuation(t=123.4, actuator=a, stage=stage_name)
                   for a in actuators],
        )

    return draw_overlay(bg, landmarks, ff, st, plan=plan_for(scene["plan"]),
                        alert=alert, ui_cfg=ui_cfg, fps=24.3,
                        calibrating=scene["calibrating"])


def main() -> int:
    import cv2

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/overlay_demo.png")
    ap.add_argument("--cols", type=int, default=2)
    ap.add_argument("--scale", type=float, default=0.72)
    args = ap.parse_args()

    ui_cfg = {"draw_eyes": True, "draw_gauges": True, "draw_mesh": False}

    tiles = []
    for scene in SCENES:
        canvas = build_scene(scene, ui_cfg)
        canvas = cv2.resize(canvas, None, fx=args.scale, fy=args.scale)
        h, w = canvas.shape[:2]
        tile = np.full((h + 30, w, 3), 8, np.uint8)
        tile[30:, :] = canvas
        cv2.putText(tile, scene["label"], (10, 21), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (235, 235, 235), 1, cv2.LINE_AA)
        tiles.append(tile)

    cols = max(1, args.cols)
    rows = []
    for i in range(0, len(tiles), cols):
        chunk = tiles[i:i + cols]
        while len(chunk) < cols:
            chunk.append(np.zeros_like(tiles[0]))
        rows.append(np.hstack(chunk))
    sheet = np.vstack(rows)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)
    print(f"wrote {out}  ({sheet.shape[1]}x{sheet.shape[0]}, "
          f"{len(SCENES)} states)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
