"""The product film on the booth screen.

While nobody is driving, the Pi's screen loops the team's film (muted), so
people reading the poster see it. The staff remote's "영상 재생" plays it from
the start with sound (through the device's speaker); "영상 정지" stops it.

The film is assets/booth/film.mp4 (720p, no sound) with its soundtrack in
assets/booth/film.wav, copied to the Pi by hand: they show people, so they
are not in the public repo. Without them the film is simply off.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("bamnun.film")


class Film:
    def __init__(self, root: Path) -> None:
        self.video = Path(root) / "assets" / "booth" / "film.mp4"
        self.audio = Path(root) / "assets" / "booth" / "film.wav"
        self._cap = None
        self._fps = 30.0
        self._index = -1                 # the last frame read
        self._frame: Optional[np.ndarray] = None
        self.started: Optional[float] = None
        self.sound = False
        self._proc: Optional[subprocess.Popen] = None

    @property
    def available(self) -> bool:
        return self.video.exists()

    @property
    def playing(self) -> bool:
        return self.started is not None

    def start(self, now: float, sound: bool = False) -> bool:
        """Play from the start; with ``sound``, the soundtrack too."""
        import cv2

        self.stop()
        if not self.available:
            return False
        self._cap = cv2.VideoCapture(str(self.video))
        if not self._cap.isOpened():
            log.warning("can't open %s", self.video)
            self._cap = None
            return False
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._index, self._frame = -1, None
        self.started, self.sound = now, sound
        if sound and self.audio.exists() and shutil.which("aplay"):
            try:
                self._proc = subprocess.Popen(["aplay", "-q", str(self.audio)],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                log.warning("film sound: %s", exc)
        return True

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self.started = None

    def frame(self, now: float) -> tuple[Optional[np.ndarray], bool]:
        """The frame for this moment, and whether the film has ended (a film
        with sound ends; a muted one loops)."""
        if self._cap is None or self.started is None:
            return None, True
        want = int((now - self.started) * self._fps)
        while self._index < want:
            ok, f = self._cap.read()
            if not ok:                               # the end
                if self.sound:
                    return self._frame, True
                self._cap.set(1, 0)                  # loop (CAP_PROP_POS_FRAMES)
                self.started, self._index = now, -1
                want = 0
                continue
            self._index += 1
            self._frame = f
        return self._frame, False
