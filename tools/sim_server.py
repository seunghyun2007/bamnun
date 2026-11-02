#!/usr/bin/env python3
"""Serve the app with a simulated driver, for working on it without a camera.

    python tools/sim_server.py                     # an 8-minute drive, on repeat
    python tools/sim_server.py --minutes 4 --port 8000 --once

Then open http://localhost:8000 (or http://<this machine's address>:8000 from
a phone on the same Wi-Fi).

Same pipeline as ``python -m bamnun.app --serve`` from the state estimator
on: the real StateEstimator, EscalationPolicy, Hub and server. Only the
eyelid signal is synthetic, from tools/simulate.py, compressed so the driver
gets sleepy within the run. Each drive opens with a short calibration and
includes a few seconds with nobody in the seat, so every screen state shows.

Every actuator is replaced by a logging stub, so running this on the Pi
cannot fire the real mister, light or speakers.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bamnun.alerts import EscalationPolicy                 # noqa: E402
from bamnun.features import Calibration, FeatureExtractor, FeatureFrame  # noqa: E402
from bamnun.server import ServerThread                     # noqa: E402
from bamnun.session import load_config                     # noqa: E402
from bamnun.state import DriverState, StateEstimator       # noqa: E402
from bamnun.telemetry import Hub, alert_event, build_snapshot  # noqa: E402
from simulate import feature_frame, synth_ear_stream       # noqa: E402

FPS = 20.0
PUBLISH_PERIOD_S = 0.1


def drive(hub: Hub, minutes: float, calibrate_s: float, seed: int) -> None:
    cfg = load_config()
    for spec in cfg["alerts"]["actuators"].values():
        spec["type"] = "null"
    extractor = FeatureExtractor(cfg["features"], cfg["calibration"])
    extractor.set_calibration(Calibration(ear_open=0.30, ear_std=0.01,
                                          complete=True, n_samples=999))
    estimator = StateEstimator(cfg["state"])
    policy = EscalationPolicy(cfg["alerts"])
    total = minutes * 60.0
    away = (0.12 * total, 0.12 * total + 5.0)     # driver out of view for 5 s
    stage = 0
    last_publish = -1e9
    hub.set_health({"calibrated": True, "simulated": True, "gpio": False,
                    "parts": {p: "simulated" for p in ("camera", "ir_light",
                              "blue_light", "mist", "speakers", "co2")}})

    start = time.monotonic()
    for t, ear, mar, yaw, pitch in synth_ear_stream(minutes, FPS, seed=seed):
        delay = start + t - time.monotonic()
        if delay > 0:
            time.sleep(delay)

        calibrating = t < calibrate_s
        if calibrating:
            ff = FeatureFrame(t=t, face_found=True)
            state = DriverState(t=t, calibrated=False)
        else:
            ff = (FeatureFrame(t=t, face_found=False) if away[0] <= t < away[1]
                  else feature_frame(extractor, t, ear, mar, yaw, pitch))
            state = estimator.update(ff, calibrated=True)
            decision = policy.update(state)
            if decision.stage != stage:
                hub.emit(alert_event(decision, stage))
                print(f"{int(t) // 60:2d}m{int(t) % 60:02d}s  stage {stage} -> "
                      f"{decision.stage} ({decision.stage_name})", flush=True)
                stage = decision.stage

        if t - last_publish >= PUBLISH_PERIOD_S:
            last_publish = t
            hub.publish(build_snapshot(
                ff, state, stage=policy.stage,
                stage_name=str(policy.stages[policy.stage].get("name", "")),
                calibrated=not calibrating, calibrating=calibrating,
                cal_progress=t / calibrate_s if calibrating else 0.0,
                trip_s=t, fps=FPS, last_blink_s=extractor.blink.last_blink_s,
                # A cabin slowly going stale, so the CO2 card moves too.
                co2_ppm=600.0 + 1100.0 * t / total, co2_age_s=2.0))
    policy.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=8.0,
                    help="length of one simulated drive")
    ap.add_argument("--calibrate-s", type=float, default=6.0)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--once", action="store_true", help="stop after one drive")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    hub = Hub()
    server = ServerThread(hub, args.host, args.port).start()
    print(f"open http://localhost:{args.port}  (Ctrl+C to stop)", flush=True)
    seed = args.seed
    try:
        while True:
            drive(hub, args.minutes, args.calibrate_s, seed)
            if args.once:
                break
            seed += 1
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
