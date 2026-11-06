"""One booth visitor's drive, for their phone (2026 exhibition).

From the end of their calibration this keeps what the app needs to show the
drive as the newest trip in their history: how sleepy they were over time
(a sample every 2 s), each alert and the highest wake-up step, microsleeps,
and two small photos: a profile shot (face centred, eyes open, early in the
drive) and the frame of their first alert ("caught dozing").

Nothing leaves the Pi unless the visitor says yes on the learn-more screen.
Then ``upload`` sends one row to the Supabase table ``visits``
(supabase/booth_visits.sql) with the website's public key, and the visitor's
own QR code opens the website with ``?v=<code>``. Everything is deleted
after the last exhibition day, 24 Nov 2026. A new visitor (NEXT PERSON,
standby) wipes it all from memory with ``reset``.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

import numpy as np

log = logging.getLogger("bamnun.visit")

EXPIRES = "2026-11-24"          # the last exhibition day: shown on screen
SAMPLE_S = 2.0                  # one sleepiness sample this often
PROFILE_AFTER_S = 2.0           # the profile shot: a good frame after this ...
PROFILE_BY_S = 20.0             # ... or the best seen by then
PHOTO_PX = 320                  # photos are this square, as JPEG
ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def read_env(path: Path) -> dict[str, str]:
    """KEY=value lines (frontend/.env, which holds the website's Supabase
    address and public key; not in git)."""
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def face_crop(image: np.ndarray, points: np.ndarray, px: int = PHOTO_PX) -> Optional[bytes]:
    """A square JPEG around the face, with room for the hair and chin."""
    import cv2

    if image is None or points is None or len(points) == 0:
        return None
    h, w = image.shape[:2]
    x0, y0 = points[:, 0].min(), points[:, 1].min()
    x1, y1 = points[:, 0].max(), points[:, 1].max()
    side = max(x1 - x0, y1 - y0) * 1.7
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 - 0.08 * side
    a, b = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    c, d = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
    if c - a < 40 or d - b < 40:
        return None
    crop = image[b:d, a:c]
    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    crop = cv2.resize(crop, (px, int(px * crop.shape[0] / crop.shape[1])), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 78])
    return jpg.tobytes() if ok else None


def _data_url(jpg: Optional[bytes]) -> Optional[str]:
    return None if jpg is None else "data:image/jpeg;base64," + base64.b64encode(jpg).decode()


class Visit:
    """The current visitor. state: none (nothing yet), ask (a photo and a
    drive to offer), uploading, done (``code`` set), declined, failed."""

    def __init__(self, root: Path, website: str) -> None:
        self.root = Path(root)
        self.website = website
        env = read_env(self.root / "frontend" / ".env")
        self.url = env.get("SUPABASE_URL", "").rstrip("/")
        self.key = env.get("SUPABASE_ANON_KEY", "")
        self._counter = self.root / "runs" / "visit_counter.txt"
        self.reset()

    # -- the drive ---------------------------------------------------------- #

    def reset(self) -> None:
        self.started: Optional[float] = None      # monotonic, end of calibration
        self.wall0 = 0.0
        self.trace: list[tuple[float, float]] = []
        self.episodes: list[dict[str, Any]] = []
        self.max_stage = 0
        self.microsleeps = 0
        self.calm_s = 0.0
        self.drive_s = 0.0
        self.photo: Optional[bytes] = None
        self.photo_img: Optional[np.ndarray] = None
        self.caught: Optional[bytes] = None
        self._best = (-1.0, None)
        self._last = None
        self._stage = 0
        self.state = "none"
        self.code: Optional[str] = None
        self.number: Optional[int] = None

    @property
    def active(self) -> bool:
        return self.started is not None

    def start(self, now: float) -> None:
        self.reset()
        self.started, self.wall0 = now, time.time()

    def frame(self, now: float, image, points, *, fit_good: bool, eyes_open: bool,
              score: float, stage: int, microsleeps: int, face: bool) -> None:
        """One frame of the drive (dashboard showing, not calibrating)."""
        if self.started is None:
            return
        el = now - self.started
        dt = 0.0 if self._last is None else min(1.0, max(0.0, now - self._last))
        self._last = now
        if face:
            self.drive_s += dt
            if stage == 0:
                self.calm_s += dt
        if not self.trace or el - self.trace[-1][0] >= SAMPLE_S:
            self.trace.append((round(el, 1), round(float(score), 3)))
            self.trace = self.trace[-600:]
        if stage > 0 and self._stage == 0:          # a new alert
            self.episodes.append({"at": round(self.wall0 + el, 1), "max_stage": stage})
            if self.caught is None and points is not None:
                self.caught = face_crop(image, points)
        if stage > 0 and self.episodes:
            self.episodes[-1]["max_stage"] = max(self.episodes[-1]["max_stage"], stage)
        self._stage = stage
        self.max_stage = max(self.max_stage, stage)
        self.microsleeps = max(self.microsleeps, microsleeps)
        # The profile shot: the first good frame after a moment, else the
        # most centred-and-open one by PROFILE_BY_S.
        if self.photo is None and points is not None and face:
            q = (1.0 if fit_good else 0.4) * (1.0 if eyes_open else 0.2)
            if el >= PROFILE_AFTER_S and q >= 1.0:
                self._take_profile(image, points)
            elif q > self._best[0]:
                self._best = (q, (image.copy(), points.copy()))
            if self.photo is None and el >= PROFILE_BY_S and self._best[1] is not None:
                self._take_profile(*self._best[1])
        if self.photo is not None and self.state == "none" and el >= 10.0:
            self.state = "ask"

    def _take_profile(self, image, points) -> None:
        import cv2

        self.photo = face_crop(image, points)
        if self.photo is not None:
            self.photo_img = cv2.imdecode(np.frombuffer(self.photo, np.uint8), cv2.IMREAD_COLOR)
        self._best = (-1.0, None)

    # -- what goes to the phone --------------------------------------------- #

    def _next_number(self) -> int:
        try:
            n = int(self._counter.read_text().strip()) + 1
        except (OSError, ValueError):
            n = 1
        try:
            self._counter.parent.mkdir(parents=True, exist_ok=True)
            self._counter.write_text(str(n))
        except OSError:
            pass
        return n

    def payload(self) -> dict[str, Any]:
        end = self.wall0 + (self._last - self.started
                             if self._last is not None and self.started is not None else 0.0)
        alerts = len(self.episodes)
        return {
            "v": 1, "number": self.number, "expires": EXPIRES,
            "photo": _data_url(self.photo), "caught": _data_url(self.caught),
            "trip": {
                "started_at": round(self.wall0, 1), "ended_at": round(end, 1),
                "route": {"from": "Bamnun booth", "to": "Exhibition", "booth": True},
                "trace": self.trace,
                "summary": {
                    "duration_s": round(end - self.wall0, 1), "drive_s": round(self.drive_s, 1),
                    "calm_s": round(self.calm_s, 1),
                    "alert_free": round(self.calm_s / self.drive_s, 4) if self.drive_s > 0 else None,
                    "alerts": alerts, "max_stage": self.max_stage, "microsleeps": self.microsleeps,
                    "breaks": 0, "break_s": 0, "longest_calm_s": round(self.calm_s, 1),
                    "episodes": self.episodes[-50:],
                },
            },
        }

    def link(self) -> str:
        return f"{self.website.split('?')[0].rstrip('/')}/?v={self.code}"

    def upload(self) -> None:
        """Yes on the screen: send it in the background; state goes to done
        (``code`` set) or failed."""
        if self.state != "ask":
            return
        if not (self.url and self.key):
            log.warning("no SUPABASE_URL / SUPABASE_ANON_KEY in frontend/.env; can't upload")
            self.state = "failed"
            return
        self.state = "uploading"
        self.number = self._next_number()
        code = "".join(secrets.choice(ALPHABET) for _ in range(10))
        body = json.dumps({"code": code, "payload": self.payload()}).encode()

        def send() -> None:
            req = urllib.request.Request(
                self.url + "/rest/v1/visits", data=body, method="POST",
                headers={"apikey": self.key, "Authorization": "Bearer " + self.key,
                         "Content-Type": "application/json", "Prefer": "return=minimal"})
            try:
                with urllib.request.urlopen(req, timeout=12) as r:
                    ok = 200 <= r.status < 300
            except Exception as exc:  # noqa: BLE001
                log.warning("visit upload failed: %s", exc)
                ok = False
            if self.state == "uploading":        # not reset meanwhile
                self.code = code if ok else None
                self.state = "done" if ok else "failed"

        threading.Thread(target=send, name="visit-upload", daemon=True).start()

    def decline(self) -> None:
        """No: the photos go at once."""
        self.photo = self.photo_img = self.caught = None
        self.state = "declined"
