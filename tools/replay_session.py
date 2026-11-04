#!/usr/bin/env python3
"""Run the real drowsiness pipeline over a recorded session, to tune thresholds.

    python tools/replay_session.py runs/recordings/20261104-190000
    python tools/replay_session.py REC --set state.weights.squint=0.35 --set features.ear_shut_fraction=0.35
    python tools/replay_session.py REC --config my_tuning.yaml --plot

The first run finds the face in every frame (MediaPipe, the slow part) and
caches the measurements in REC/measures.npz. Every run after that only re-runs
the features, the score and the ladder, so trying a threshold takes seconds.

Calibration: the first --calibrate-s seconds (default 12) are used as this
session's calibration, exactly like the device does at start-up, unless you
pass --calibration runs/calibration.json.

Writes REC/replay.csv (one row per frame: every signal, the raw and smoothed
score, the level, the label and the ladder stage) and prints a summary for
each marked stretch from markers.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun.alerts import EscalationPolicy  # noqa: E402
from bamnun.features import (Calibration, FeatureExtractor, FeatureFrame, HeadPose,  # noqa: E402
                             both_eye_ear, gaze_offset, interocular_px,
                             mouth_aspect_ratio, solve_head_pose)
from bamnun.session import deep_update, load_config, repo_root  # noqa: E402
from bamnun.state import COMPONENTS, StateEstimator  # noqa: E402

FIELDS = ("t", "face", "ear_raw", "mar", "yaw", "pitch", "roll", "pose_valid",
          "gaze_h", "gaze_v", "gaze_valid", "iod")


# -- measuring (slow, cached) ------------------------------------------------ #

def measure_video(rec: Path, cfg: dict) -> dict[str, np.ndarray]:
    import cv2

    from bamnun.capture import Frame
    from bamnun.landmarks import FaceLandmarker

    times = []
    fpath = rec / "frames.csv"
    if fpath.exists():
        with open(fpath, encoding="utf-8") as f:
            times = [float(r["t"]) for r in csv.DictReader(f)]
    cap = cv2.VideoCapture(str(rec / "video.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    lm = FaceLandmarker(cfg["landmarks"], repo_root=repo_root())
    rows, i = [], 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = times[i] if i < len(times) else i / fps
        res = lm.process(Frame(image=img, timestamp=t, index=i))
        if res is None or not res.ok:
            rows.append((t, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        else:
            pts = res.points
            er, el = both_eye_ear(pts)
            pose = solve_head_pose(pts, res.image_size)
            g = gaze_offset(pts)
            rows.append((t, 1, max(er, el), mouth_aspect_ratio(pts), pose.yaw, pose.pitch,
                         pose.roll, int(pose.valid), g[0], g[1], int(g[2]), interocular_px(pts)))
        i += 1
        if i % 300 == 0:
            print(f"  measured {i} frames", flush=True)
    cap.release()
    lm.close()
    arr = np.array(rows, dtype=np.float64).reshape(-1, len(FIELDS))
    return {k: arr[:, j] for j, k in enumerate(FIELDS)}


def load_measures(rec: Path, cfg: dict, refresh: bool = False) -> dict[str, np.ndarray]:
    cache = rec / "measures.npz"
    if cache.exists() and not refresh:
        with np.load(cache) as z:
            return {k: z[k] for k in FIELDS}
    print("finding the face in every frame (cached for next time)...", flush=True)
    m = measure_video(rec, cfg)
    np.savez_compressed(cache, **m)
    return m


# -- replaying (fast) -------------------------------------------------------- #

def replay(m: dict[str, np.ndarray], cfg: dict, calibration: Calibration | None = None,
           calibrate_s: float = 12.0) -> list[dict]:
    """The device's pipeline over cached measurements. One dict per frame."""
    fx = FeatureExtractor(cfg["features"], cfg["calibration"])
    est = StateEstimator(cfg["state"])
    alerts = cfg["alerts"]
    for spec in alerts["actuators"].values():
        spec["type"] = "null"
    policy = EscalationPolicy(alerts)
    n = len(m["t"])
    if n == 0:
        return []
    if calibration is not None:
        fx.set_calibration(calibration)
    else:
        fx.calibrator.duration_s = calibrate_s
        fx.start_calibration(float(m["t"][0]))
    out = []
    for i in range(n):
        t = float(m["t"][i])
        if not m["face"][i]:
            ff = FeatureFrame(t=t, face_found=False)
        else:
            pose = HeadPose(float(m["yaw"][i]), float(m["pitch"][i]), float(m["roll"][i]), bool(m["pose_valid"][i]))
            ff = fx.measure(t, float(m["ear_raw"][i]), float(m["mar"][i]), pose,
                            (float(m["gaze_h"][i]), float(m["gaze_v"][i]), bool(m["gaze_valid"][i])),
                            float(m["iod"][i]))
        if fx.calibrating:
            out.append({"t": t, "face": int(ff.face_found), "calibrating": 1})
            continue
        st = est.update(ff, calibrated=fx.calibration.complete)
        d = policy.update(st)
        row = {"t": round(t, 3), "face": int(ff.face_found), "calibrating": 0,
               "ear_norm": round(ff.ear_norm, 3), "openness": round(ff.openness, 3),
               "looking_down": int(ff.looking_down), "microsleep": int(ff.microsleep_now),
               "raw_score": round(100 * st.raw_score, 1), "score": round(100 * st.score, 1),
               "level": st.level_name, "label": st.label, "stage": d.stage}
        for k in COMPONENTS:
            row[f"sig_{k}"] = round(st.signals.get(k, 0.0), 4)
            row[f"pts_{k}"] = round(100 * st.contributions.get(k, 0.0), 2)
        out.append(row)
    return out


