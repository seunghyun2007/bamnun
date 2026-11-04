"""The Pi's own storage: driver profile, settings and trips, in SQLite.

docs/SPEC.md, section 0: the Pi is the master copy, so the device behaves
correctly with the phone off. The phone keeps a cache and pushes changes.

Two kinds of caller, and the rule that keeps the camera loop fast:

* The server thread reads and writes directly. A few milliseconds on the SD
  card is fine there.
* The camera loop never touches the disk itself. It hands writes to
  ``later()``, which runs them on a writer thread of their own.

Stdlib only, like telemetry.py.
"""

from __future__ import annotations

import copy
import json
import logging
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("bamnun.store")

# Section 4: the vehicle sets these defaults, all editable later.
VEHICLES: dict[str, dict[str, Any]] = {
    "long_haul": {"volume": "high", "break_every_min": 120, "break_len_min": 15,
                  "mount_cm": [50, 70]},
    "delivery": {"volume": "high", "break_every_min": 120, "break_len_min": 0,
                 "mount_cm": [50, 70]},
    "bus": {"volume": "medium", "break_every_min": 120, "break_len_min": 15,
            "mount_cm": [50, 70]},
    "taxi": {"volume": "medium", "break_every_min": 120, "break_len_min": 0,
             "mount_cm": [40, 60]},
    "car": {"volume": "medium", "break_every_min": 120, "break_len_min": 0,
            "mount_cm": [40, 60]},
}

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "",
    "vehicle": "long_haul",
    "work": {"days": [True, True, True, True, True, False, False],
             "start": "22:00", "end": "06:00", "variable": False},
    "voice_lang": "en",
    "app_lang": "en",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    # The light and the alarm are always on (the Ladder screen says "Always").
    "ladder": {"mint": True, "voice": True},
    "sensitivity": "normal",
    "volume": "high",
    "break_every_min": 120,
    "break_len_min": 15,
    "co2_alert": True,
    "emergency": {
        "contact_name": "",
        "contact_phone": "",
        # Off by default. Even on, the phone only opens the dialer, and never
        # with a real emergency number in this build (see the frontend).
        "call_services": False,
        # Demo: run the whole flow, but only show what would be sent.
        "demo": True,
    },
}

SENSITIVITIES = ("gentle", "normal", "strict")
VOLUMES = ("low", "medium", "high")
LANGS = ("en", "ko")
NAME_MAX = 20


class InvalidUpdate(ValueError):
    pass


def _hhmm(v: Any) -> str:
    s = str(v)
    try:
        h, m = s.split(":")
        h, m = int(h), int(m)
    except ValueError:
        raise InvalidUpdate(f"time must be HH:MM, not {s!r}") from None
    if not (0 <= h < 24 and 0 <= m < 60):
        raise InvalidUpdate(f"time out of range: {s!r}")
    return f"{h:02d}:{m:02d}"


def _merge(base: dict, patch: dict, path: str = "") -> dict:
    """Merge ``patch`` into a copy of ``base``; unknown keys are an error."""
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if k not in base:
            raise InvalidUpdate(f"unknown field {path}{k}")
        if isinstance(base[k], dict):
            if not isinstance(v, dict):
                raise InvalidUpdate(f"{path}{k} must be an object")
            out[k] = _merge(base[k], v, f"{path}{k}.")
        else:
            out[k] = v
    return out


def clean_profile(p: dict[str, Any]) -> dict[str, Any]:
    p["name"] = str(p.get("name") or "").strip()[:NAME_MAX]
    if p["vehicle"] not in VEHICLES:
        raise InvalidUpdate(f"vehicle must be one of {sorted(VEHICLES)}")
    for k in ("voice_lang", "app_lang"):
        if p[k] not in LANGS:
            raise InvalidUpdate(f"{k} must be en or ko")
    w = p["work"]
    days = w.get("days")
    if not (isinstance(days, list) and len(days) == 7):
        raise InvalidUpdate("work.days must be 7 true/false values, Monday first")
    w["days"] = [bool(d) for d in days]
    w["start"], w["end"] = _hhmm(w["start"]), _hhmm(w["end"])
    w["variable"] = bool(w["variable"])
    return p


