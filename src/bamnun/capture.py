"""Frame sources.

One interface, three backends, so that the whole pipeline can be developed on a
laptop webcam today and moved to the IMX708 NoIR on the Pi 5 by changing one
line of config.

Design note worth putting in the report: everything downstream of this module
consumes a single ``Frame`` record with a monotonic timestamp. Nothing else in
the codebase knows or cares whether the pixels came from a sensor or a file.
That is what makes the recorded-session replay honest: identical code path.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

# cv2 is imported lazily inside the backends that need it so that the pure
# maths modules remain importable in a bare test environment.


@dataclass(slots=True)
class Frame:
    """A single captured image plus the clock reading that goes with it."""

    image: np.ndarray          # HxWx3 BGR, or HxW uint8 if grayscale
    timestamp: float           # seconds, monotonic
    index: int                 # frame counter since source open
    dropped: int = 0           # frames the backend reports as lost before this one

    @property
    def is_gray(self) -> bool:
        return self.image.ndim == 2

    def as_rgb(self) -> np.ndarray:
        """MediaPipe wants RGB. Convert once, here, and cache nothing."""
        import cv2

        if self.is_gray:
            return cv2.cvtColor(self.image, cv2.COLOR_GRAY2RGB)
        return cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB)


class FrameSource(ABC):
    """Abstract frame producer."""

    def __init__(self) -> None:
        self._index = 0

    @abstractmethod
    def _grab(self) -> Optional[np.ndarray]:
        """Return the next image, or None when the source is exhausted."""

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def resolution(self) -> tuple[int, int]: ...

    def read(self) -> Optional[Frame]:
        img = self._grab()
        if img is None:
            return None
        frame = Frame(image=img, timestamp=time.monotonic(), index=self._index)
        self._index += 1
        return frame

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __iter__(self):
        while True:
            frame = self.read()
            if frame is None:
                return
            yield frame


# --------------------------------------------------------------------------- #
# Raspberry Pi camera (IMX708 NoIR)
# --------------------------------------------------------------------------- #

class PiCameraSource(FrameSource):
    """picamera2 backend with all automatic algorithms pinned.

    Why pin them: the IR scene is low-contrast and nearly monochrome. Leaving
    AE/AWB/AF running produces slow oscillation in apparent eye size, which
    shows up directly as EAR drift and fake blinks. A fixed exposure of a few
    milliseconds also freezes head motion, which matters more than absolute
    brightness for landmark stability.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__()
        try:
            from picamera2 import Picamera2  # type: ignore
        except ImportError as exc:  # pragma: no cover - Pi only
            raise RuntimeError(
                "picamera2 not available. On Raspberry Pi OS install it with\n"
                "    sudo apt install -y python3-picamera2\n"
                "and create the venv with --system-site-packages."
            ) from exc

        pc = cfg.get("picamera", {})
        size = tuple(pc.get("sensor_mode_size", (1536, 864)))
        fps = float(cfg.get("fps", 30))

        self._cam = Picamera2()
        # 'lores'/'main' split is unnecessary here; one stream keeps latency low.
        video_cfg = self._cam.create_video_configuration(
            main={"size": size, "format": "RGB888"},
            controls={"FrameDurationLimits": (int(1e6 / fps), int(1e6 / fps))},
            buffer_count=4,
        )
        self._cam.configure(video_cfg)

        controls: dict[str, Any] = {}
        if pc.get("lock_exposure", True):
            controls["AeEnable"] = False
            controls["ExposureTime"] = int(pc.get("exposure_time_us", 8000))
            controls["AnalogueGain"] = float(pc.get("analogue_gain", 4.0))
        if pc.get("lock_awb", True):
            controls["AwbEnable"] = False
            controls["ColourGains"] = tuple(pc.get("colour_gains", (1.0, 1.0)))
        if pc.get("manual_focus", True):
            # AfMode 0 == Manual. IMX708 is a voice-coil AF module; letting it
            # hunt at 20 cm is the single worst thing you can do to landmarks.
            controls["AfMode"] = 0
            controls["LensPosition"] = float(pc.get("lens_position", 4.5))
        nr = str(pc.get("noise_reduction", "fast")).lower()
        if nr in {"off", "fast", "high_quality"}:
            controls["NoiseReductionMode"] = {"off": 0, "fast": 1, "high_quality": 2}[nr]

        self._cam.set_controls(controls)
        self._cam.start()
        time.sleep(0.4)  # let the pipeline settle before the first read

        self._size = size
        self._gray = bool(cfg.get("grayscale_input", False))
        self._flip = bool(cfg.get("flip_horizontal", False))
        self._last_seq = -1
        self._dropped = 0

    def _grab(self) -> Optional[np.ndarray]:
        import cv2

        request = self._cam.capture_request()
        try:
            img = request.make_array("main")
            meta = request.get_metadata()
        finally:
            request.release()

        seq = meta.get("SensorTimestamp", None)
        if seq is not None and self._last_seq >= 0:
            pass  # sequence gaps could be counted here if the driver exposes them
        self._last_seq = seq if seq is not None else self._last_seq

        # picamera2 "RGB888" actually hands back BGR-ordered bytes. Keep BGR.
        if self._flip:
            img = cv2.flip(img, 1)
        if self._gray:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    @property
    def resolution(self) -> tuple[int, int]:
        return self._size

    def set_lens_position(self, dioptres: float) -> None:
        """Exposed so the focus-sweep tool can find the sharpest setting."""
        self._cam.set_controls({"AfMode": 0, "LensPosition": float(dioptres)})

    def set_exposure(self, exposure_us: int, gain: float) -> None:
        self._cam.set_controls(
            {"AeEnable": False, "ExposureTime": int(exposure_us), "AnalogueGain": float(gain)}
        )

    def close(self) -> None:
        try:
            self._cam.stop()
            self._cam.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Laptop webcam
