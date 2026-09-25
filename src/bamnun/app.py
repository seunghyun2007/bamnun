"""Main real-time loop.

    python -m bamnun.app --source webcam            # laptop development
    python -m bamnun.app --source picamera --no-window   # headless on the Pi
    python -m bamnun.app --source video --device runs/clip.mp4 --fast

Keys in the window: c recalibrate, s snapshot, a toggle actuators, q quit.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from collections import deque
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from .alerts import EscalationPolicy
from .capture import open_source
from .features import Calibration, FeatureExtractor, FeatureFrame
from .landmarks import FaceLandmarker
from .predictor import RestPlanner
from .session import SessionLogger, load_config, repo_root
from .state import DriverState, StateEstimator

console = Console()
log = logging.getLogger("bamnun")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bamnun", description="driver state monitor")
    p.add_argument("--config", default=None, help="extra YAML merged over the default")
    p.add_argument("--source", choices=["picamera", "webcam", "video"], default=None)
    p.add_argument("--device", default=None, help="webcam index or video path")
    p.add_argument("--no-window", action="store_true", help="headless")
    p.add_argument("--no-alerts", action="store_true", help="detect but do not actuate")
    p.add_argument("--fast", action="store_true", help="video source: ignore real-time pacing")
    p.add_argument("--loop", action="store_true", help="video source: loop the file")
    p.add_argument("--calibration", default=None, help="load a saved calibration JSON")
    p.add_argument("--hours-awake", type=float, default=8.0,
                   help="driver's hours since waking, for the alertness prior")
    p.add_argument("--tag", default="", help="label appended to the session log filenames")
    p.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def build_overrides(args: argparse.Namespace) -> dict:
    ov: dict = {}
    cap: dict = {}
    if args.source:
        cap["source"] = args.source
    if args.device is not None:
        cap["device"] = int(args.device) if str(args.device).isdigit() else args.device
    if cap:
        ov["capture"] = cap
    if args.no_window:
        ov["ui"] = {"show_window": False}
    if args.no_alerts:
        ov["alerts"] = {"enabled": False}
    return ov


class Monitor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.cfg = load_config(args.config, build_overrides(args))
        self.root = repo_root()

        self.source = open_source(
            self.cfg["capture"],
            **({"realtime": not args.fast, "loop": args.loop}
               if self.cfg["capture"].get("source") == "video" else {}),
        )
        self.landmarker = FaceLandmarker(self.cfg["landmarks"], repo_root=self.root)
        self.features = FeatureExtractor(self.cfg["features"], self.cfg["calibration"])
        self.estimator = StateEstimator(self.cfg["state"])
        self.planner = RestPlanner(self.cfg["predictor"])
        self.planner.set_driver_context(args.hours_awake)
        self.policy = EscalationPolicy(self.cfg["alerts"])
        self.logger = SessionLogger(self.cfg["logging"], tag=args.tag)

        self.show_window = bool(self.cfg["ui"].get("show_window", True)) and not args.no_window
        self._fps = deque(maxlen=60)
        self._running = True
        self._plan = None
        self._last_plan_t = -1e9
        self._last_alert = None
        self._cal_attempts_seen = 0

        cal_path = args.calibration or self.cfg["calibration"].get("save_path")
        self._cal_path = self.root / str(cal_path)
        self._load_calibration()

        self.logger.write_meta({
            "config": self.cfg,
            "argv": sys.argv,
            "resolution": self.source.resolution,
            "hours_awake": args.hours_awake,
        })

    # ----------------------------------------------------------------- #

    def _load_calibration(self) -> None:
        if self._cal_path.exists():
            try:
                data = json.loads(self._cal_path.read_text(encoding="utf-8"))
                self.features.set_calibration(Calibration.from_dict(data))
                console.print(f"[green]loaded calibration[/] {self._cal_path} "
                              f"(open EAR {self.features.calibration.ear_open:.3f})")
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("could not read calibration: %s", exc)
        console.print("[yellow]no calibration on file; press 'c' or wait for auto-calibration[/]")

    def _save_calibration(self) -> None:
        self._cal_path.parent.mkdir(parents=True, exist_ok=True)
        self._cal_path.write_text(
            json.dumps(self.features.calibration.to_dict(), indent=2), encoding="utf-8"
        )
        console.print(f"[green]calibration saved[/] {self._cal_path}")

    def stop(self, *_a) -> None:
        self._running = False

    # ----------------------------------------------------------------- #

    def run(self) -> int:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        cv2 = None
        if self.show_window:
            try:
                import cv2 as _cv2
                cv2 = _cv2
                cv2.namedWindow("bamnun", cv2.WINDOW_NORMAL)
            except Exception as exc:  # noqa: BLE001
                log.warning("no GUI available (%s); running headless", exc)
                self.show_window = False

        # Auto-start calibration if we have none. Better than silently running
        # with a default baseline that fits nobody.
        if not self.features.calibration.complete:
            first = self.source.read()
            if first is not None:
                self.features.start_calibration(first.timestamp)

        t_start = None
        last = time.monotonic()
        alerts_on = True

        console.print("[bold]running[/]  keys: c calibrate  s snapshot  a alerts  q quit")

        for frame in self.source:
            if not self._running:
                break
            if t_start is None:
                t_start = frame.timestamp
            if self.args.duration and (frame.timestamp - t_start) > self.args.duration:
                break

            lms = self.landmarker.process(frame)
            ff: FeatureFrame = self.features.update(frame.timestamp, lms)

            calibrating = self.features.calibrating
            if calibrating:
                state = DriverState(t=frame.timestamp, calibrated=False)
                progress = self.features.calibrator.progress(frame.timestamp)
                # A restarted calibration used to be indistinguishable from a
                # frozen progress bar. Report the reason once per attempt.
                cal_obj = self.features.calibrator
                if cal_obj.attempts != self._cal_attempts_seen:
                    self._cal_attempts_seen = cal_obj.attempts
                    console.print(f"[yellow]calibration restarted[/] "
                                  f"(attempt {cal_obj.attempts + 1}): "
                                  f"{cal_obj.last_failure}")
                    self.logger.log_event("calibration_retry",
                                          {"attempt": cal_obj.attempts,
                                           "reason": cal_obj.last_failure})
            else:
                progress = -1.0
                if self.features.calibration.complete and self.features.calibration.n_samples \
                        and not getattr(self, "_cal_announced", False):
                    self._save_calibration()
                    self._cal_announced = True
                state = self.estimator.update(
                    ff, calibrated=self.features.calibration.complete
                )
                self.planner.push(frame.timestamp, state.score)
                if frame.timestamp - self._last_plan_t > 15.0:
                    self._plan = self.planner.plan(frame.timestamp)
                    self._last_plan_t = frame.timestamp

                decision = self.policy.update(state) if alerts_on else None
                if decision is not None and (decision.fired or decision.changed):
                    self._last_alert = decision
                    self.logger.log_event("alert", decision)
                    if decision.fired:
                        console.print(f"[bold red]ALERT[/] stage={decision.stage_name} "
                                      f"-> {[a.actuator for a in decision.fired]}")

                if ff.blink_event in ("microsleep", "long_closure"):
                    self.logger.log_event("closure", {"kind": ff.blink_event,
                                                      "t": ff.t,
                                                      "duration_s": ff.ongoing_closure_s})
                self.logger.log_frame(ff, state)

            now = time.monotonic()
            self._fps.append(1.0 / max(now - last, 1e-6))
            last = now
            fps = sum(self._fps) / len(self._fps)

            if self.show_window and cv2 is not None:
                from .viz import draw_overlay
                canvas = draw_overlay(
                    frame.image, lms, ff, state, plan=self._plan,
                    alert=self._last_alert, ui_cfg=self.cfg["ui"], fps=fps,
                    calibrating=progress if calibrating else -1.0,
                    cal_stats=(self.features.calibrator.stats(frame.timestamp)
                               if calibrating else None),
                )
                scale = float(self.cfg["ui"].get("window_scale", 1.0))
                if scale != 1.0:
                    canvas = cv2.resize(canvas, None, fx=scale, fy=scale)
                cv2.imshow("bamnun", canvas)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("c"):
                    self.features.start_calibration(frame.timestamp)
                    self._cal_announced = False
                    console.print("[cyan]calibration restarted[/]")
                if key == ord("s"):
                    out = self.logger.dir / f"snap_{int(time.time())}.png"
                    cv2.imwrite(str(out), canvas)
                    console.print(f"snapshot {out}")
                if key == ord("a"):
                    alerts_on = not alerts_on
                    console.print(f"actuators {'on' if alerts_on else 'off'}")
            elif not self.show_window:
                # Headless heartbeat, once a second.
                if int(frame.timestamp) != int(frame.timestamp - 1 / max(fps, 1)):
                    pass

        self.shutdown()
        return 0

    def shutdown(self) -> None:
        if self._plan is not None:
            console.print(f"[bold]final rest plan:[/] {self._plan.summary()}")
        self.logger.log_event("shutdown", {"actuations": len(self.policy.history)})
        self.logger.close()
        self.policy.close()
        self.landmarker.close()
        self.source.close()
        try:
            import cv2
            cv2.destroyAllWindows()
        except Exception:
            pass
        console.print("[bold]stopped[/]")


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    try:
        return Monitor(args).run()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
