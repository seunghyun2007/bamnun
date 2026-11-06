"""Main real-time loop.

    python -m bamnun.app --source webcam            # laptop development
    python -m bamnun.app --source picamera --no-window   # headless on the Pi
    python -m bamnun.app --source video --device runs/clip.mp4 --fast
    python -m bamnun.app --serve                    # plus the app and live data on :8000

Keys in the window: c recalibrate, s snapshot, a toggle actuators, l dashboard or
camera-only layout, f full screen, - and = speaker volume, space the visitor
briefing, Esc skip the standby or briefing screen, q quit. The dashboard also has Calibrate, Full screen and volume
buttons to click; on the standby and briefing screens a click is space.
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
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

from .air import CabinAir
from .alerts import (_HAVE_GPIO, AlertDecision, AtomizerActuator, AudioActuator,
                     EscalationPolicy, LightActuator)
from . import demo as demo_mode
from .capture import Illuminator, open_source
from .control import Controller, FeatureCalibration
from .eyes import face_brightness
from .predictor import two_process_alertness
from .features import Calibration, FeatureExtractor, FeatureFrame
from .landmarks import FaceLandmarker
from .predictor import RestPlanner
from .session import SessionLogger, load_config, repo_root
from .state import DriverState, StateEstimator
from .store import Store
from .video import VideoEncoder
from .telemetry import Hub, alert_event, build_snapshot
from .viz import (DASH_H, DASH_W, Dashboard, DashboardData, button_at, fit_to_window,
                  window_to_canvas)

# Console output must never stop detection. A Windows console in a legacy
# code page can't print Korean (Ollie's lines, a driver's name), and an
# encoding error raised inside a print in the camera loop used to end the
# program. Write UTF-8 and replace anything the terminal still can't show.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
console = Console()

# The camera loop runs at 25-30 fps; the app only needs a fraction of that.
PUBLISH_PERIOD_S = 0.1
# The dashboard's score chart: one sample every half second, the last 2 min.
SCORE_SAMPLE_S = 0.5
SOUND_LIGHT_S = 3.0      # the dashboard's SOUND light stays lit this long after a sound
CAL_NOTICE_S = 20.0      # how long a failed calibration's message stays on the dashboard
BRIEFING_IDLE_S = 45.0   # an untouched briefing page closes after this
VOLUME_STEP = 10

# The calibrator's live hints, as a person reads them.
CAL_HINTS = {"no_face": "Can't see your face", "closer": "Move a little closer",
             "farther": "Move back a little", "dark": "Too dark: more light, please",
             "bright": "Too bright", "face_camera": "Turn a little towards the camera",
             "still": "Hold still"}


class SpeakerVolume:
    """The device speaker's volume, through ALSA's mixer (amixer).

    The card is the USB speaker the device plays through (ui.speaker_mixer).
    Changes are saved with alsactl so they survive a restart, in the
    background so the camera loop never waits on them.
    """

    def __init__(self, cfg: Optional[dict]) -> None:
        cfg = cfg or {}
        self.card = str(cfg.get("card", "UACDemoV10"))
        self.control = str(cfg.get("control", "PCM"))
        self.percent: Optional[int] = self._read()

    def _read(self) -> Optional[int]:
        import re
        import subprocess

        try:
            out = subprocess.run(["amixer", "-c", self.card, "sget", self.control],
                                 capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        m = re.search(r"\[(\d+)%\]", out)
        return int(m.group(1)) if m else None

    def change(self, step: int) -> None:
        import subprocess
        import threading

        if self.percent is None:
            return
        self.percent = max(0, min(100, self.percent + step))
        pct = self.percent

        def apply() -> None:
            try:
                subprocess.run(["amixer", "-q", "-c", self.card, "sset", self.control, f"{pct}%"],
                               timeout=3)
                subprocess.run(["sudo", "-n", "alsactl", "store", self.card],
                               capture_output=True, timeout=5)
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning("speaker volume: %s", exc)

        threading.Thread(target=apply, name="bamnun-volume", daemon=True).start()
        console.print(f"speaker volume {pct}%")
HEALTH_PERIOD_S = 1.0
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
    p.add_argument("--demo", action="store_true",
                   help="showcase mode: keys 1-4 fire each stage, t runs a tour")
    p.add_argument("--serve", action="store_true",
                   help="serve the phone app and live data (needs fastapi, uvicorn)")
    p.add_argument("--host", default="0.0.0.0", help="--serve: address to listen on")
    p.add_argument("--port", type=int, default=8000, help="--serve: port")
    p.add_argument("--booth", action="store_true",
                   help="demo booth: --serve, quiet ladder, and phones kept on the booth "
                        "Wi-Fi (tools/booth/setup_booth.sh)")
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
        self.demo = bool(getattr(args, "demo", False))
        if self.demo:
            self.cfg = demo_mode.apply_demo(self.cfg)
        self.tour = demo_mode.Tour()
        self.root = repo_root()

        self.source = open_source(
            self.cfg["capture"],
            **({"realtime": not args.fast, "loop": args.loop}
               if self.cfg["capture"].get("source") == "video" else {}),
        )
        self.illuminator = Illuminator(self.cfg["capture"].get("illuminator"),
                                       str(self.cfg["capture"].get("source", "")))
        self.landmarker = FaceLandmarker(self.cfg["landmarks"], repo_root=self.root)
        self.features = FeatureExtractor(self.cfg["features"], self.cfg["calibration"])
        self.estimator = StateEstimator(self.cfg["state"])
        self.planner = RestPlanner(self.cfg["predictor"])
        self.planner.set_driver_context(args.hours_awake)
        self.policy = EscalationPolicy(self.cfg["alerts"])
        self.air = CabinAir(self.cfg.get("air"))
        self._air_seen_at = None
        self.logger = SessionLogger(self.cfg["logging"], tag=args.tag)

        self.show_window = bool(self.cfg["ui"].get("show_window", True)) and not args.no_window
        self._fps = deque(maxlen=60)
        self._running = True
        self._plan = None
        self._last_plan_t = -1e9
        self._last_alert = None
        self._cal_attempts_seen = 0
        self._cal_run = False

        # Live data for the phone app. The Hub always exists, so publishing
        # costs the same with or without --serve; only the server is optional.
        self.hub = Hub()
        self.hub.video_capable = True
        self.hub.video_size = list(self.source.resolution) if self.source.resolution else None
        vcfg = self.cfg.get("video") or {}
        self.video = VideoEncoder(self.hub, width=int(vcfg.get("width", 640)),
                                  quality=int(vcfg.get("quality", 80)),
                                  max_fps=float(vcfg.get("max_fps", 30)))
        self.server = None
        self._last_publish = -1e9
        self._last_video = -1e9
        self._last_window = -1e9
        self._window_period = 1.0 / max(1.0, float(self.cfg["ui"].get("window_max_fps", 15)))
        # The presenting layout: the camera beside large panels of what the
        # detector sees (viz.Dashboard). l switches to the camera alone.
        ui = self.cfg["ui"]
        self._dash_refresh_s = float(ui.get("dashboard_refresh_s", 0.2))
        layout = "dashboard" if args.booth else ui.get("layout", "overlay")
        self.dashboard = Dashboard(self._dash_refresh_s) if layout == "dashboard" else None
        self._score_history: deque = deque(maxlen=int(120.0 / SCORE_SAMPLE_S))
        self._co2_history: deque = deque(maxlen=120)     # 10 min at the sensor's 5 s
        self._co2_recorded_at: Optional[float] = None
        self._last_score_t = -1e9
        self.volume = SpeakerVolume(ui.get("speaker_mixer"))
        self._max_cal_attempts = int(self.cfg["calibration"].get("max_attempts", 3))
        # Booth screens (attract.py): standby after a while with nobody at the
        # wheel, and the briefing a visitor starts with space or a click.
        self.mode = "live"                       # live | standby | briefing
        self._standby_after_s = float(ui.get("standby_after_s", 30.0))
        self._no_face_since: Optional[float] = None
        self._face_since: Optional[float] = None
        self._brief_step = 0
        self._brief_at = 0.0
        self._screens = None
        self._cal_notice: Optional[tuple[str, float]] = None
        self._last_health = -1e9
        self._published_stage = 0
        self._publish_failed = False

        # Profile, settings and trips (SPEC.md, sections 0 and 1). The store
        # is optional in the same way the server is: without it the device
        # still detects and alerts, it just keeps no trips.
        self.store = None
        db = (self.cfg.get("storage") or {}).get("db", "runs/bamnun.db")
        try:
            self.store = Store(self.root / str(db))
        except Exception as exc:  # noqa: BLE001
            log.warning("no profile or trip storage (%s); detection unaffected", exc)
        self.controller = Controller(
            self.hub, self.store, self.policy, estimator=self.estimator,
            calibration=FeatureCalibration(self.features, on_commit=self._save_calibration),
            trip_cfg=self.cfg.get("trips"), quiet=self.args.booth)

        # Calibration is per driver (SPEC.md, 15): runs/drivers/<name>/.
        # --calibration names a file explicitly and pins it.
        self._pinned_cal = args.calibration
        self._driver = driver_id(self.controller.profile.get("name", ""))
        self._cal_path = self._calibration_path()
        self._load_calibration()
        self._last_driver_check = -1e9
        self._proc = deque(maxlen=60)
        self._slow_since: Optional[float] = None
        self._last_risk = -1e9
        self._t_started = time.monotonic()
        self._time_risk: Optional[dict] = None

        self.logger.write_meta({
            "config": self.cfg,
            "argv": sys.argv,
            "resolution": self.source.resolution,
            "hours_awake": args.hours_awake,
        })

    # ----------------------------------------------------------------- #

    def _calibration_path(self) -> Path:
        if self._pinned_cal:
            return self.root / str(self._pinned_cal)
        per_driver = self.root / "runs" / "drivers" / self._driver / "calibration.json"
        legacy = self.root / str(self.cfg["calibration"].get("save_path", "runs/calibration.json"))
        # The first time, carry an older single calibration over to "default".
        if not per_driver.exists() and self._driver == "default" and legacy.exists():
            return legacy
        return per_driver

    def _check_driver(self, now: float) -> None:
        """A new profile name means a new driver: use their calibration."""
        if self._pinned_cal or now - self._last_driver_check < 2.0:
            return
        self._last_driver_check = now
        d = driver_id(self.controller.profile.get("name", ""))
        if d == self._driver:
            return
        self._driver = d
        self._cal_path = self._calibration_path()
        console.print(f"[cyan]driver changed[/] to {d!r}")
        if self._cal_path.exists():
            self._load_calibration()

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
        if not self._pinned_cal:
            self._cal_path = self.root / "runs" / "drivers" / self._driver / "calibration.json"
        self._cal_path.parent.mkdir(parents=True, exist_ok=True)
        self._cal_path.write_text(
            json.dumps(self.features.calibration.to_dict(), indent=2), encoding="utf-8"
        )
        console.print(f"[green]calibration saved[/] {self._cal_path}")

    def _demo_action(self, key: str, t: float) -> None:
        """One showcase action: a stage, a glance nudge, the CO2 prompt, off."""
        console.print(f"[bold magenta]demo[/] {demo_mode.LABELS.get(key, key)}")
        if key in "1234":
            decision = self.policy.trigger(int(key), t, note="demo")
        elif key == "0":
            decision = self.policy.reset(t)
        else:
            if key == "d":
                names = self.policy.distraction_actuators or ["chime"]
                stage = "distraction"
            else:
                names = [self.air.actuator]
                stage = "co2"
            fired = [a for a in (self.policy.prompt(n, t, stage) for n in names) if a]
            decision = AlertDecision(t=t, stage=self.policy.stage, stage_name=stage,
                                     changed=True, fired=fired, message="demo")
        decision.message = f"demo {key}"
        self._last_alert = decision
        self._note_stage(decision)
        self.logger.log_event("demo", decision)
        for a in decision.fired:
            console.print(f"     -> {a.actuator}: {a.detail}")
        for why in decision.suppressed:
            console.print(f"     [yellow]suppressed[/] {why}")

    def _voice(self, name: str, t: float) -> None:
        """Play an optional spoken cue outside the alert ladder."""
        a = self.policy.prompt(name, t)
        if a is not None:
            self.logger.log_event("prompt", a)

    def _check_air(self, t: float, level: int) -> None:
        air = self.air
        if air.updated_at is not None and air.updated_at != self._air_seen_at:
            self._air_seen_at = air.updated_at
            self.logger.log_event("co2", {"t": t, "ppm": air.ppm,
                                          "temp_c": air.temp_c, "rh": air.rh})
        if air.should_prompt(level):
            console.print(f"[bold yellow]CO2 {air.ppm:.0f} ppm[/]: open the window")
            a = self.policy.prompt(air.actuator, t, "co2")
            self.logger.log_event("co2_prompt", {"t": t, "ppm": air.ppm, "level": level,
                                                 "fired": a is not None})

    def stop(self, *_a) -> None:
        self._running = False

    # -- live data for the app ------------------------------------------ #

    def start_server(self) -> None:
        """Serve the app and live data. Never fatal: detection runs regardless."""
        try:
            from .server import ServerThread
        except ImportError as exc:
            console.print(f"[yellow]--serve needs fastapi and uvicorn ({exc}); "
                          "pip install -r requirements.txt[/]")
            return
        try:
            self.server = ServerThread(self.hub, self.args.host, self.args.port,
                                       store=self.store, booth=self.args.booth).start()
        except Exception as exc:  # noqa: BLE001
            log.warning("could not start the server: %s", exc)
            return
        console.print(f"[green]app and live data[/] on port {self.args.port}: "
                      f"open http://<this machine's address>:{self.args.port}")

    def _guarded(self, fn, *args) -> None:
        """Run a publishing step; a fault there must never stop detection."""
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            if not self._publish_failed:
                self._publish_failed = True
                log.warning("live data publishing failed (detection unaffected): %r", exc)

    def _note_stage(self, decision: AlertDecision) -> None:
        """Send an ``alert`` message when the ladder stage changes."""
        def emit():
            if decision.stage != self._published_stage:
                self.hub.emit(alert_event(decision, self._published_stage))
                self._published_stage = decision.stage
        self._guarded(emit)

    def _health(self) -> dict:
        """Part status for /api/health: ok, simulated, missing or off."""
        acts = self.policy.actuators

        def part(name: str) -> str:
            a = acts.get(name)
            if a is None or not a.available:
                return "missing"
            if isinstance(a, AudioActuator):
                # A player with nothing recorded to play is still a stub.
                return "ok" if a._player and a.present else "simulated"
            return "ok" if getattr(a, "_dev", None) is not None else "simulated"

        ir = self.illuminator
        guided = self.controller.guided
        return {
            "calibrated": bool(self.features.calibration.complete),
            # The driver's Yes / No from the last device test (section 8).
            "checks": {k: v for k, v in (guided.results if guided else {}).items()
                       if k in ("speaker", "chime", "light", "mist")},
            "gpio": bool(_HAVE_GPIO),
            "parts": {
                "camera": str(self.cfg["capture"].get("source", "")),
                "ir_light": ("ok" if ir.is_on and ir._dev is not None
                             else "simulated" if ir.is_on else "off"),
                "blue_light": part("blue_light"),
                "mist": part("scent"),
                "speakers": part("chime"),
                "co2": "ok" if self.air.available else "missing",
            },
        }

    def _watch_rate(self, now: float, fps: float) -> None:
        """Warn once a minute if detection runs below 20 fps (audit F1)."""
        if fps >= 20.0:
            self._slow_since = None
            return
        if self._slow_since is None:
            self._slow_since = now
        elif now - self._slow_since > 10.0:
            cap = len(self._proc) / max(sum(self._proc), 1e-6)
            log.warning("detection at %.0f fps (processing could do %.0f): %s", fps, cap,
                        "the camera is slow (low light?)" if cap > fps * 1.5
                        else "processing is the limit: close the preview window")
            self._slow_since = now + 50.0

    def _risk(self, now: float) -> Optional[dict]:
        """Time-of-day risk, separate from the camera score (SPEC.md, 15)."""
        if now - self._last_risk < 30.0 and self._time_risk is not None:
            return self._time_risk
        self._last_risk = now
        local = time.localtime(time.time() + self.hub.clock_offset_s)
        hour = local.tm_hour + local.tm_min / 60.0
        awake = float(self.args.hours_awake) + (now - self._t_started) / 3600.0
        v = two_process_alertness(awake, hour)
        self._time_risk = {"level": "high" if v >= 0.55 else "medium" if v >= 0.35 else "low",
                           "value": round(v, 2), "hours_awake": round(awake, 1)}
        return self._time_risk

    def _publish(self, now: float, ff: FeatureFrame, state: DriverState,
                 calibrating: bool, progress: float, fps: float,
                 trip_s: float, lms=None) -> None:
        if now - self._last_publish < PUBLISH_PERIOD_S:
            return
        self._last_publish = now
        air = self.air
        co2_age = (None if air.updated_at is None
                   else time.monotonic() - air.updated_at)
        self.hub.publish(build_snapshot(
            ff, state, stage=self.policy.stage,
            stage_name=str(self.policy.stages[self.policy.stage].get("name", "")),
            calibrated=self.features.calibration.complete,
            calibrating=calibrating, cal_progress=progress, trip_s=trip_s,
            fps=fps, last_blink_s=self.features.blinks.last_blink_s,
            co2_ppm=air.ppm, co2_age_s=co2_age, face_box=face_box(lms),
            time_risk=self._risk(now),
            fps_capacity=(len(self._proc) / max(sum(self._proc), 1e-6)) if self._proc else None))
        if now - self._last_health >= HEALTH_PERIOD_S:
            self._last_health = now
            self.hub.set_health(self._health())

    def _control(self, t: float, ff: FeatureFrame) -> None:
        """Phone commands, guided calibration, trips, reminders, emergency."""
        face = bool(ff.face_found)
        self.controller.tick(
            t, face=face, calibrated=bool(self.features.calibration.complete),
            eye_closed=bool(ff.eye_closed) if face and not self.features.calibrating else None,
            microsleep=bool(ff.microsleep_now), ear_raw=ff.ear_raw if face else None,
            co2_ppm=self.air.ppm)

    def _publish_video(self, now: float, image, lms, ff: FeatureFrame) -> None:
        """Hand the frame to the encoder thread, only while someone watches."""
        self.video.offer(image, lms, ff.shut_now or ff.microsleep_now)

    def _on_mouse(self, event: int, x: int, y: int, _flags: int, _param) -> None:
        """A click on a dashboard button; acted on in the camera loop."""
        import cv2

        if event != cv2.EVENT_LBUTTONUP:
            return
        if self.mode != "live":
            self._clicks.append("next")
            return
        if self.dashboard is None:
            return
        try:
            _x, _y, win_w, win_h = cv2.getWindowImageRect("bamnun")
        except Exception:  # noqa: BLE001
            return
        name = button_at(*window_to_canvas(x, y, win_w, win_h))
        if name:
            self._clicks.append(name)

    def _start_calibration(self, t: float) -> None:
        """Calibrate now (c key, the button, or start-up with none on file).

        The wake-up lights go off first: the blue light shines into the
        camera's view and darkens its exposure, which failed every
        calibration after the first as "too dark". Nobody calibrating is
        drowsy anyway.
        """
        self._last_alert = self.policy.reset(t)
        self.features.calibrator.reset()
        self.features.start_calibration(t)
        self._cal_run = True
        self._cal_announced = False
        self._cal_notice = None

    def _give_up_calibration(self, t: float) -> None:
        """Stop after a few failed tries if there is a calibration to keep.

        A calibration restarts by itself when it fails, which left the
        dashboard calibrating forever. With an earlier one on file, keep it
        and say why the new one didn't work; the button tries again.
        """
        cal = self.features.calibrator
        if (cal.attempts >= self._max_cal_attempts and self.features.calibration.complete
                and self.features.calibrating):
            self.features.cancel_calibration()
            self._cal_run = False
            why = cal.last_failure or "the measurement wasn't steady"
            self._cal_notice = (f"Kept the last calibration. {why}", time.monotonic() + CAL_NOTICE_S)
            console.print(f"[yellow]calibration stopped after {cal.attempts} tries[/]: {why}")
            self.logger.log_event("calibration_gave_up", {"attempts": cal.attempts, "reason": why})

    def _update_mode(self, now: float, face: bool) -> None:
        """Standby after standby_after_s with no face. It stays up when someone
        sits down, so they can read it and press space; Esc skips it."""
        if face:
            self._no_face_since = None
            if self._face_since is None:
                self._face_since = now
        else:
            self._face_since = None
            if self._no_face_since is None:
                self._no_face_since = now
        if self.mode == "live" and self._standby_after_s > 0 and self._no_face_since is not None \
                and now - self._no_face_since >= self._standby_after_s:
            self.mode = "standby"
            self._last_alert = self.policy.reset(now)     # lights off; nobody to wake
            self.logger.log_event("standby", {"after_s": self._standby_after_s})
            console.print("[dim]standby: nobody at the wheel[/]")
        elif self.mode == "briefing" and now - self._brief_at >= BRIEFING_IDLE_S:
            self.mode = "live"

    def _next(self, now: float, t: float) -> None:
        """Space or a click: start the briefing, or turn its page."""
        from .attract import STEPS

        if self.mode != "briefing":
            self.mode, self._brief_step = "briefing", 0
            self.logger.log_event("briefing", {})
        elif self._brief_step < len(STEPS) - 1:
            self._brief_step += 1
        else:                                         # the last page: calibrate now
            self.mode = "live"
            self._start_calibration(t)
            self._voice("calibrate_voice", t)
        self._brief_at = now

    def _record_history(self, t: float, state: DriverState, calibrating: bool) -> None:
        """Samples for the dashboard's charts."""
        if not calibrating and t - self._last_score_t >= SCORE_SAMPLE_S:
            self._last_score_t = t
            self._score_history.append((t, float(state.score)))
        air = self.air
        if air.ppm is not None and air.updated_at != self._co2_recorded_at:
            self._co2_recorded_at = air.updated_at
            self._co2_history.append((t, float(air.ppm)))

    def _dashboard_data(self, t: float, session_s: float, fps: float, progress: float,
                        alerts_on: bool) -> DashboardData:
        acts = list(self.policy.actuators.values())
        sound_on = any(isinstance(a, AudioActuator) and a._last_fired is not None
                       and time.monotonic() - a._last_fired < SOUND_LIGHT_S for a in acts)
        mist_on = any(isinstance(a, AtomizerActuator) and a._last_fired is not None
                      and time.monotonic() - a._last_fired < max(a.duration, 1.0) for a in acts)
        stages = self.policy.stages
        stage = self.policy.stage
        air = self.air
        last = self._last_alert
        last_words = ""
        if last is not None and last.fired:
            names = ", ".join(a.actuator for a in last.fired)
            last_words = f"{last.stage_name}: {names}"
        return DashboardData(
            now=t, fps=fps, session_s=session_s, calibrating=progress,
            score_history=self._score_history, co2_history=self._co2_history,
            co2_connected=air.enabled, co2_ppm=air.ppm,
            co2_age_s=(time.monotonic() - air.updated_at
                       if air.updated_at is not None else None),
            temp_c=air.temp_c, rh=air.rh,
            co2_elevated_ppm=air.drowsy_prompt_ppm, co2_high_ppm=air.prompt_ppm,
            score_ticks=[float(lv["min_score"]) for lv in self.cfg["state"].get("levels", [])
                         if lv.get("min_score")],
            ir_on=self.illuminator.is_on,
            blue_on=any(isinstance(a, LightActuator) and a.is_on for a in acts),
            mist_on=mist_on, sound_on=sound_on,
            alerts_on=alerts_on and bool(self.cfg["alerts"].get("enabled", True)),
            stage=stage,
            stage_name=str(stages[min(stage, len(stages) - 1)].get("name", "")),
            last_alert=last_words,
            plan=self._plan,
            calibration_hint=(CAL_HINTS.get(self.features.calibrator.hint or "", "")
                              if progress >= 0.0 else ""),
            notice=(self._cal_notice[0] if self._cal_notice
                    and time.monotonic() < self._cal_notice[1] else ""),
            volume=self.volume.percent,
            note=("booth: nothing fires by itself; stages play from the app"
                  if self.args.booth else demo_mode.HELP if self.demo else ""),
        )

    # ----------------------------------------------------------------- #

    def run(self) -> int:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        cv2 = None
        fullscreen = bool(self.args.booth or self.cfg["ui"].get("fullscreen", False))
        self._clicks: deque = deque(maxlen=4)
        if self.show_window:
            try:
                import cv2 as _cv2
                cv2 = _cv2
                # No Qt toolbar, and fit_to_window keeps the dashboard's
                # shape, so nothing is left for Qt to letterbox in grey.
                cv2.namedWindow("bamnun", cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL
                                | cv2.WINDOW_FREERATIO)
                cv2.setMouseCallback("bamnun", self._on_mouse)
                if fullscreen:   # the booth's big screen shows only this
                    cv2.setWindowProperty("bamnun", cv2.WND_PROP_FULLSCREEN,
                                          cv2.WINDOW_FULLSCREEN)
            except Exception as exc:  # noqa: BLE001
                log.warning("no GUI available (%s); running headless", exc)
                self.show_window = False

        # Auto-start calibration if we have none. Better than silently running
        # with a default baseline that fits nobody.
        if not self.features.calibration.complete:
            first = self.source.read()
            if first is not None:
                self._start_calibration(first.timestamp)
                self._voice("calibrate_voice", first.timestamp)

        t_start = None
        last = time.monotonic()
        alerts_on = True
        self.illuminator.on()
        if self.args.serve or self.args.booth:
            self.start_server()

        console.print("[bold]running[/]  keys: c calibrate  s snapshot  a alerts  "
                      "l layout  f full screen  q quit")
        if self.demo:
            console.print(f"[bold magenta]{demo_mode.HELP}[/]")
            if not self.show_window:
                # No window means no keys; run the tour once instead.
                self.tour.start(time.monotonic())

        for frame in self.source:
            if not self._running:
                break
            if t_start is None:
                t_start = frame.timestamp
            if self.args.duration and (frame.timestamp - t_start) > self.args.duration:
                break

            t_proc = time.perf_counter()     # processing capacity = face tracking + everything after
            lms = self.landmarker.process(frame)
            bright = face_brightness(frame.image, lms.points) if lms is not None and lms.ok else None
            ff: FeatureFrame = self.features.update(frame.timestamp, lms, brightness=bright)

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
                    # Only after a calibration that ran now, not one loaded
                    # from disk at start-up.
                    if self._cal_run:
                        self._cal_run = False
                        self._voice("calibrated_voice", frame.timestamp)
                state = self.estimator.update(
                    ff, calibrated=self.features.calibration.complete
                )
                self.planner.push(frame.timestamp, state.score)
                if frame.timestamp - self._last_plan_t > 15.0:
                    self._plan = self.planner.plan(frame.timestamp)
                    self._last_plan_t = frame.timestamp
                    plan = self._plan
                    if plan.valid and (plan.recommend_rest_now or (
                            plan.rest_at_s is not None and plan.rest_at_s < 600.0)):
                        self._voice("rest_voice", frame.timestamp)
                self._check_air(frame.timestamp, state.level if state.calibrated else 0)

                hold = self.controller.holds_ladder(frame.timestamp)
                decision = (self.policy.update(state)
                            if alerts_on and not hold and self.mode == "live" else None)
                if decision is not None:
                    self._note_stage(decision)
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

            if self.demo:
                for action in self.tour.due(time.monotonic()):
                    self._demo_action(action, frame.timestamp)

            self._guarded(self._control, frame.timestamp, ff)
            self._guarded(self._record_history, frame.timestamp, state, calibrating)
            self._guarded(self._give_up_calibration, frame.timestamp)
            self._guarded(self._update_mode, time.monotonic(), bool(ff.face_found))

            now = time.monotonic()
            self._fps.append(1.0 / max(now - last, 1e-6))
            last = now
            fps = sum(self._fps) / len(self._fps)
            self._proc.append(time.perf_counter() - t_proc)
            self._guarded(self._watch_rate, now, fps)
            self._guarded(self._check_driver, now)
            self._guarded(self._publish, now, ff, state, calibrating, progress,
                          fps, frame.timestamp - t_start, lms)
            self._guarded(self._publish_video, now, frame.image, lms, ff)

            # The laptop preview window is drawn at most window_max_fps times a
            # second. Drawing and showing it every frame cost more than face
            # tracking itself (34 fps without it, 13 with it on a laptop), and
            # the app's video can only be as fast as detection.
            draw_window = (self.show_window and cv2 is not None
                           and now - self._last_window >= self._window_period)
            if draw_window:
                self._last_window = now
                from .viz import draw_overlay
                dash = self.dashboard
                if self.mode != "live":
                    if self._screens is None:
                        from .attract import Screens
                        self._screens = Screens(self.root)
                    # Drawn at the window's own size: stretched, the text went soft.
                    _x, _y, win_w, win_h = cv2.getWindowImageRect("bamnun")
                    size = (win_w, win_h) if win_w > 0 and win_h > 0 else (DASH_W, DASH_H)
                    canvas = (self._screens.standby(now, frame.image, size) if self.mode == "standby"
                              else self._screens.briefing(self._brief_step, now, size))
                else:
                    canvas = draw_overlay(
                        frame.image, lms, ff, state,
                        plan=None if dash else self._plan,
                        alert=None if dash else self._last_alert,
                        # The dashboard's panels say it all; keep the camera clean.
                        ui_cfg={**self.cfg["ui"], "draw_gauges": False} if dash else self.cfg["ui"],
                        fps=fps,
                        calibrating=progress if calibrating else -1.0,
                        cal_stats=(self.features.calibrator.stats(frame.timestamp)
                                   if calibrating and not dash else None),
                    )
                    if dash is not None:
                        if dash.due(frame.timestamp):
                            dash.refresh(ff, state, self._dashboard_data(
                                frame.timestamp, frame.timestamp - t_start, fps,
                                progress if calibrating else -1.0, alerts_on))
                        canvas = dash.compose(canvas)
                        _x, _y, win_w, win_h = cv2.getWindowImageRect("bamnun")
                        canvas = fit_to_window(canvas, win_w, win_h)
                    if self.demo and dash is None:
                        h = canvas.shape[0]
                        label = demo_mode.HELP + ("   [tour running]" if self.tour.running else "")
                        cv2.rectangle(canvas, (0, h - 86), (canvas.shape[1], h - 58), (14, 14, 14), -1)
                        cv2.putText(canvas, label, (12, h - 66), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                    (230, 120, 230), 1, cv2.LINE_AA)
                    scale = float(self.cfg["ui"].get("window_scale", 1.0))
                    if scale != 1.0 and dash is None:
                        canvas = cv2.resize(canvas, None, fx=scale, fy=scale)
                cv2.imshow("bamnun", canvas)
                key = cv2.waitKey(1) & 0xFF
                # Caps Lock or Shift sends the upper case; treat it the same.
                if ord("A") <= key <= ord("Z"):
                    key += 32
                # A click on a dashboard button counts as its key: over Pi
                # Connect, a key press doesn't always reach this window.
                go_next = key == ord(" ")
                while self._clicks:
                    btn = self._clicks.popleft()
                    if btn == "next":
                        go_next = True
                    key = {"calibrate": ord("c"), "fullscreen": ord("f"),
                           "vol_down": ord("-"), "vol_up": ord("=")}.get(btn, key)
                if go_next:
                    self._next(now, frame.timestamp)
                if key == 27 and self.mode != "live":     # Esc: skip to the dashboard
                    self.mode = "live"
                if key == ord("q"):
                    break
                if key == ord("l"):
                    self.dashboard = None if dash else Dashboard(self._dash_refresh_s)
                if key == ord("f"):
                    fullscreen = not fullscreen
                    cv2.setWindowProperty("bamnun", cv2.WND_PROP_FULLSCREEN,
                                          cv2.WINDOW_FULLSCREEN if fullscreen
                                          else cv2.WINDOW_NORMAL)
                if key == ord("c"):
                    self._start_calibration(frame.timestamp)
                    self._voice("calibrate_voice", frame.timestamp)
                    console.print("[cyan]calibration restarted[/]")
                if key in (ord("-"), ord("_")):
                    self.volume.change(-VOLUME_STEP)
                if key in (ord("="), ord("+")):
                    self.volume.change(VOLUME_STEP)
                if key == ord("s"):
                    out = self.logger.dir / f"snap_{int(time.time())}.png"
                    cv2.imwrite(str(out), canvas)
                    console.print(f"snapshot {out}")
                if key == ord("a"):
                    alerts_on = not alerts_on
                    console.print(f"actuators {'on' if alerts_on else 'off'}")
                if self.demo and key != 0xFF and chr(key) in "01234dw":
                    self.tour.stop()
                    self._demo_action(chr(key), frame.timestamp)
                if self.demo and key == ord("t"):
                    self.tour.start(time.monotonic())
                    console.print("[bold magenta]demo[/] tour started")
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
        try:
            self.controller.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("could not close the trip: %s", exc)
        if self.server is not None:
            self.server.stop()
        if self.store is not None:
            self.store.close()
        self.video.close()
        self.logger.close()
        self.policy.close()
        self.air.close()
        self.illuminator.close()
        self.landmarker.close()
        self.source.close()
        try:
            import cv2
            cv2.destroyAllWindows()
        except Exception:
            pass
        console.print("[bold]stopped[/]")


def driver_id(name: str) -> str:
    """A folder name for a driver: their profile name, or "default"."""
    import re
    s = re.sub(r"[^\w-]+", "_", (name or "").strip().lower()).strip("_")
    return s[:40] or "default"


def face_box(lms) -> Optional[list[float]]:
    """The face's bounding box as fractions of the frame, for the Home tile."""
    if lms is None or not getattr(lms, "ok", False):
        return None
    w, h = lms.image_size
    xs, ys = lms.points[:, 0], lms.points[:, 1]
    x0, y0 = max(0.0, float(xs.min()) / w), max(0.0, float(ys.min()) / h)
    x1, y1 = min(1.0, float(xs.max()) / w), min(1.0, float(ys.max()) / h)
    return [x0, y0, x1 - x0, y1 - y0]


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    monitor = None
    try:
        monitor = Monitor(args)
        return monitor.run()
    except KeyboardInterrupt:
        return 130
    finally:
        # run() only reaches shutdown() on a clean exit. An exception in the
        # loop would otherwise leave the IR LED, or a latched blue light, lit
        # with nothing watching it.
        if monitor is not None:
            monitor.illuminator.close()
            monitor.policy.close()


if __name__ == "__main__":
    raise SystemExit(main())
