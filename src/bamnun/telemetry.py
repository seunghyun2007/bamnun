"""What the camera loop tells the outside world, and the hand-off to the server.

Two rules, both from the spec (docs/SPEC.md, section 0):

1. Video only goes to the driver's phone, and only while someone watches.
   A snapshot carries numbers only. Camera frames are a separate channel:
   the loop encodes them only while ``wants_video`` is true, that is while
   the Camera screen is open, and nothing here records or stores them.

2. The camera loop never waits on a client. It only ever calls ``publish``
   and ``emit`` on the Hub, which take a lock for a few microseconds and
   cannot block on the network. The server thread reads from the Hub at its
   own pace. A slow phone, a crashed server or no server at all changes
   nothing about when the ladder fires.

Everything here is stdlib-only so the camera loop has no dependency on the
web stack; ``server.py`` is the only module that imports FastAPI.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Optional

# A snapshot older than this means the camera loop has stopped publishing:
# the camera is unplugged, the loop has hung, or the program is calibrating
# with no face in view for a long time. The app shows it as "no camera".
STALE_AFTER_S = 2.0


def _r(x: Optional[float], nd: int) -> Optional[float]:
    return None if x is None else round(float(x), nd)


def build_snapshot(ff, state, *, stage: int, stage_name: str, calibrated: bool,
                   calibrating: bool, cal_progress: float, trip_s: float,
                   fps: float, last_blink_s: Optional[float] = None,
                   co2_ppm: Optional[float] = None,
                   co2_age_s: Optional[float] = None,
                   face_box: Optional[list[float]] = None,
                   time_risk: Optional[dict] = None,
                   fps_capacity: Optional[float] = None) -> dict[str, Any]:
    """One frame's state as plain JSON-ready values. Field list: SPEC.md, section 1.

    Ocular values are ``None`` unless they were actually measured on this
    frame. A FeatureFrame without a face carries defaults (ear_norm = 1.0),
    and sending those would show "eyes open" over an empty seat, the same
    mistake viz.py already guards against on the overlay.
    """
    face = bool(ff.face_found)
    measured = face and not calibrating
    return {
        "type": "snapshot",
        "face": face,
        "eye_open": _r(ff.ear_norm, 3) if measured else None,
        "eye_closed": bool(ff.eye_closed) if measured else None,
        "blink_rate": _r(ff.blink_rate_per_min, 1) if measured else None,
        "perclos": _r(ff.perclos, 4) if measured else None,
        "last_blink_s": _r(last_blink_s, 2),
        "microsleep": bool(state.microsleep_now),
        "stage": int(stage),
        "stage_name": str(stage_name),
        "level": int(state.level),
        "level_name": str(state.level_name),
        "score": _r(state.score, 3),
        "kss": _r(state.kss, 1),
        # The same score as 0-100, and the driver's state in one word, decided
        # here so every screen and the laptop overlay agree (SPEC.md, 13).
        "drowsiness": int(round(100 * float(state.score))) if measured else None,
        "label": ("no_face" if not face else "alert") if calibrating else str(getattr(state, "label", "alert")),
        "signals": ({k: [_r(v, 3), _r(state.contributions.get(k, 0.0) * 100, 1)]
                     for k, v in getattr(state, "signals", {}).items()} or None) if measured else None,
        "face_box": [_r(x, 3) for x in face_box] if face_box and face else None,
        # Time-of-day risk is shown on its own; it never changes the camera
        # score or the ladder (SPEC.md, 15).
        "time_risk": time_risk,
        "fps_capacity": _r(fps_capacity, 1),
        "unreliable": getattr(ff, "unreliable", "") if measured else None,
        "distracted": bool(state.distracted),
        "distraction_reason": str(state.distraction_reason),
        "yaw": _r(ff.yaw, 1) if face and ff.pose_valid else None,
        "off_road": bool(ff.off_road) if measured else None,
        "calibrated": bool(calibrated),
        "calibrating": bool(calibrating),
        "cal_progress": _r(cal_progress, 3) if calibrating else None,
        "co2_ppm": _r(co2_ppm, 0),
        "co2_age_s": _r(co2_age_s, 1),
        "trip_s": _r(trip_s, 1),
        "fps": _r(fps, 1),
    }


def alert_event(decision, previous_stage: int) -> dict[str, Any]:
    """An ``alert`` message for a change of ladder stage."""
    return {
        "type": "alert",
        "stage": int(decision.stage),
        "stage_name": str(decision.stage_name),
        "previous": int(previous_stage),
        "reason": str(decision.message or ""),
        "fired": [a.actuator for a in decision.fired],
        "time": time.time(),
    }


class Hub:
    """Latest snapshot, latest health, and a short log of events.

    Written by the camera loop, read by the server. Events get a sequence
    number so each WebSocket client can ask for "everything after N" without
    the Hub tracking clients.
    """

    def __init__(self, max_events: int = 200) -> None:
        self._lock = threading.Lock()
        self._snapshot: Optional[dict[str, Any]] = None
        self._snapshot_at: Optional[float] = None
        self._health: dict[str, Any] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._seq = 0
        self.client_hello: Optional[dict[str, Any]] = None
        # Live video for the Camera screen. ``video_capable`` says a real
        # camera feeds this Hub (false for the simulated driver).
        self.video_capable = False
        self.video_size: Optional[list[int]] = None
        self._jpeg: Optional[bytes] = None
        self._jpeg_seq = 0
        self._viewers = 0
        # Commands from the phone, drained by the camera loop (control.py).
        self._commands: deque[dict[str, Any]] = deque(maxlen=100)
        # The phone's clock and time zone, from its ``hello``: the Pi has no
        # reliable clock of its own (SPEC.md, section 1).
        self.clock_offset_s = 0.0
        self.tz_min = 0
        # Written by the controller about once a second, read by the server.
        self.trip_live: Optional[dict[str, Any]] = None
        self.cal_state: Optional[dict[str, Any]] = None

    # -- camera loop side ------------------------------------------------ #

    def publish(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._snapshot_at = time.monotonic()

    def set_health(self, health: dict[str, Any]) -> None:
        with self._lock:
            self._health = dict(health)

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            self._events.append(dict(event, seq=self._seq))

    def wants_video(self) -> bool:
        """True while at least one Camera screen is watching."""
        with self._lock:
            return self._viewers > 0

    def publish_frame(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg
            self._jpeg_seq += 1

    def take_commands(self) -> list[dict[str, Any]]:
        with self._lock:
            out = list(self._commands)
            self._commands.clear()
        return out

    # -- server side ----------------------------------------------------- #

    def command(self, cmd: dict[str, Any]) -> None:
        with self._lock:
            self._commands.append(dict(cmd))

    def set_client_clock(self, phone_ms: Any, tz_min: Any = None) -> None:
        """Trust the phone's clock over the Pi's (no RTC, often no NTP)."""
        try:
            self.clock_offset_s = float(phone_ms) / 1000.0 - time.time()
        except (TypeError, ValueError):
            return
        # Within a few seconds is "the same"; don't jitter the trip times.
        if abs(self.clock_offset_s) < 5.0:
            self.clock_offset_s = 0.0
        if tz_min is not None:
            try:
                self.tz_min = int(tz_min)
            except (TypeError, ValueError):
                pass


    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def latest(self) -> Optional[dict[str, Any]]:
        """The newest snapshot, stamped with its age, or None before the first."""
        with self._lock:
            snap, at = self._snapshot, self._snapshot_at
        if snap is None or at is None:
            return None
        age = time.monotonic() - at
        return dict(snap, age_s=round(age, 2), stale=age > STALE_AFTER_S,
                    video=self.video_capable, video_size=self.video_size)

    def health(self) -> dict[str, Any]:
        with self._lock:
            health, at = dict(self._health), self._snapshot_at
        age = None if at is None else time.monotonic() - at
        health["camera_live"] = age is not None and age <= STALE_AFTER_S
        health["video"] = self.video_capable
        return health

    def add_viewer(self) -> None:
        with self._lock:
            self._viewers += 1

    def remove_viewer(self) -> None:
        with self._lock:
            self._viewers = max(0, self._viewers - 1)
            if self._viewers == 0:
                self._jpeg = None       # don't keep a picture of the driver around

    def latest_frame(self) -> tuple[int, Optional[bytes]]:
        with self._lock:
            return self._jpeg_seq, self._jpeg

    def events_after(self, seq: int) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e["seq"] > seq]
