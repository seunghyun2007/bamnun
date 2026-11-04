#!/usr/bin/env python3
"""Run the real drowsiness pipeline over a recorded session, to tune thresholds.

    python tools/replay_session.py runs/recordings/20261104-190000
    python tools/replay_session.py REC --set state.weights.perclos=0.25 --plot
    python tools/evaluate_detection.py --recordings runs/recordings

The first run finds the face in every frame (MediaPipe, the slow part) and
caches each frame's measurements in REC/measures.npz: both eyes, the
blendshapes, head pose, face size and brightness. Every run after that only
re-runs the features, the score and the ladder, so trying a threshold takes
about a second.

Calibration: a recording made with ``tools/record_session.py --script``
contains its own look-ahead (``calibrate_look``) and eyes-closed
(``calibrate_closed``) stretches, used exactly like the guided calibration.
Otherwise the first --calibrate-s seconds are the look-ahead step and the
closed level is estimated, like the device's start-up calibration.

Writes REC/replay.csv (one row per frame: every signal, the raw and smoothed
score, the level, the label, the ladder stage) and prints a summary for each
marked stretch. With --recordings, tools/evaluate_detection.py scores the
labelled stretches of every recording like the simulator's cases.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun.alerts import EscalationPolicy  # noqa: E402
from bamnun.eyes import EyeInputs, face_brightness  # noqa: E402
from bamnun.features import (Calibration, FeatureExtractor, HeadPose,  # noqa: E402
                             both_eye_ear, gaze_offset, interocular_px,
                             mouth_aspect_ratio, solve_head_pose)
from bamnun.session import deep_update, load_config, repo_root  # noqa: E402
from bamnun.state import COMPONENTS, StateEstimator  # noqa: E402

CACHE_VERSION = 2
POSE = ("t", "face", "mar", "yaw", "pitch", "roll", "pose_valid", "gaze_h", "gaze_v", "gaze_valid", "iod")
EYES = ("ear_l", "ear_r", "width_l", "width_r", "edge_l", "edge_r", "edge", "blink_l", "blink_r",
        "squint_l", "squint_r", "jaw", "smile", "cheek", "mouth_width", "brightness", "iod_frac")
FIELDS = POSE + EYES

# Labels from tools/record_session.py and what a correct detector does there.
DROWSY_LABELS = {"slow_blinks", "heavy_eyelids", "head_nods", "head_nod", "microsleep", "drowsy"}
QUIET_LABELS = {"normal", "alert", "talking", "smiling", "laughing", "slight_squint", "mirror_glances",
                "dashboard_glances", "phone_glances", "looking_down", "head_turns", "yawning",
                "glasses_glare", "lighting_change", "face_partly_out", "one_eye_hidden"}


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
    lm_cfg = dict(cfg["landmarks"], output_blendshapes=True)
    lm = FaceLandmarker(lm_cfg, repo_root=repo_root())
    rows, i = [], 0
    nan = float("nan")
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = times[i] if i < len(times) else i / fps
        res = lm.process(Frame(image=img, timestamp=t, index=i))
        if res is None or not res.ok:
            rows.append((t, 0) + (0,) * (len(POSE) - 2) + (nan,) * len(EYES))
        else:
            pts = res.points
            er, el = both_eye_ear(pts)
            pose = solve_head_pose(pts, res.image_size)
            g = gaze_offset(pts)
            iod = interocular_px(pts)
            x = EyeInputs.from_landmarks(res, ear_r=er, ear_l=el, iod=iod,
                                         brightness=face_brightness(img, pts))
            rows.append((t, 1, mouth_aspect_ratio(pts), pose.yaw, pose.pitch, pose.roll,
                         int(pose.valid), g[0], g[1], int(g[2]), iod)
                        + tuple(nan if getattr(x, k) is None else float(getattr(x, k)) for k in EYES))
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
            if "version" in z and int(z["version"]) == CACHE_VERSION:
                return {k: z[k] for k in FIELDS}
        print("old measurement cache: measuring again with blendshapes", flush=True)
    print("finding the face in every frame (cached for next time)...", flush=True)
    m = measure_video(rec, cfg)
    np.savez_compressed(cache, version=CACHE_VERSION, **m)
    return m


def _inputs(m: dict[str, np.ndarray], i: int) -> EyeInputs:
    def v(k):
        x = float(m[k][i])
        return None if np.isnan(x) else x
    return EyeInputs(
        ear_l=v("ear_l") or 0.0, ear_r=v("ear_r") or 0.0,
        width_l=v("width_l") or 1.0, width_r=v("width_r") or 1.0,
        edge_l=bool(v("edge_l")), edge_r=bool(v("edge_r")), edge=bool(v("edge")),
        blink_l=v("blink_l"), blink_r=v("blink_r"), squint_l=v("squint_l"), squint_r=v("squint_r"),
        jaw=v("jaw"), smile=v("smile"), cheek=v("cheek"), mouth_width=v("mouth_width") or 0.0,
        brightness=v("brightness"), iod_frac=v("iod_frac"),
    )


# -- replaying (fast) -------------------------------------------------------- #

def _stretch(markers, label) -> Optional[tuple[float, float]]:
    for i, (t, lab) in enumerate(markers):
        if lab == label:
            end = markers[i + 1][0] if i + 1 < len(markers) else t + 1e9
            return t, end
    return None


def replay(m: dict[str, np.ndarray], cfg: dict, calibration: Optional[Calibration] = None,
           calibrate_s: float = 12.0, markers: Optional[list] = None) -> list[dict]:
    """The device's pipeline over cached measurements. One dict per frame."""
    fx = FeatureExtractor(cfg["features"], cfg["calibration"])
    est = StateEstimator(cfg["state"])
    alerts = {**cfg["alerts"], "actuators": {k: {**v, "type": "null"} for k, v in cfg["alerts"]["actuators"].items()}}
    policy = EscalationPolicy(alerts)
    n = len(m["t"])
    if n == 0:
        return []
    markers = markers or []
    look = _stretch(markers, "calibrate_look")
    closed = _stretch(markers, "calibrate_closed")
    if calibration is not None:
        fx.set_calibration(calibration)
    else:
        t0 = look[0] if look else float(m["t"][0])
        if not look:
            # A recording without a guided look-ahead stretch wasn't made to
            # calibrate on; accept more head movement than the device would.
            fx.calibrator.max_steady = max(fx.calibrator.max_steady, 15.0)
        fx.calibrator.duration_s = (look[1] - look[0] - 0.2) if look else calibrate_s
        fx.calibrator.max_duration_s = fx.calibrator.duration_s + 10.0
        fx.start_calibration(t0)
    out = []
    closing = False
    for i in range(n):
        t = float(m["t"][i])
        in_closed = closed is not None and closed[0] <= t < closed[1]
        if in_closed and not closing and fx.calibration.complete:
            fx.start_closed(t)
            closing = True
        if closing and not in_closed:
            fx.finish_closed()
            closing = False
        if look and t < look[0] and calibration is None:
            continue
        if not m["face"][i]:
            ff = fx.no_face(t)
        else:
            pose = HeadPose(float(m["yaw"][i]), float(m["pitch"][i]), float(m["roll"][i]), bool(m["pose_valid"][i]))
            x = _inputs(m, i)
            ff = fx.measure(t, max(x.ear_l, x.ear_r), float(m["mar"][i]), pose,
                            (float(m["gaze_h"][i]), float(m["gaze_v"][i]), bool(m["gaze_valid"][i])),
                            float(m["iod"][i]), extra=x)
        if fx.calibrating or closing or not fx.calibration.complete:
            out.append({"t": round(t, 3), "face": int(bool(m["face"][i])), "calibrating": 1})
            continue
        st = est.update(ff, calibrated=True)
        d = policy.update(st)
        row = {"t": round(t, 3), "face": int(ff.face_found), "calibrating": 0,
               "openness": round(ff.ear_norm, 3), "typical": round(ff.openness, 3),
               "reliable": int(ff.reliable), "unreliable": ff.unreliable,
               "microsleep": int(ff.microsleep_now), "head_drop": int(ff.head_drop),
               "raw_score": round(100 * st.raw_score, 1), "score": round(100 * st.score, 1),
               "level": st.level, "level_name": st.level_name, "label": st.label, "stage": d.stage}
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
        labels: dict[str, int] = {}
        for r in part:
            labels[r["label"]] = labels.get(r["label"], 0) + 1
        res.append({"stretch": label, "from_s": round(a), "to_s": round(min(b, part[-1]["t"])),
                    "mean_score": round(float(np.mean(sc)), 1), "max_score": round(float(np.max(sc)), 1),
                    "end_score": round(sc[-1], 1), "max_stage": max(r["stage"] for r in part),
                    "microsleeps": sum(1 for x, y in zip(part, part[1:]) if y["microsleep"] and not x["microsleep"]),
                    "labels": ", ".join(f"{k} {100 * v / len(part):.0f}%" for k, v in
                                        sorted(labels.items(), key=lambda kv: -kv[1]))})
    return res