# --------------------------------------------------------------------------- #

class WebcamSource(FrameSource):
    """OpenCV VideoCapture. Development stand-in for the IMX708."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__()
        import cv2

        device = cfg.get("device", 0)
        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            raise RuntimeError(f"could not open webcam device {device!r}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg.get("width", 1280)))
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg.get("height", 720)))
        self._cap.set(cv2.CAP_PROP_FPS, float(cfg.get("fps", 30)))
        # Shallow buffer keeps the newest frame; a deep one adds latency that
        # makes the alert feel sluggish in a live demo.
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        self._gray = bool(cfg.get("grayscale_input", False))
        self._flip = bool(cfg.get("flip_horizontal", False))
        self._size = (
            int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    def _grab(self) -> Optional[np.ndarray]:
        import cv2

        ok, img = self._cap.read()
        if not ok:
            return None
        if self._flip:
            img = cv2.flip(img, 1)
        if self._gray:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    @property
    def resolution(self) -> tuple[int, int]:
        return self._size

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Recorded file
# --------------------------------------------------------------------------- #

class VideoFileSource(FrameSource):
    """Replay a recording.

    Two modes matter. ``realtime=True`` paces playback to the file's fps, which
    is what you want when demonstrating the alert timing. ``realtime=False``
    runs flat out, which is what you want when re-scoring twenty recorded
    sessions after changing a threshold.
    """

    def __init__(self, cfg: dict[str, Any], realtime: bool = True, loop: bool = False) -> None:
        super().__init__()
        import cv2

        path = Path(str(cfg.get("device", "")))
        if not path.exists():
            raise FileNotFoundError(path)
        self._cap = cv2.VideoCapture(str(path))
        if not self._cap.isOpened():
            raise RuntimeError(f"could not open video {path}")

        self._path = path
        self._loop = loop
        self._realtime = realtime
        self._src_fps = self._cap.get(cv2.CAP_PROP_FPS) or float(cfg.get("fps", 30))
        self._dt = 1.0 / max(self._src_fps, 1.0)
        self._next_due = None
        self._gray = bool(cfg.get("grayscale_input", False))
        self._size = (
            int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    def _grab(self) -> Optional[np.ndarray]:
        import cv2

        ok, img = self._cap.read()
        if not ok:
            if self._loop:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, img = self._cap.read()
            if not ok:
                return None

        if self._realtime:
            now = time.monotonic()
            if self._next_due is None:
                self._next_due = now
            sleep_for = self._next_due - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._next_due += self._dt

        if self._gray:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    @property
    def resolution(self) -> tuple[int, int]:
        return self._size

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass


# --------------------------------------------------------------------------- #

class ArraySource(FrameSource):
    """Feed a pre-built list of images. Used by the test suite."""

    def __init__(self, images: list[np.ndarray], dt: float = 1 / 30) -> None:
        super().__init__()
        self._images = images
        self._dt = dt
        self._t = 0.0

    def _grab(self) -> Optional[np.ndarray]:
        if self._index >= len(self._images):
            return None
        return self._images[self._index]

    def read(self) -> Optional[Frame]:
        img = self._grab()
        if img is None:
            return None
        frame = Frame(image=img, timestamp=self._t, index=self._index)
        self._index += 1
        self._t += self._dt
        return frame

    @property
    def resolution(self) -> tuple[int, int]:
        if not self._images:
            return (0, 0)
        h, w = self._images[0].shape[:2]
        return (w, h)

    def close(self) -> None:
        pass


def open_source(cfg: dict[str, Any], **kwargs) -> FrameSource:
    """Factory. ``cfg`` is the ``capture`` block of the config file."""
    kind = str(cfg.get("source", "webcam")).lower()
    if kind == "picamera":
        return PiCameraSource(cfg)
    if kind == "webcam":
        return WebcamSource(cfg)
    if kind == "video":
        return VideoFileSource(cfg, **kwargs)
    raise ValueError(f"unknown capture source {kind!r}")
