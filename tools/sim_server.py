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

The phone's commands work too, through the same Controller the device
uses: profile and settings, the guided calibration (the simulated driver
does as Ollie says, so "close your eyes" passes), the device test, Ollie's
lines, trips, Insights and the emergency trigger. Trips go to their own
database, runs/sim.db, so they never mix with a real device's.

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
from bamnun.control import Controller                      # noqa: E402
from bamnun.store import Store                             # noqa: E402
from bamnun.features import Calibration, FeatureExtractor, FeatureFrame  # noqa: E402
from bamnun.server import ServerThread                     # noqa: E402
from bamnun.session import load_config                     # noqa: E402
from bamnun.state import DriverState, StateEstimator       # noqa: E402
from bamnun.telemetry import Hub, alert_event, build_snapshot  # noqa: E402
from simulate import synth_ear_stream                      # noqa: E402

FPS = 20.0
PUBLISH_PERIOD_S = 0.1


def feature_frame(extractor: FeatureExtractor, t: float, ear: float, mar: float,
                  yaw: float, pitch: float) -> FeatureFrame:
    """Feed one synthetic sample through the real trackers.

    The same steps as the loop body in tools/simulate.py, which is left as it
    is; this bypasses only the landmark geometry.
    """
    ear_s = extractor.ear_ewma.update(ear)
    cal = extractor.calibration
    ear_norm = ear_s / cal.ear_open
    ev = extractor.blink.update(t, ear_s, cal.ear_open)
    extractor.perclos_window.push(t, ear_norm)
    perclos = extractor.perclos_window.time_fraction_below(extractor.perclos_fraction)
    extractor.yawn.update(t, mar)
    off = extractor.head.update(t, yaw, pitch, True)

    return FeatureFrame(
        t=t, face_found=True, ear_raw=ear, ear=ear_s, ear_norm=ear_norm,
        eye_closed=extractor.blink.is_closed,
        ongoing_closure_s=extractor.blink.ongoing_closure_s,
        microsleep_now=extractor.blink.microsleep_in_progress,
        perclos=perclos,
        blink_rate_per_min=extractor.blink.blink_rate_per_min(),
        mean_blink_duration_s=extractor.blink.mean_blink_duration_s(),
        microsleep_count=extractor.blink.microsleep_count(),
        long_closure_count=extractor.blink.long_closure_count(),
        mar=mar, yawn_count=extractor.yawn.count(),
        yawn_rate_per_hour=extractor.yawn.rate_per_hour(),
        yaw=yaw, pitch=pitch, pose_valid=True,
        pitch_std=extractor.head.pitch_std(), nodding=extractor.head.nodding(),
        gaze_h=0.0, gaze_v=0.0, gaze_valid=True,
        off_road=off, off_road_alarm=extractor.head.off_road_alarm,
        off_road_glance_s=extractor.head.current_glance_s,
        long_glance_count=extractor.head.long_glance_count(),
        interocular_px=120.0,
        blink_event=ev.kind if ev else None,
    )


class SimCalibration:
    """The guided calibration's view of a driver who does as asked.

    The look-ahead step "measures" for the usual 12 s and always succeeds;
    the eyes-closed check then sees the synthetic eyelids shut, because
    ``drive`` closes them while the step is running.
    """

    DURATION_S = 12.0

    def __init__(self) -> None:
        self.t0 = None
        self.t = 0.0

    def start(self, t: float) -> None:
        self.t0 = t

    def cancel(self) -> None:
        self.t0 = None

    def progress(self, t: float) -> float:
        return 0.0 if self.t0 is None else min(1.0, (t - self.t0) / self.DURATION_S)

    def ready(self) -> bool:
        return self.t0 is not None and self.t - self.t0 >= self.DURATION_S

    def failures(self) -> int:
        return 0

    def failure(self) -> str:
        return ""

    def open_level(self) -> float:
        return 0.30

    def closed_fraction(self) -> float:
        return 0.65

    def commit(self) -> None:
        self.t0 = None


def drive(hub: Hub, store: Store, minutes: float, calibrate_s: float, seed: int) -> None:
    cfg = load_config()
    for spec in cfg["alerts"]["actuators"].values():
        spec["type"] = "null"
    extractor = FeatureExtractor(cfg["features"], cfg["calibration"])
    extractor.set_calibration(Calibration(ear_open=0.30, ear_std=0.01,
                                          complete=True, n_samples=999))
    estimator = StateEstimator(cfg["state"])
    policy = EscalationPolicy(cfg["alerts"])
    sim_cal = SimCalibration()
    control = Controller(hub, store, policy, estimator=estimator, calibration=sim_cal,
                         trip_cfg=cfg.get("trips"))
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
        sim_cal.t = t
        step = control.guided.step
        if step == "close":
            ear = 0.06          # the driver closes their eyes when asked
        elif step in ("position", "look"):
            yaw = pitch = 0.0   # and sits still looking ahead
        if calibrating:
            ff = FeatureFrame(t=t, face_found=True)
            state = DriverState(t=t, calibrated=False)
        else:
            ff = (FeatureFrame(t=t, face_found=False) if away[0] <= t < away[1]
                  else feature_frame(extractor, t, ear, mar, yaw, pitch))
            state = estimator.update(ff, calibrated=True)
            decision = policy.update(state) if not control.holds_ladder(t) else None
            if decision is not None and decision.stage != stage:
                hub.emit(alert_event(decision, stage))
                print(f"{int(t) // 60:2d}m{int(t) % 60:02d}s  stage {stage} -> "
                      f"{decision.stage} ({decision.stage_name})", flush=True)
                stage = decision.stage

        co2 = 600.0 + 1100.0 * t / total
        control.tick(t, face=bool(ff.face_found), calibrated=not calibrating,
                     eye_closed=bool(ff.eye_closed) if ff.face_found and not calibrating else None,
                     microsleep=bool(ff.microsleep_now),
                     ear_raw=ear if ff.face_found else None, co2_ppm=co2)

        if t - last_publish >= PUBLISH_PERIOD_S:
            last_publish = t
            hub.publish(build_snapshot(
                ff, state, stage=policy.stage,
                stage_name=str(policy.stages[policy.stage].get("name", "")),
                calibrated=not calibrating, calibrating=calibrating,
                cal_progress=t / calibrate_s if calibrating else 0.0,
                trip_s=t, fps=FPS, last_blink_s=extractor.blink.last_blink_s,
                # A cabin slowly going stale, so the CO2 card moves too.
                co2_ppm=co2, co2_age_s=2.0))
    control.close()
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
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "runs" / "sim.db"),
                    help="where the simulated device keeps its profile and trips")
    args = ap.parse_args()

    hub = Hub()
    store = Store(args.db)
    server = ServerThread(hub, args.host, args.port, store=store).start()
    print(f"open http://localhost:{args.port}  (Ctrl+C to stop)", flush=True)
    seed = args.seed
    try:
        while True:
            drive(hub, store, args.minutes, args.calibrate_s, seed)
            if args.once:
                break
            seed += 1
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
