#!/usr/bin/env python3
"""Record a labelled webcam session for evaluating and tuning detection.

    python tools/record_session.py                 # the 10-minute test script, with prompts
    python tools/record_session.py --free --seconds 300

Writes a folder under runs/recordings/<date-time>/:

    video.mp4       the camera, as seen by the detector (no overlay)
    frames.csv      frame number and timestamp, so replay keeps real timing
    markers.csv     what you were doing when (time, label)
    meta.json       resolution, frame rate, start time

The test script (default) shows one instruction at a time on the preview and
labels each stretch for you: calibration (look ahead, eyes closed), then
every not-drowsy case (normal, talking, smiling, mirror/dashboard/phone
glances, shoulder checks, yawning) and every drowsy one (slow blinks, heavy
eyelids, nodding off, microsleeps). Free mode labels by key press:

    1 normal  2 talking  3 smiling  4 mirror glances  5 dashboard glances
    6 phone glances  7 head turns  8 yawning  9 slow blinks
    h heavy eyelids  n head nods  m microsleep  0 unlabelled  q stop

Then:
    python tools/replay_session.py runs/recordings/<time> --plot
    python tools/evaluate_detection.py --recordings runs/recordings

Video stays on this machine; runs/ is not in git.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun.capture import open_source  # noqa: E402
from bamnun.session import load_config  # noqa: E402

KEYS = {"1": "normal", "2": "talking", "3": "smiling", "4": "mirror_glances",
        "5": "dashboard_glances", "6": "phone_glances", "7": "head_turns", "8": "yawning",
        "9": "slow_blinks", "h": "heavy_eyelids", "n": "head_nods", "m": "microsleep", "0": ""}

# The 10-minute test script: (seconds, label, what to do). The labels are the
# ones tools/evaluate_detection.py --recordings understands.
GUIDE = [
    (20, "calibrate_look", "Look straight at the camera and blink normally"),
    (5, "calibrate_closed", "Close your eyes and keep them closed"),
    (5, "settle", "Open your eyes and look ahead"),
    (60, "normal", "Drive normally: look ahead, blink as usual"),
    (40, "talking", "Talk out loud: count, or describe the road"),
    (30, "smiling", "Smile, and laugh at something"),
    (40, "mirror_glances", "Check your mirrors every few seconds"),
    (40, "dashboard_glances", "Glance down at the dashboard for 1-2 s now and then"),
    (30, "phone_glances", "Look down at a phone in your lap for 2-3 s, then back"),
    (30, "head_turns", "Shoulder checks: turn your head fully, then back"),
    (40, "yawning", "Yawn two or three times"),
    (30, "normal", "Back to normal driving"),
    (60, "slow_blinks", "Blink SLOWLY: about half a second shut, every 3 s"),
    (60, "heavy_eyelids", "Let your eyelids droop, as if very tired"),
    (60, "head_nods", "Nod off: let your head sink slowly, then jerk it back up"),
    (30, "microsleep", "Close your eyes for 1-2 s, a few times"),
    (20, "normal", "Look ahead. Almost done"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--free", action="store_true", help="no prompts; mark with number keys")
    ap.add_argument("--seconds", type=float, default=None, help="free mode: stop after this long")
    ap.add_argument("--device", default=None, help="webcam index")
    ap.add_argument("--out", default=None, help="folder to write (default runs/recordings/<time>)")
    ap.add_argument("--no-preview", action="store_true", help="free mode only: record without a window")
    args = ap.parse_args(argv)

    import cv2

    ov = {"capture": {"source": "webcam"}}
    if args.device is not None:
        ov["capture"]["device"] = int(args.device)
    cfg = load_config(None, ov)
    src = open_source(cfg["capture"])
    out = Path(args.out) if args.out else ROOT / "runs" / "recordings" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    first = src.read()
    if first is None:
        print("no picture from the webcam")
        return 1
    h, w = first.image.shape[:2]
    fps = float(cfg["capture"].get("fps", 30))
    writer = cv2.VideoWriter(str(out / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    frames = open(out / "frames.csv", "w", newline="", encoding="utf-8")
    fw = csv.writer(frames)
    fw.writerow(["frame", "t"])
    markers = open(out / "markers.csv", "w", newline="", encoding="utf-8")
    mw = csv.writer(markers)
    mw.writerow(["t", "label"])

    guided = not args.free
    plan, t_end = [], None
    if guided:
        acc = 0.0
        for dur, label, text in GUIDE:
            plan.append((acc, label, text))
            acc += dur
        t_end = acc
    elif args.seconds:
        t_end = args.seconds
    print(f"recording to {out}")
    print("guided session: follow the prompts in the window" if guided
          else "mark with keys 1-6, 0 to clear, q to stop")

    t0, n, current, step = first.timestamp, 0, None, -1
    frame = first
    show = guided or not args.no_preview
    try:
        while frame is not None:
            t = frame.timestamp - t0
            if t_end is not None and t >= t_end:
                break
            img = frame.image if frame.image.ndim == 3 else cv2.cvtColor(frame.image, cv2.COLOR_GRAY2BGR)
            writer.write(img)
            fw.writerow([n, f"{t:.4f}"])
            n += 1
            prompt = ""
            if guided:
                while step + 1 < len(plan) and t >= plan[step + 1][0]:
                    step += 1
                    mw.writerow([f"{t:.3f}", plan[step][1]])
                    markers.flush()
                    print(f"{t:6.1f}s  {plan[step][2]}")
                nxt = plan[step + 1][0] if step + 1 < len(plan) else t_end
                prompt = f"{plan[step][2]}   ({nxt - t:0.0f} s)"
            if show:
                view = img.copy()
                cv2.rectangle(view, (0, 0), (w, 48), (20, 14, 22), -1)
                cv2.putText(view, prompt or f"marker: {current or '-'}   (1-6 mark, q stop)",
                            (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 190, 250), 2, cv2.LINE_AA)
                cv2.putText(view, f"REC {t:5.1f}s", (w - 170, h - 18), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (60, 60, 240), 2, cv2.LINE_AA)
                cv2.imshow("bamnun recorder", cv2.resize(view, None, fx=0.75, fy=0.75))
                k = cv2.waitKey(1) & 0xFF
                if k == ord("q"):
                    break
                if not guided and k != 0xFF and chr(k).lower() in KEYS:
                    k = ord(chr(k).lower())
                    current = KEYS[chr(k)]
                    mw.writerow([f"{t:.3f}", current])
                    markers.flush()
            frame = src.read()
    except KeyboardInterrupt:
        pass
    finally:
        writer.release()
        frames.close()
        markers.close()
        src.close()
        try:
            cv2.destroyAllWindows()
        except Exception:  # noqa: BLE001
            pass
    el = max(1e-6, (frame.timestamp - t0) if frame is not None else n / fps)
    (out / "meta.json").write_text(json.dumps({
        "resolution": [w, h], "frames": n, "seconds": round(el, 2), "fps": round(n / el, 2),
        "started": datetime.now().isoformat(timespec="seconds"), "guided": guided,
    }, indent=2), encoding="utf-8")
    print(f"saved {n} frames ({n / el:.1f} fps) to {out}")
    print(f"next: python tools/replay_session.py {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
