"""What the camera loop tells the outside world, and the hand-off to the server.

Two rules, both from the spec (docs/SPEC.md, section 0):

1. Video never leaves the Pi. A snapshot carries numbers only, which is also
   what the Privacy screen promises the driver.

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
                   co2_age_s: Optional[float] = None) -> dict[str, Any]:
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

    # -- server side ----------------------------------------------------- #

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
        return dict(snap, age_s=round(age, 2), stale=age > STALE_AFTER_S)

    def health(self) -> dict[str, Any]:
        with self._lock:
            health, at = dict(self._health), self._snapshot_at
        age = None if at is None else time.monotonic() - at
        health["camera_live"] = age is not None and age <= STALE_AFTER_S
        return health

    def events_after(self, seq: int) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e["seq"] > seq]
