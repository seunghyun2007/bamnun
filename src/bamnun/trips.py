"""Trips: what one drive looked like, kept on the Pi, and the Insights maths.

A trip starts when a calibrated driver is first seen (or the phone says
"Start trip") and ends after ``end_after_s`` with nobody in the seat (or the
phone says "End trip", or the program stops). An empty seat for at least
``break_min_s`` in between is a break, which also resets the break reminder.

``TripTracker.tick`` runs in the camera loop. It only does arithmetic; every
write goes through ``Store.later`` so the loop never waits on the SD card.

Times: the loop runs on a monotonic clock, and the Pi has no reliable wall
clock (no RTC, often no internet). ``wall`` is whatever the caller trusts
most, normally the Pi's clock corrected by the phone's ``hello``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .store import Store

SAVE_EVERY_S = 30.0


@dataclass
class TripConfig:
    auto_start: bool = True
    break_min_s: float = 180.0      # empty seat this long counts as a break
    end_after_s: float = 900.0      # empty seat this long ends the trip

    @classmethod
    def from_cfg(cls, d: Optional[dict[str, Any]]) -> "TripConfig":
        d = d or {}
        return cls(auto_start=bool(d.get("auto_start", True)),
                   break_min_s=float(d.get("break_min_s", 180.0)),
                   end_after_s=float(d.get("end_after_s", 900.0)))


@dataclass
class Trip:
    id: int
    started_at: float               # wall clock
    t0: float                       # loop clock
    tz_min: int = 0
    drive_s: float = 0.0
    calm_s: float = 0.0
    calm_run_s: float = 0.0
    longest_calm_s: float = 0.0
    max_stage: int = 0
    microsleeps: int = 0
    breaks: int = 0
    break_s: float = 0.0
    co2_max: Optional[float] = None
    emergencies: int = 0
    episodes: list[dict[str, Any]] = field(default_factory=list)
    last_seen_t: float = 0.0
    route: Optional[dict[str, Any]] = None
    open_episode: Optional[dict[str, Any]] = None   # an alert still going on

    def summary(self, now_t: float) -> dict[str, Any]:
        return {
            "duration_s": round(max(0.0, self.last_seen_t - self.t0), 1),
            "drive_s": round(self.drive_s, 1),
            "calm_s": round(self.calm_s, 1),
            "alert_free": round(self.calm_s / self.drive_s, 4) if self.drive_s > 0 else None,
            "longest_calm_s": round(max(self.longest_calm_s, self.calm_run_s), 1),
            "alerts": len(self.episodes) + (self.open_episode is not None),
            "max_stage": self.max_stage,
            "microsleeps": self.microsleeps,
            "breaks": self.breaks,
            "break_s": round(self.break_s, 1),
            "co2_max": None if self.co2_max is None else round(self.co2_max),
            "emergencies": self.emergencies,
            "episodes": self.episodes[-200:],
        }


class TripTracker:
    def __init__(self, store: Optional[Store], cfg: Optional[TripConfig] = None,
                 on_event=None) -> None:
        self.store = store
        self.cfg = cfg or TripConfig()
        self.on_event = on_event          # phone messages (``trip``)
        self.trip: Optional[Trip] = None
        self._next_id = self._first_free_id()
        self._away_since: Optional[float] = None
        self._on_break = False
        self._last_t: Optional[float] = None
        self._last_save = -1e9
        self._stage = 0
        self.last_break_t: Optional[float] = None   # loop clock, for reminders

    def _first_free_id(self) -> int:
        return 1 if self.store is None else self.store.max_trip_id() + 1

    # -- lifecycle --------------------------------------------------------- #

    def start(self, t: float, wall: float, tz_min: int = 0, why: str = "auto") -> Trip:
        if self.trip is not None:
            return self.trip
        trip = Trip(id=self._next_id, started_at=wall, t0=t, tz_min=tz_min, last_seen_t=t)
        self._next_id += 1
        self.trip = trip
        self._away_since = None
        self._on_break = False
        self.last_break_t = t
        if self.store is not None:
            self.store.later(self.store.insert_trip, trip.id, wall, tz_min)
        self._emit({"type": "trip", "event": "started", "id": trip.id,
                    "started_at": wall, "why": why})
        return trip

    def end(self, t: float, wall: float, why: str = "ended") -> Optional[dict[str, Any]]:
        trip = self.trip
        if trip is None:
            return None
        self._close_episode(wall)
        if self._away_since is None:
            trip.last_seen_t = t
        summary = trip.summary(t)
        ended_at = trip.started_at + summary["duration_s"]
        self._save(trip, t, ended_at)
        self.trip = None
        self._away_since = None
        self._emit({"type": "trip", "event": "ended", "id": trip.id, "why": why,
                    "ended_at": ended_at, "summary": _public(summary)})
        return summary

    def set_route(self, route: Optional[dict[str, Any]]) -> bool:
        if self.trip is None:
            return False
        self.trip.route = route
        if self.store is not None:
            self.store.later(self.store.set_route, self.trip.id, route)
        return True

    def log(self, wall: float, kind: str, data: dict[str, Any]) -> None:
        if self.trip is not None and self.store is not None:
            self.store.later(self.store.add_event, self.trip.id, wall, kind, data)

    # -- per frame ---------------------------------------------------------- #

    def tick(self, t: float, wall: float, *, face: bool, calibrated: bool, stage: int,
             microsleep_started: bool = False, co2_ppm: Optional[float] = None,
             tz_min: int = 0) -> None:
        dt = 0.0 if self._last_t is None else max(0.0, min(t - self._last_t, 1.0))
        self._last_t = t

        if self.trip is None:
            if face and calibrated and self.cfg.auto_start:
                self.start(t, wall, tz_min)
            self._stage = stage
            return
        trip = self.trip

        if face:
            if self._away_since is not None:
                away = t - self._away_since
                if self._on_break:
                    trip.breaks += 1
                    trip.break_s += away
                    self.last_break_t = t
                    self.log(wall, "break", {"duration_s": round(away, 1)})
                self._away_since = None
                self._on_break = False
            trip.last_seen_t = t
        else:
            if self._away_since is None:
                self._away_since = t
            away = t - self._away_since
            if not self._on_break and away >= self.cfg.break_min_s:
                self._on_break = True
                self._close_episode(wall)
            if away >= self.cfg.end_after_s:
                self.end(t, wall, why="seat empty")
                return

        if not self._on_break:
            trip.drive_s += dt
            if stage == 0:
                trip.calm_s += dt
                trip.calm_run_s += dt
            else:
                trip.longest_calm_s = max(trip.longest_calm_s, trip.calm_run_s)
                trip.calm_run_s = 0.0

        if stage > self._stage:
            if trip.open_episode is None:
                trip.open_episode = {"at": round(wall, 1), "max_stage": stage}
            trip.open_episode["max_stage"] = max(trip.open_episode["max_stage"], stage)
            self.log(wall, "alert", {"stage": stage, "from": self._stage})
        elif stage == 0 and self._stage > 0:
            self._close_episode(wall)
        trip.max_stage = max(trip.max_stage, stage)
        self._stage = stage

        if microsleep_started:
            trip.microsleeps += 1
            self.log(wall, "microsleep", {})
        if co2_ppm is not None:
            trip.co2_max = co2_ppm if trip.co2_max is None else max(trip.co2_max, co2_ppm)

        if t - self._last_save >= SAVE_EVERY_S:
            self._save(trip, t)

    def note_emergency(self, wall: float, data: dict[str, Any]) -> None:
        if self.trip is not None:
            self.trip.emergencies += 1
        self.log(wall, "emergency", data)

    def drive_since_break_s(self, t: float) -> float:
        if self.trip is None or self.last_break_t is None:
            return 0.0
        return t - self.last_break_t

    # -- internals ---------------------------------------------------------- #

    def _close_episode(self, wall: float) -> None:
        trip = self.trip
        if trip is not None and trip.open_episode is not None:
            trip.open_episode["ended"] = round(wall, 1)
            trip.episodes.append(trip.open_episode)
            trip.open_episode = None

    def _save(self, trip: Trip, t: float, ended_at: Optional[float] = None) -> None:
        self._last_save = t
        if self.store is not None:
            self.store.later(self.store.save_trip, trip.id, trip.summary(t), ended_at)

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001
                pass

    def live(self, t: float) -> Optional[dict[str, Any]]:
        """The open trip, for the API: summary so far plus the route."""
        if self.trip is None:
            return None
        return {"id": self.trip.id, "started_at": self.trip.started_at, "open": True,
                "summary": _public(self.trip.summary(t)), "route": self.trip.route}


def _public(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in summary.items() if k != "episodes"}


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #

RANGES = {"week": 7, "month": 30, "all": None}


def _local(ts: float, tz_min: int) -> datetime:
    return datetime.fromtimestamp(ts, timezone(timedelta(minutes=tz_min)))


def insights(store: Store, range_: str = "week", now: Optional[float] = None,
             tz_min: int = 0) -> dict[str, Any]:
    """Numbers for the Insights screen, from the saved trips."""
    now = time.time() if now is None else now
    days = RANGES.get(range_, 7)
    since = None if days is None else now - days * 86400.0
    trips = [t for t in store.trips(since=since, limit=1000)]
    prev = ([] if days is None else
            [t for t in store.trips(since=since - days * 86400.0, limit=1000)
             if t["started_at"] < since])

    def share(ts: list[dict[str, Any]]) -> Optional[float]:
        drive = sum(t["summary"].get("drive_s", 0.0) for t in ts)
        calm = sum(t["summary"].get("calm_s", 0.0) for t in ts)
        return round(calm / drive, 4) if drive > 0 else None

    episodes = [e for t in trips for e in t["summary"].get("episodes", [])]
    hours = [0] * 24
    for e in episodes:
        hours[_local(e["at"], tz_min).hour] += 1
    woke = [0, 0, 0, 0]
    for e in episodes:
        s = int(e.get("max_stage", 1))
        if 1 <= s <= 4:
            woke[s - 1] += 1

    # Alerts per day for a week, per week for a month or more.
    per: list[dict[str, Any]] = []
    today = _local(now, tz_min).date()
    if days == 7:
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            n = sum(1 for e in episodes if _local(e["at"], tz_min).date() == d)
            drove = any(_local(t["started_at"], tz_min).date() == d for t in trips)
            per.append({"date": d.isoformat(), "weekday": d.weekday(), "alerts": n,
                        "drove": drove})
    else:
        if days == 30:
            weeks = 5
        else:
            first = min((t["started_at"] for t in trips), default=now)
            weeks = max(1, min(12, int((now - first) // (7 * 86400)) + 1))
        for i in range(weeks - 1, -1, -1):
            end = today - timedelta(days=7 * i)
            start = end - timedelta(days=6)
            n = sum(1 for e in episodes
                    if start <= _local(e["at"], tz_min).date() <= end)
            drove = any(start <= _local(t["started_at"], tz_min).date() <= end
                        for t in trips)
            per.append({"date": start.isoformat(), "alerts": n, "drove": drove})

    peak = max(range(24), key=lambda h: hours[h]) if any(hours) else None
    return {
        "range": range_,
        "trips": len(trips),
        "drive_s": round(sum(t["summary"].get("drive_s", 0.0) for t in trips), 1),
        "alerts": len(episodes),
        "alert_free": share(trips),
        "alert_free_prev": share(prev),
        "longest_calm_s": max((t["summary"].get("longest_calm_s", 0.0) for t in trips),
                              default=0.0),
        "per": per,
        "hours": hours,
        "peak_hour": peak,
        "woke_by": woke,
        "first_step_enough": woke[0],
        "microsleeps": sum(t["summary"].get("microsleeps", 0) for t in trips),
        "breaks": sum(t["summary"].get("breaks", 0) for t in trips),
    }