def segments(rows: list[dict], markers: list[tuple[float, str]]) -> list[tuple[str, float, float]]:
    out = []
    for i, (t, label) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else (rows[-1]["t"] if rows else t)
        if label:
            out.append((label, t, end))
    return out


def summary(rows: list[dict], markers: list[tuple[float, str]]) -> list[dict]:
    res = []
    scored = [r for r in rows if not r.get("calibrating")]
    for label, a, b in segments(rows, markers) or [("whole session", 0.0, float("inf"))]:
        part = [r for r in scored if a <= r["t"] < b]
        if not part:
            continue
        sc = [r["score"] for r in part]
        labels = {}
        for r in part:
            labels[r["label"]] = labels.get(r["label"], 0) + 1
        res.append({"stretch": label, "from_s": round(a), "to_s": round(min(b, part[-1]["t"])),
                    "mean_score": round(float(np.mean(sc)), 1), "max_score": round(float(np.max(sc)), 1),
                    "end_score": round(sc[-1], 1), "max_stage": max(r["stage"] for r in part),
                    "microsleeps": sum(1 for x, y in zip(part, part[1:]) if y["microsleep"] and not x["microsleep"]),
                    "labels": ", ".join(f"{k} {100 * v / len(part):.0f}%" for k, v in sorted(labels.items(), key=lambda kv: -kv[1]))})
    return res


def parse_set(items: list[str]) -> dict:
    """``a.b.c=1.5`` -> {"a": {"b": {"c": 1.5}}}"""
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
    ap.add_argument("recording", help="a folder from tools/record_session.py")
    ap.add_argument("--config", default=None, help="extra YAML merged over the default")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override one setting, e.g. state.weights.squint=0.35 (repeatable)")
    ap.add_argument("--calibration", default=None, help="use this calibration JSON instead of the first seconds")
    ap.add_argument("--calibrate-s", type=float, default=12.0)
    ap.add_argument("--refresh", action="store_true", help="re-measure the video (ignore the cache)")
    ap.add_argument("--out", default=None, help="CSV to write (default REC/replay.csv)")
    ap.add_argument("--plot", action="store_true", help="also write REC/replay.png (needs matplotlib)")
    args = ap.parse_args(argv)

    rec = Path(args.recording)
    cfg = load_config(args.config)
    if args.set:
        cfg = deep_update(cfg, parse_set(args.set))
    m = load_measures(rec, cfg, refresh=args.refresh)
    cal = None
    if args.calibration:
        cal = Calibration.from_dict(json.loads(Path(args.calibration).read_text(encoding="utf-8")))
    rows = replay(m, cfg, cal, args.calibrate_s)
    markers = []
    mp = rec / "markers.csv"
    if mp.exists():
        with open(mp, encoding="utf-8") as f:
            markers = [(float(r["t"]), r["label"]) for r in csv.DictReader(f)]
    out = Path(args.out) if args.out else rec / "replay.csv"
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k.startswith(("sig_", "pts_")), k))
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    faces = float(np.mean(m["face"])) if len(m["face"]) else 0.0
    print(f"{len(rows)} frames, face found in {100 * faces:.0f}%  ->  {out}")
    print(f"{'stretch':16s} {'time':>11s} {'mean':>5s} {'max':>5s} {'end':>5s} {'stage':>5s} {'micro':>5s}  labels")
    for s in summary(rows, markers):
        print(f"{s['stretch']:16s} {s['from_s']:>4}-{s['to_s']:<4}s {s['mean_score']:5.0f} {s['max_score']:5.0f} "
              f"{s['end_score']:5.0f} {s['max_stage']:5d} {s['microsleeps']:5d}  {s['labels']}")
    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("--plot needs matplotlib: pip install matplotlib")
            return 0
        sc = [r for r in rows if not r.get("calibrating")]
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot([r["t"] for r in sc], [r["score"] for r in sc], label="score")
        ax.plot([r["t"] for r in sc], [r["raw_score"] for r in sc], alpha=.4, label="raw")
        for lv in cfg["state"]["levels"][1:]:
            ax.axhline(100 * float(lv["min_score"]), ls=":", c="grey")
        for label, a, b in segments(rows, markers):
            ax.axvspan(a, b, alpha=.08)
            ax.text(a, 98, label, fontsize=8, va="top")
        ax.set_ylim(0, 100); ax.set_xlabel("s"); ax.legend()
        fig.tight_layout(); fig.savefig(rec / "replay.png", dpi=110)
        print(f"plot -> {rec / 'replay.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
