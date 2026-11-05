"""The Camera screen's video, encoded off the camera loop (docs/SPEC.md, section 13).

The app used to get about 11 frames a second while the laptop overlay showed
29: the camera loop encoded a JPEG itself, and only every 0.1 s, to keep that
cost bounded. Now the loop only hands over the newest frame and its eye
outline points (a memory copy, about 1 ms, and only while someone is
watching), and this thread does the drawing, scaling and encoding. It takes
the newest frame each time it's free, so if it ever falls behind it skips
frames; detection never waits for it. OpenCV releases the GIL while it
resizes and encodes, so the two really do run side by side.
"""

from __future__ import annotations

import threading
import time
from typing import Optional, Sequence

import numpy as np

from .landmarks import LEFT_EYE_RING, RIGHT_EYE_RING

LILAC = (240, 155, 169)     # BGR, eyes open
PINK = (177, 143, 244)      # BGR, eyes shut


def eye_rings(landmarks) -> Optional[list[np.ndarray]]:
    """The two eye outlines, in frame pixels, or None without a face."""
    if landmarks is None or not landmarks.ok:
        return None
    pts = landmarks.points
    rings = []
    for ring in (RIGHT_EYE_RING, LEFT_EYE_RING):
        r = np.array([pts[i][:2] for i in ring if i < len(pts)], dtype=np.float32)
        if len(r) >= 3:
            rings.append(r)
    return rings or None


def encode(image: np.ndarray, rings: Optional[Sequence[np.ndarray]], shut: bool,
           width: int = 640, quality: int = 80) -> bytes:
    """Scale to ``width``, then draw the outlines at that scale, then JPEG.

    Drawing after scaling keeps the lines crisp and exactly on the eyes; the
    points are scaled by the same factor as the picture.
    """
    import cv2

    img = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image
    h, w = img.shape[:2]
    k = 1.0
    if w > width:
        k = width / w
        img = cv2.resize(img, (width, int(round(h * k))), interpolation=cv2.INTER_AREA)
    elif img is image:
        img = img.copy()
    if rings:
        colour = PINK if shut else LILAC
        for r in rings:
            p = np.round(r * k * 16).astype(np.int32)       # 4 fractional bits
            cv2.polylines(img, [p], True, colour, 2, cv2.LINE_AA, shift=4)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    return buf.tobytes() if ok else b""


class VideoEncoder:
    def __init__(self, hub, width: int = 640, quality: int = 80, max_fps: float = 30.0) -> None:
        self.hub = hub
        self.width, self.quality = int(width), int(quality)
        self.min_period = 1.0 / max(1.0, float(max_fps))
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._job: Optional[tuple] = None
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self.encoded = 0
        self.fps = 0.0

    def offer(self, image: np.ndarray, landmarks, shut: bool) -> None:
        """Called by the camera loop every frame. Cheap, never blocks."""
        if not self.hub.wants_video():
            return
        job = (image.copy(), eye_rings(landmarks), bool(shut))
        with self._lock:
            self._job = job
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="bamnun-video", daemon=True)
            self._thread.start()
        self._wake.set()

    def _run(self) -> None:
        last = 0.0
        t0, n = time.monotonic(), 0
        while not self._stop:
            if not self._wake.wait(1.0):
                if not self.hub.wants_video():
                    return      # nobody watching: the thread ends, offer() restarts it
                continue
            self._wake.clear()
            with self._lock:
                job, self._job = self._job, None
            if job is None:
                continue
            wait = self.min_period - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            try:
                jpeg = encode(*job, width=self.width, quality=self.quality)
            except Exception:  # noqa: BLE001 - a bad frame must not end the stream
                continue
            if jpeg:
                self.hub.publish_frame(jpeg)
                self.encoded += 1
                n += 1
                if last - t0 >= 2.0:
                    self.fps, t0, n = n / (last - t0), last, 0

    def close(self) -> None:
        self._stop = True
        self._wake.set()