def read_markers(rec: Path) -> list[tuple[float, str]]:
    mp = rec / "markers.csv"
    if not mp.exists():
        return []
    with open(mp, encoding="utf-8") as f:
        return [(float(r["t"]), r["label"]) for r in csv.DictReader(f)]


def evaluate_recordings(folder: Path, cfg: dict) -> list[dict]:
    """Score labelled stretches of every recording like simulator cases."""
    from bamnun.evaluation import CaseResult
    results = []
    for rec in sorted(p for p in folder.iterdir() if (p / "video.mp4").exists()):
        markers = read_markers(rec)
        if not markers:
            continue
        rows = replay(load_measures(rec, cfg), cfg, markers=markers)
        top = len(cfg["alerts"]["stages"]) - 1
        for label, a, b in segments(rows, markers):
            part = [r for r in rows if a <= r["t"] < b and not r.get("calibrating")]
            if not part or label.startswith("calibrate"):
                continue
            drowsy = label in DROWSY_LABELS
            if not drowsy and label not in QUIET_LABELS:
                continue
            r = CaseResult(f"rec:{label}", rec.name, drowsy, body_h=max(1e-9, (b - a) / 3600))
            sc = sorted(x["score"] for x in part)
            r.rest_score = sc[len(sc) // 2]
            r.p90_score = sc[int(len(sc) * 0.9)]
            r.time_flagged = sum(1 for x in part if x["level"] >= 1) / len(part)
            if drowsy:
                r.events = 1
                hit = next((x for x in part if (x["stage"] >= top if label == "microsleep" else x["level"] >= 1)), None)
                if hit is not None:
                    r.caught = 1
                    r.latencies.append(hit["t"] - a)
            else:
                prev = 0
                for x in part:
                    if prev == 0 and x["stage"] >= 1:
                        r.false_alarms += 1
                    prev = x["stage"]
            results.append(r)
    if not results:
        return []
    from bamnun.evaluation import summarise
    return summarise(results)


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
                    help="override one setting, e.g. state.weights.perclos=0.25 (repeatable)")
    ap.add_argument("--calibration", default=None, help="use this calibration JSON instead")
    ap.add_argument("--calibrate-s", type=float, default=15.0)
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
    markers = read_markers(rec)
    rows = replay(m, cfg, cal, args.calibrate_s, markers)
    out = Path(args.out) if args.out else rec / "replay.csv"
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k.startswith(("sig_", "pts_")), k))
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    faces = float(np.mean(m["face"])) if len(m["face"]) else 0.0
    print(f"{len(rows)} frames, face found in {100 * faces:.0f}%  ->  {out}")
    print(f"{'stretch':18s} {'time':>11s} {'mean':>5s} {'max':>5s} {'end':>5s} {'stage':>5s} {'micro':>5s}  labels")
    for s in summary(rows, markers):
        print(f"{s['stretch']:18s} {s['from_s']:>4}-{s['to_s']:<4}s {s['mean_score']:5.0f} {s['max_score']:5.0f} "
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
        ax.set_ylim(0, 100)
        ax.set_xlabel("s")
        ax.legend()
        fig.tight_layout()
        fig.savefig(rec / "replay.png", dpi=110)
        print(f"plot -> {rec / 'replay.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
