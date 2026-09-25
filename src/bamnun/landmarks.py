"""Face landmark extraction.

Wraps the MediaPipe Face Landmarker (478 points, iris refinement included) in
VIDEO running mode so that MediaPipe's own internal tracker carries the face
between frames instead of re-detecting every frame. On a Pi 5 that is the
difference between roughly 8 fps and roughly 25 fps.

Honest caveat for the report: this model was trained on visible-light RGB
faces. A NoIR image under 850 nm illumination is not what it was trained on.
In practice it still tracks, because IR skin is bright and the eye/brow
geometry survives, but detection confidence drops, which is why the
thresholds in the config are lowered to 0.4. If it turns out to be unreliable
on your own IR footage, the fallback is documented in docs/ir_fallback.md:
crop the eye region using the still-reliable coarse face box and classify
open/closed with a small CNN trained on the MRL Eye Dataset, which is itself
IR imagery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

# --------------------------------------------------------------------------- #
# Landmark index sets (MediaPipe canonical face mesh, refined with iris)
#
# "left" / "right" below are the SUBJECT's left and right. Verify once with
# the debug overlay on your own rig; the iris centre indices in particular are
# reported inconsistently across blog posts, and the overlay settles it in
# five seconds.
# --------------------------------------------------------------------------- #

# Six-point EAR sets, in the order (corner, upper1, upper2, corner, lower2, lower1)
RIGHT_EYE_EAR = (33, 160, 158, 133, 153, 144)
LEFT_EYE_EAR = (362, 385, 387, 263, 373, 380)

# Full eyelid rings, used for the overlay and for a more robust opening height.
RIGHT_EYE_RING = (33, 7, 163, 144, 145, 153, 154, 155, 133,
                  173, 157, 158, 159, 160, 161, 246)
LEFT_EYE_RING = (362, 382, 381, 380, 374, 373, 390, 249, 263,
                 466, 388, 387, 386, 385, 384, 398)

RIGHT_IRIS = (469, 470, 471, 472)
LEFT_IRIS = (474, 475, 476, 477)
RIGHT_IRIS_CENTER = 468
LEFT_IRIS_CENTER = 473

# Eye corners used to normalise gaze and to measure interocular distance.
RIGHT_EYE_OUTER, RIGHT_EYE_INNER = 33, 133
LEFT_EYE_INNER, LEFT_EYE_OUTER = 362, 263

# Mouth: inner lip centre pair for the vertical, corners for the horizontal.
MOUTH_TOP, MOUTH_BOTTOM = 13, 14
MOUTH_LEFT, MOUTH_RIGHT = 61, 291

NOSE_TIP = 1
CHIN = 152
FOREHEAD = 10

# Six-point subset used for solvePnP, and a generic 3D face model in
# millimetres to match it. Absolute scale is irrelevant for angles.
#
# The model is expressed in the OPENCV CAMERA CONVENTION: x to the right,
# y DOWNWARD, z away from the camera. The widely copied version of this table
# has y upward, which is the natural way to write it and is wrong here: mixing
# a y-up object frame with OpenCV's y-down camera frame makes solvePnP return
# a pose that is an extra 180 degrees about the x axis, so a driver looking
# straight ahead reads as roll = 180 and yaw = 176 rather than zero. Keeping
# the signs consistent is what makes a frontal face come back as the identity
# rotation. Hence the chin is at POSITIVE y and the eyes at negative y.
PNP_LANDMARKS = (NOSE_TIP, CHIN, LEFT_EYE_OUTER, RIGHT_EYE_OUTER,
                 MOUTH_RIGHT, MOUTH_LEFT)
# The object frame MUST match the camera frame that rotation_matrix_to_euler
# assumes: x right in the image, y down, z away from the lens. Otherwise the
# recovered rotation carries a constant offset.
#
# This table was previously mirrored in both x and z, which is exactly a 180
# degree rotation about the vertical axis, so a driver facing the lens squarely
# came back as yaw = 180 and EVERY frame failed the +-20 deg calibration gate.
# The suite missed it because tests/test_integration.py builds its synthetic
# face by projecting THIS array and then fits THIS array, so the offset
# cancelled and 157 tests passed against a pipeline that could not calibrate a
# real face. Ground truth measured off the sensor, with the face square to the
# camera, is what the signs below encode:
#
#   landmark 263 (subject's LEFT eye)  lands on the image RIGHT -> x > 0
#   landmark  33 (subject's RIGHT eye) lands on the image LEFT  -> x < 0
#   landmark 291 lands on the image RIGHT -> x > 0   (named MOUTH_RIGHT, but
#   landmark  61 lands on the image LEFT  -> x < 0    the mouth constants are
#                                                     image-relative while the
#                                                     eye constants are
#                                                     subject-relative)
#   the nose tip is NEAREST the lens -> it holds the SMALLEST z, so every
#   other point is at positive z, behind it.
PNP_MODEL_3D = np.array(
    [
        [0.0, 0.0, 0.0],          # nose tip, nearest the lens
        [0.0, 63.6, 12.5],        # chin (below the nose -> +y, behind -> +z)
        [43.3, -32.7, 26.0],      # 263, subject's left eye outer -> image right
        [-43.3, -32.7, 26.0],     # 33, subject's right eye outer -> image left
        [28.9, 28.9, 24.1],       # 291, image right
        [-28.9, 28.9, 24.1],      # 61, image left
    ],
    dtype=np.float64,
)


@dataclass(slots=True)
class LandmarkResult:
    """Landmarks for one frame.

    ``points`` is (N, 3) in pixel units for x, y and MediaPipe's
    weakly-metric z (same scale as x). ``normalized`` keeps the raw 0..1
    coordinates for anything resolution-independent.
    """

    points: np.ndarray                 # (478, 3) float32, pixels
    normalized: np.ndarray             # (478, 3) float32, 0..1
    image_size: tuple[int, int]        # (w, h)
    timestamp: float
    blendshapes: Optional[dict[str, float]] = None

    @property
    def ok(self) -> bool:
        return self.points is not None and len(self.points) > 0


class FaceLandmarker:
    """Thin, allocation-light wrapper over mediapipe.tasks FaceLandmarker."""

    def __init__(self, cfg: dict[str, Any], repo_root: Optional[Path] = None) -> None:
        try:
            import mediapipe as mp  # type: ignore
            from mediapipe.tasks import python as mp_python  # type: ignore
            from mediapipe.tasks.python import vision as mp_vision  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "mediapipe is required for landmark extraction: pip install mediapipe"
            ) from exc

        self._mp = mp
        model_path = Path(cfg.get("model_path", "models/face_landmarker.task"))
        if not model_path.is_absolute() and repo_root is not None:
            model_path = repo_root / model_path
        if not model_path.exists():
            raise FileNotFoundError(
                f"landmark model not found at {model_path}\n"
                "Run:  python tools/download_models.py"
            )

        base = mp_python.BaseOptions(model_asset_path=str(model_path))
        options = mp_vision.FaceLandmarkerOptions(
            base_options=base,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=int(cfg.get("num_faces", 1)),
            min_face_detection_confidence=float(cfg.get("min_face_detection_confidence", 0.4)),
            min_face_presence_confidence=float(cfg.get("min_face_presence_confidence", 0.4)),
            min_tracking_confidence=float(cfg.get("min_tracking_confidence", 0.4)),
            output_face_blendshapes=bool(cfg.get("output_blendshapes", False)),
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        self._want_blendshapes = bool(cfg.get("output_blendshapes", False))
        self._last_ms = -1

    def process(self, frame) -> Optional[LandmarkResult]:
        """Run one frame. Returns None when no face is found."""
        import mediapipe as mp

        rgb = frame.as_rgb()
        h, w = rgb.shape[:2]
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # VIDEO mode demands strictly increasing integer milliseconds.
        ts_ms = int(frame.timestamp * 1000.0)
        if ts_ms <= self._last_ms:
            ts_ms = self._last_ms + 1
        self._last_ms = ts_ms

        result = self._landmarker.detect_for_video(mp_image, ts_ms)
        if not result.face_landmarks:
            return None

        lms = result.face_landmarks[0]
        norm = np.array([[p.x, p.y, p.z] for p in lms], dtype=np.float32)
        px = norm.copy()
        px[:, 0] *= w
        px[:, 1] *= h
        px[:, 2] *= w  # z shares the x scale in MediaPipe's convention

        bs = None
        if self._want_blendshapes and result.face_blendshapes:
            bs = {c.category_name: c.score for c in result.face_blendshapes[0]}

        return LandmarkResult(
            points=px,
            normalized=norm,
            image_size=(w, h),
            timestamp=frame.timestamp,
            blendshapes=bs,
        )

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()
