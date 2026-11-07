"""Everything the phone can ask the device to do, run inside the camera loop.

The server never touches the pipeline. It drops commands into the Hub; the
camera loop calls ``Controller.tick`` once a frame, which drains them, and
runs the slower jobs that sit beside detection (docs/SPEC.md):

* applying the driver's settings to the ladder (sections 1 and 4),
* Ollie's voice on the device speaker (sections 2 and 6),
* the guided calibration and device test (section 8),
* trips and the break reminder (sections 1 and 9),
* the emergency trigger after an unanswered alarm (section 9b).

Nothing in here blocks: sound plays on worker threads, the disk is written by
the store's writer thread, and the phone hears about results over ``/ws``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .alerts import AtomizerActuator, AudioActuator, EscalationPolicy, LightActuator, NullActuator
from .store import Store
from .telemetry import Hub
from .trips import TripConfig, TripTracker
from .voice import LINES, Speaker

log = logging.getLogger("bamnun.control")

# Section 9b.
EMERGENCY_AFTER_S = 20.0
# After the break reminder, remind again this often until a break is taken.
BREAK_REPEAT_S = 15 * 60.0
# Ladder toggles in the app -> actuators they silence. The light and the
# rising alarm are always on.
LADDER_ACTUATORS = {"mint": ["scent"], "voice": ["warn"]}
VOLUME_PCT = {"low": 60, "medium": 80, "high": 100}
TEST_PARTS = ("speaker", "chime", "blue_light", "mist", "alarm")


def part_state(act) -> str:
    """ok (real hardware), simulated (a stub), or missing."""
    if act is None or not act.available:
        return "missing"
    if isinstance(act, NullActuator):
        return "simulated"
    if isinstance(act, AudioActuator):
        return "ok" if act._player and act.present else "simulated"
    return "ok" if getattr(act, "_dev", None) is not None else "simulated"


def set_volume(level: str) -> None:
    """Best effort: the Pi's mixer, on a thread. Absent on a laptop."""
    pct = VOLUME_PCT.get(level)
    amixer = shutil.which("amixer")
    if pct is None or amixer is None:
        return

    def run():  # pragma: no cover - hardware only
        for control in ("Master", "PCM", "Speaker"):
            try:
                r = subprocess.run([amixer, "-q", "sset", control, f"{pct}%"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=3)
                if r.returncode == 0:
                    return
            except Exception:  # noqa: BLE001
                return

    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- #
# Guided calibration (section 8)
# --------------------------------------------------------------------------- #


class FeatureCalibration:
    """The guided flow's view of the real FeatureExtractor (SPEC.md, 15)."""

    def __init__(self, features, on_commit: Optional[Callable[[], None]] = None) -> None:
        self.f = features
        self.on_commit = on_commit

    def start(self, t: float) -> None:
        self._attempts0 = self.f.calibrator.attempts
        self.f.start_calibration(t, hold=True)

    def cancel(self) -> None:
        self.f.cancel_calibration()

    def progress(self, t: float) -> float:
        return self.f.calibrator.progress(t)

    def ready(self) -> bool:
        if self.f.hold:
            return self.f.candidate is not None
        return not self.f.calibrator.active and self.f.calibration.complete

    def failures(self) -> int:
        return self.f.calibrator.attempts - getattr(self, "_attempts0", 0)

    def failure(self) -> str:
        return str(self.f.calibrator.last_failure or "")

    def failure_code(self) -> str:
        return str(self.f.calibrator.failure_code or "")

    def start_closed(self, t: float) -> None:
        self.f.start_closed(t)

    def finish_closed(self) -> tuple[bool, str, str]:
        return self.f.finish_closed()

    def hint(self) -> str:
        return self.f.calibrator.hint

    def summary(self) -> dict:
        cal = self.f.candidate or self.f.calibration
        return cal.summary() if cal is not None else {}

    def commit(self) -> None:
        self.f.commit_candidate()
        if self.on_commit is not None:
            self.on_commit()


@dataclass
class _Step:
    key: str
    line: str
    ask: bool = False          # waits for Yes / No from the phone


STEPS = [
    _Step("position", "cal_position"),
    _Step("look", "cal_look"),
    _Step("close", "cal_close"),
    _Step("speaker", "cal_hear", ask=True),
    _Step("chime", "cal_chime", ask=True),
    _Step("light", "cal_light", ask=True),
    _Step("mist", "cal_mist", ask=True),
    _Step("done", "cal_done"),
]
STEP_KEYS = [s.key for s in STEPS]

POSITION_STEADY_S = 2.0
NO_FACE_NAG_S = 15.0
POSITION_GIVE_UP_S = 90.0
CLOSE_LEAD_S = 1.5         # the line plays before the eyes are measured
CLOSE_WINDOW_S = 3.0       # eyes closed for this long (the first 0.7 s is them closing)
STEP_TRIES = 3             # a failed look-ahead or eyes-closed step is redone up to twice
# The ladder holds while the driver closes their eyes on request, and a
# moment after, or the calibration itself would set off the alarm.
CLOSE_HOLD_AFTER_S = 2.0


class GuidedCalibration:
    """Steps 1-8 of section 8, as a state machine ticked by the camera loop."""

    def __init__(self, cal, say: Callable[[str], None], emit: Callable[[dict], None],
                 fire_part: Callable[[str], str]) -> None:
        self.cal = cal
        self.say = say
        self.emit = emit
        self.fire_part = fire_part
        self.active = False
        self.idx = 0
        self.results: dict[str, str] = {}
        self.message = ""
        self._entered = 0.0
        self._face_since: Optional[float] = None
        self._last_nag = 0.0
        self._closed_s = 0.0
        self._last_t: Optional[float] = None
        self._look_retried = False
        self._last_progress_emit = -1e9
        self._answer: Optional[bool] = None
        self.started_wall: Optional[float] = None
        self.reason = ""           # a plain sentence when a step needs redoing
        self.summary: Optional[dict] = None
        self._tries = 0
        self._closed_started = False
        self._last_hint = ""
        self._close_left_at: Optional[float] = None

    def holds_ladder(self, t: float) -> bool:
        """True while the eyes are closed on purpose for the "close" step."""
        if self.active and self.step == "close":
            return True
        return self._close_left_at is not None and t - self._close_left_at < CLOSE_HOLD_AFTER_S

    @property
    def step(self) -> Optional[str]:
        return STEP_KEYS[self.idx] if self.active else None

    def state(self, t: Optional[float] = None) -> dict[str, Any]:
        prog = None
        if self.active and t is not None:
            if self.step == "look":
                prog = round(self.cal.progress(t), 3)
            elif self.step == "close":
                prog = round(max(0.0, min(1.0, (t - self._entered - CLOSE_LEAD_S) / CLOSE_WINDOW_S)), 3)
            elif self.step == "position" and self._face_since is not None:
                prog = round(min(1.0, (t - self._face_since) / POSITION_STEADY_S), 3)
        hint = getattr(self.cal, "hint", lambda: "")()
        return {"type": "calibration", "active": self.active, "step": self.step,
                "index": self.idx, "steps": STEP_KEYS, "results": dict(self.results),
                "progress": prog, "message": self.message, "reason": self.reason,
                "hint": hint if self.active and self.step in ("position", "look", "close") else "",
                "summary": self.summary,
                "ask": bool(self.active and STEPS[self.idx].ask)}

    def start(self, t: float) -> None:
        if self.active:
            self.cal.cancel()
        self.active = True
        self.results = {}
        self.summary = None
        self._tries = 0
        self.started_wall = time.time()
        self._enter(0, t)

    def cancel(self, t: float) -> None:
        if not self.active:
            return
        if self.step == "close":
            self._close_left_at = t
        self.cal.cancel()
        self.active = False
        self.message = "cancelled"
        self.emit(self.state(t))

    def answer(self, step: str, ok: bool) -> None:
        if self.active and self.step == step and STEPS[self.idx].ask:
            self._answer = bool(ok)

    def _enter(self, idx: int, t: float, message: str = "") -> None:
        if self.active and self.step == "close" and STEP_KEYS[idx] != "close":
            self._close_left_at = t
        if message != "retry":
            self._tries = 0         # a fresh step; a retry keeps its count
        self.idx = idx
        self._entered = t
        self._answer = None
        self.message = message
        if not message:
            self.reason = ""
        step = STEPS[idx]
        self.say(step.line)
        if step.key == "look":
            self.cal.start(t)
        elif step.key == "close":
            self._closed_started = False
        elif step.key == "position":
            self._face_since = None
            self._last_nag = t
        elif step.key in ("chime", "light", "mist"):
            self.results[step.key + "_fired"] = self.fire_part(
                {"chime": "chime", "light": "blue_light", "mist": "mist"}[step.key])
        elif step.key == "done":
            self.active = False
            self.message = "done"
        self.emit(self.state(t))

    def _fail(self, t: float, step: str, why: str) -> None:
        if step == "close":
            self._close_left_at = t
        self.results[step] = "fail"
        self.message = why
        self.cal.cancel()
        self.active = False
        self.emit(dict(self.state(t), failed=step))

    def tick(self, t: float, face: bool, ear_raw: Optional[float]) -> None:
        dt = 0.0 if self._last_t is None else max(0.0, min(t - self._last_t, 0.5))
        self._last_t = t
        if not self.active:
            return
        key = self.step
        since = t - self._entered

        hint = getattr(self.cal, "hint", lambda: "")()
        if hint != self._last_hint and key in ("position", "look", "close"):
            self._last_hint = hint
            self.emit(self.state(t))

        if key == "position":
            if face and not hint:
                self._face_since = self._face_since if self._face_since is not None else t
                if t - self._face_since >= POSITION_STEADY_S:
                    self.results["position"] = "ok"
                    self._enter(1, t)
            else:
                self._face_since = None
                if t - self._last_nag >= NO_FACE_NAG_S:
                    self._last_nag = t
                    self.say("cal_no_face")
                    self.message = "no_face"
                    self.emit(self.state(t))
                if since >= POSITION_GIVE_UP_S:
                    self._fail(t, "position", "no_face")
        elif key == "look":
            if self.cal.ready():
                self.results["look"] = "ok"
                self._enter(2, t)
            elif self.cal.failures() > self._tries:
                # The calibrator found a problem (too dark, moving, no face)
                # and restarted the step: say why, and give up after 3 tries.
                self._tries = self.cal.failures()
                self.reason = self.cal.failure()
                if self._tries >= STEP_TRIES:
                    self._fail(t, "look", getattr(self.cal, "failure_code", lambda: "")() or "tracking")
                else:
                    self.message = "retry"
                    self.say("cal_look")
                    self.emit(self.state(t))
            elif t - self._last_progress_emit >= 0.5:
                self._last_progress_emit = t
                self.emit(self.state(t))
        elif key == "close":
            if since >= CLOSE_LEAD_S and not self._closed_started:
                self._closed_started = True
                self.cal.start_closed(t)
            if since >= CLOSE_LEAD_S + CLOSE_WINDOW_S:
                ok, code, why = self.cal.finish_closed()
                if ok:
                    self.results["close"] = "ok"
                    self.summary = self.cal.summary()
                    self.cal.commit()
                    self._enter(3, t)
                else:
                    self._tries += 1
                    self.reason = why
                    if self._tries >= STEP_TRIES:
                        self._fail(t, "close", code or "separation")
                    else:
                        self._enter(2, t, message="retry")
            elif t - self._last_progress_emit >= 0.5:
                self._last_progress_emit = t
                self.emit(self.state(t))
        elif STEPS[self.idx].ask and self._answer is not None:
            self.results[key] = "ok" if self._answer else "fail"
            self._enter(self.idx + 1, t)


# --------------------------------------------------------------------------- #
# The controller
# --------------------------------------------------------------------------- #


# The booth's four wake-up stages, each as device commands and how long it
# plays: from a phone (server.py) or the "learn more" screen (app.py).
SHOWCASE_STAGES: dict[int, tuple[tuple[dict[str, Any], ...], float]] = {
    1: (({"cmd": "test", "part": "blue_light"},), 4.0),
    2: (({"cmd": "test", "part": "mist"},), 4.0),
    3: (({"cmd": "test", "part": "chime"}, {"cmd": "say", "line": "stage3"}), 6.0),
    4: (({"cmd": "test", "part": "alarm"}, {"cmd": "say", "line": "stage4"}), 6.0),
}


class Controller:
    def __init__(self, hub: Hub, store: Optional[Store], policy: EscalationPolicy,
                 estimator=None, calibration=None, speaker: Optional[Speaker] = None,
                 trip_cfg: Optional[dict[str, Any]] = None, quiet: bool = False) -> None:
        # quiet: the demo booth. The ladder is still worked out and shown (on
        # the big screen and the phones), but nothing fires by itself: no
        # parts, no break reminder, no emergency check. Product control's
        # stage buttons (fire_part, say) still play on demand.
        self.quiet = quiet
        self.hub = hub
        self.store = store
        self.policy = policy
        self.estimator = estimator
        self.speaker = speaker or Speaker(on_say=hub.emit)
        if self.speaker.on_say is None:
            self.speaker.on_say = hub.emit
        self.trips = TripTracker(store, TripConfig.from_cfg(trip_cfg), on_event=hub.emit)
        self.guided = (GuidedCalibration(calibration, self.say, hub.emit, self.fire_part)
                       if calibration is not None else None)
        self.profile: dict[str, Any] = store.profile() if store else {}
        self.settings: dict[str, Any] = store.settings() if store else {}
        self._stage4_since: Optional[float] = None
        self._emergency_sent = False
        self._emergency_seq = 0
        self._next_break_at: Optional[float] = None
        self._was_microsleep = False
        self._last_live = -1e9
        self._t = 0.0
        if store is not None:
            closed = store.close_open_trips(time.time())
            if closed:
                log.info("closed %d trip(s) left open by a restart", closed)
        self.apply()

    # -- time ------------------------------------------------------------ #

    def wall(self) -> float:
        """The Pi's clock corrected by the phone's (SPEC.md, section 1)."""
        return time.time() + self.hub.clock_offset_s

    # -- settings ---------------------------------------------------------- #

    def apply(self) -> None:
        s, p = self.settings, self.profile
        muted: set[str] = set()
        for key, acts in LADDER_ACTUATORS.items():
            if not s.get("ladder", {}).get(key, True):
                muted.update(acts)
        if not s.get("co2_alert", True):
            muted.add("open_window")
        if self.quiet:
            muted.update(self.policy.actuators)
        self.policy.muted = muted
        if self.estimator is not None and hasattr(self.estimator, "set_sensitivity"):
            self.estimator.set_sensitivity(s.get("sensitivity", "normal"))
        AudioActuator.lang = p.get("voice_lang", "en")
        set_volume(s.get("volume", "high"))
        self._next_break_at = None

    def holds_ladder(self, t: float) -> bool:
        """The camera loop skips the ladder while this is true (see above)."""
        return self.guided is not None and self.guided.holds_ladder(t)

    @property
    def voice_lang(self) -> str:
        return self.profile.get("voice_lang", "en")

    def say(self, line: str, lang: Optional[str] = None) -> dict:
        return self.speaker.say(line, lang or self.voice_lang)

    # -- device test ------------------------------------------------------- #

    def fire_part(self, part: str) -> str:
        """Fire one part for the device test. Ignores refractory periods."""
        names = {"chime": "chime", "blue_light": "blue_light", "mist": "scent",
                 "alarm": "alarm"}
        if part == "speaker":
            r = self.say("cal_hear")["result"]
            return {"played": "ok", "simulated": "simulated"}.get(r, "error")
        act = self.policy.actuators.get(names.get(part, ""))
        state = part_state(act)
        if state == "missing":
            return "missing"
        params: dict[str, Any] = {}
        if isinstance(act, LightActuator):
            params = {"hold_s": 3.0}
        elif isinstance(act, AtomizerActuator):
            params = {"duration_s": 2.0}
        try:
            act._do_fire(self._t, **params)
        except Exception as exc:  # noqa: BLE001
            log.warning("device test %s failed: %s", part, exc)
            return "error"
        return state

    # -- commands from the phone ------------------------------------------ #

    def handle(self, cmd: dict[str, Any], t: float, face: bool) -> None:
        kind = cmd.get("cmd")
        if kind == "apply":
            if isinstance(cmd.get("profile"), dict):
                self.profile = cmd["profile"]
            if isinstance(cmd.get("settings"), dict):
                self.settings = cmd["settings"]
            self.apply()
        elif kind == "say":
            line = str(cmd.get("line", ""))
            if line in LINES:
                self.say(line, cmd.get("lang"))
        elif kind == "test":
            part = str(cmd.get("part", ""))
            result = self.fire_part(part) if part in TEST_PARTS else "unknown"
            self.hub.emit({"type": "test_result", "part": part, "result": result})
        elif kind == "cal_start" and self.guided is not None:
            self.guided.start(t)
        elif kind == "cal_cancel" and self.guided is not None:
            self.guided.cancel(t)
        elif kind == "cal_answer" and self.guided is not None:
            self.guided.answer(str(cmd.get("step", "")), bool(cmd.get("ok")))
        elif kind == "trip_start":
            self.trips.start(t, self.wall(), self.hub.tz_min, why="phone")
        elif kind == "trip_end":
            self.trips.end(t, self.wall(), why="phone")
        elif kind == "route":
            self.trips.set_route(cmd.get("route"))
            self.trips.log(self.wall(), "route", {"set": cmd.get("route") is not None})
        elif kind == "emergency_outcome":
            self.trips.log(self.wall(), "emergency_outcome",
                           {"id": cmd.get("id"), "outcome": str(cmd.get("outcome", ""))})
        else:
            log.info("ignored command %r", kind)

    # -- per frame ---------------------------------------------------------- #

    def tick(self, t: float, *, face: bool, calibrated: bool, eye_closed: Optional[bool],
             microsleep: bool, ear_raw: Optional[float] = None,
             co2_ppm: Optional[float] = None) -> None:
        self._t = t
        for cmd in self.hub.take_commands():
            try:
                self.handle(cmd, t, face)
            except Exception as exc:  # noqa: BLE001
                log.warning("command %r failed: %r", cmd.get("cmd"), exc)

        if self.guided is not None:
            self.guided.tick(t, face, ear_raw)

        wall = self.wall()
        stage = self.policy.stage
        if self.holds_ladder(t):
            microsleep = False          # eyes shut on request, not asleep
            eye_closed = False
        started = microsleep and not self._was_microsleep
        self._was_microsleep = microsleep
        self.trips.tick(t, wall, face=face, calibrated=calibrated, stage=stage,
                        microsleep_started=started, co2_ppm=co2_ppm,
                        tz_min=self.hub.tz_min)
        self._break_reminder(t)
        self._emergency(t, wall, face, eye_closed, microsleep)

        if t - self._last_live >= 1.0:
            self._last_live = t
            self.hub.trip_live = self.trips.live(t)
            if self.guided is not None:
                self.hub.cal_state = self.guided.state(t)

    def _break_reminder(self, t: float) -> None:
        if self.quiet:
            return
        every = float(self.settings.get("break_every_min", 120) or 0) * 60.0
        if every <= 0 or self.trips.trip is None:
            self._next_break_at = None
            return
        since = self.trips.drive_since_break_s(t)
        if self._next_break_at is None or since < 1.0:
            self._next_break_at = every
        if since >= self._next_break_at:
            self._next_break_at = since + BREAK_REPEAT_S
            self.say("break_due")
            event = {"type": "reminder", "kind": "break_due",
                     "drive_min": round(since / 60.0)}
            self.hub.emit(event)
            self.trips.log(self.wall(), "reminder", {"kind": "break_due"})

    def _emergency(self, t: float, wall: float, face: bool, eye_closed: Optional[bool],
                   microsleep: bool) -> None:
        top = len(self.policy.stages) - 1
        if self.quiet or self.policy.stage < top:
            self._stage4_since = None
            self._emergency_sent = False
            return
        if self._stage4_since is None:
            self._stage4_since = t
        unresponsive = (not face) or bool(eye_closed) or microsleep
        if (not self._emergency_sent and unresponsive
                and t - self._stage4_since >= EMERGENCY_AFTER_S):
            self._emergency_sent = True
            self._emergency_seq += 1
            e = self.settings.get("emergency", {})
            event = {"type": "emergency", "id": self._emergency_seq, "at": wall,
                     "reason": "no_face" if not face else "eyes_closed",
                     "contact_name": e.get("contact_name", ""),
                     "demo": bool(e.get("demo", True)),
                     "driver": self.profile.get("name", "")}
            self.hub.emit(event)
            self.say("emergency_check")
            self.trips.note_emergency(wall, {"id": event["id"], "reason": event["reason"]})
            log.warning("emergency: no response %.0f s into stage %d",
                        t - self._stage4_since, top)

    def close(self) -> None:
        self.trips.end(self._t, self.wall(), why="stopped")
        self.speaker.close()
        if self.store is not None:
            self.store.flush()