def clean_settings(s: dict[str, Any]) -> dict[str, Any]:
    s["ladder"] = {k: bool(v) for k, v in s["ladder"].items()}
    if s["sensitivity"] not in SENSITIVITIES:
        raise InvalidUpdate(f"sensitivity must be one of {SENSITIVITIES}")
    if s["volume"] not in VOLUMES:
        raise InvalidUpdate(f"volume must be one of {VOLUMES}")
    try:
        s["break_every_min"] = int(s["break_every_min"])
        s["break_len_min"] = int(s["break_len_min"])
    except (TypeError, ValueError):
        raise InvalidUpdate("break times must be whole minutes") from None
    if not 0 <= s["break_every_min"] <= 600:
        raise InvalidUpdate("break_every_min must be 0 (off) to 600")
    s["co2_alert"] = bool(s["co2_alert"])
    e = s["emergency"]
    e["contact_name"] = str(e["contact_name"] or "").strip()[:40]
    # Digits only (and a leading +); the phone formats it for display.
    raw = str(e["contact_phone"] or "").strip()
    e["contact_phone"] = (("+" if raw.startswith("+") else "")
                          + "".join(c for c in raw if c.isdigit()))[:16]
    e["call_services"] = bool(e["call_services"])
    e["demo"] = bool(e["demo"])
    return s


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript("""
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    tz_min INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '{}',
                    route TEXT);
                CREATE TABLE IF NOT EXISTS trip_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trip_id INTEGER NOT NULL REFERENCES trips(id),
                    at REAL NOT NULL,
                    kind TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS trip_events_trip ON trip_events(trip_id);
            """)
        self._jobs: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=1000)
        self._writer: Optional[threading.Thread] = None

    # -- profile and settings ------------------------------------------- #

    def _get(self, key: str, default: dict) -> dict:
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return copy.deepcopy(default)
        try:
            saved = json.loads(row["value"])
        except ValueError:
            return copy.deepcopy(default)
        # Fields added in a later version get their defaults.
        merged = copy.deepcopy(default)
        for k, v in saved.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k].update({kk: vv for kk, vv in v.items() if kk in merged[k]})
            elif k in merged:
                merged[k] = v
        return merged

    def _put(self, key: str, value: dict) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)",
                             (key, json.dumps(value, ensure_ascii=False)))

    def profile(self) -> dict[str, Any]:
        p = self._get("profile", DEFAULT_PROFILE)
        p["owl_name"] = "Ollie"     # fixed; there is no owl-name field
        return p

    def settings(self) -> dict[str, Any]:
        return self._get("settings", DEFAULT_SETTINGS)

    def update_profile(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge and save. A new vehicle also resets its settings defaults."""
        patch = {k: v for k, v in patch.items() if k != "owl_name"}
        with self._lock:
            old = self._get("profile", DEFAULT_PROFILE)
            new = clean_profile(_merge(old, patch))
            self._put("profile", new)
            # The defaults already match the default vehicle, so only a change
            # needs applying.
            if new["vehicle"] != old["vehicle"]:
                v = VEHICLES[new["vehicle"]]
                self.update_settings({k: v[k] for k in
                                      ("volume", "break_every_min", "break_len_min")})
        return self.profile()

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            new = clean_settings(_merge(self.settings(), patch))
            self._put("settings", new)
        return new

    # -- trips ------------------------------------------------------------ #

    def max_trip_id(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(id) AS m FROM trips").fetchone()
        return int(row["m"] or 0)

    def insert_trip(self, trip_id: int, started_at: float, tz_min: int = 0) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO trips(id, started_at, tz_min) VALUES(?, ?, ?)",
                             (trip_id, started_at, int(tz_min)))

    def save_trip(self, trip_id: int, summary: dict[str, Any],
                  ended_at: Optional[float] = None) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE trips SET summary=?, ended_at=COALESCE(?, ended_at) "
                             "WHERE id=?", (json.dumps(summary), ended_at, trip_id))

    def set_route(self, trip_id: int, route: Optional[dict[str, Any]]) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE trips SET route=? WHERE id=?",
                             (None if route is None else json.dumps(route, ensure_ascii=False),
                              trip_id))

    def add_event(self, trip_id: int, at: float, kind: str, data: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO trip_events(trip_id, at, kind, data) VALUES(?,?,?,?)",
                             (trip_id, at, kind, json.dumps(data, ensure_ascii=False)))

    def close_open_trips(self, now: float) -> int:
        """Trips left open by a crash or power cut end at their last save."""
        with self._lock, self._db:
            rows = self._db.execute("SELECT id, started_at, summary FROM trips "
                                    "WHERE ended_at IS NULL").fetchall()
            for r in rows:
                try:
                    dur = float(json.loads(r["summary"]).get("duration_s", 0.0))
                except ValueError:
                    dur = 0.0
                self._db.execute("UPDATE trips SET ended_at=? WHERE id=?",
                                 (r["started_at"] + dur, r["id"]))
            return len(rows)

    @staticmethod
    def _trip_row(r: sqlite3.Row) -> dict[str, Any]:
        return {"id": r["id"], "started_at": r["started_at"], "ended_at": r["ended_at"],
                "tz_min": r["tz_min"], "open": r["ended_at"] is None,
                "summary": json.loads(r["summary"] or "{}"),
                "route": json.loads(r["route"]) if r["route"] else None}

    def trips(self, since: Optional[float] = None, limit: int = 100) -> list[dict[str, Any]]:
        q = "SELECT * FROM trips"
        args: list[Any] = []
        if since is not None:
            q += " WHERE started_at >= ?"
            args.append(since)
        q += " ORDER BY started_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        return [self._trip_row(r) for r in rows]

    def trip(self, trip_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            r = self._db.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
            if r is None:
                return None
            ev = self._db.execute("SELECT at, kind, data FROM trip_events WHERE trip_id=? "
                                  "ORDER BY at", (trip_id,)).fetchall()
        out = self._trip_row(r)
        out["events"] = [{"at": e["at"], "kind": e["kind"], **json.loads(e["data"])}
                         for e in ev]
        return out

    # -- writes from the camera loop ------------------------------------- #

    def later(self, fn: Callable[..., Any], *args: Any) -> None:
        """Run a write on the writer thread. Never blocks; drops if swamped."""
        try:
            self._jobs.put_nowait((fn, args))
        except queue.Full:
            log.warning("store queue full; dropped %s", getattr(fn, "__name__", fn))
            return
        if self._writer is None or not self._writer.is_alive():
            self._writer = threading.Thread(target=self._write_loop,
                                            name="bamnun-store", daemon=True)
            self._writer.start()

    def _write_loop(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job is None:
                    return
                fn, args = job
                try:
                    fn(*args)
                except Exception as exc:  # noqa: BLE001
                    log.warning("store write failed: %r", exc)
            finally:
                self._jobs.task_done()

    def flush(self, timeout: float = 5.0) -> None:
        """Wait for queued writes (shutdown and tests)."""
        end = time.monotonic() + timeout
        while self._jobs.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.01)

    def close(self) -> None:
        self.flush()
        if self._writer is not None and self._writer.is_alive():
            self._jobs.put(None)
            self._writer.join(2.0)
        with self._lock:
            self._db.close()
