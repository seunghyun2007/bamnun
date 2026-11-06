"""Debug overlay.

Dual purpose. During development it is how you see why the detector did what
it did. At the exhibition it is the entire visible product, because a judge
standing at your table cannot see a GPIO pin go high. Budget real effort here:
the overlay IS the demo.

Kept deliberately cheap. Drawing the full 478-point mesh costs several
milliseconds per frame on a Pi 5 and adds nothing a judge can read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

from .landmarks import (FACE_OUTLINES, LEFT_EYE_RING, LEFT_IRIS_CENTER, RIGHT_EYE_RING,
                        RIGHT_IRIS_CENTER)

# BGR. Monochrome base with one accent per severity keeps it legible on a
# projector and readable in a poster photograph.
_WHITE = (255, 255, 255)
_GREY = (150, 150, 150)
_DARK = (30, 30, 30)
_LEVEL_COLOURS = [
    (120, 200, 120),   # alert
    (60, 200, 240),    # mild
    (40, 140, 250),    # drowsy
    (50, 50, 240),     # severe
    (160, 40, 230),    # extreme (fifth level, when configured)
]


_FONT = 0  # cv2.FONT_HERSHEY_SIMPLEX, spelled numerically to avoid an import here

# Below this many characters of retained text, an elided label is noise rather
# than information, and is dropped instead of drawn. See _shorten.
_MIN_INFORMATIVE_CHARS = 3


def _colour_for_level(level: int):
    return _LEVEL_COLOURS[min(max(level, 0), len(_LEVEL_COLOURS) - 1)]


def _text_w(text: str, scale: float, thickness: int = 1) -> int:
    """Measured pixel width of a string.

    Right-aligned labels were previously positioned as ``w - 16 - 8*len(text)``,
    a per-character width guess. Hershey glyphs are not fixed width, so the
    estimate was wrong by tens of pixels and the rest-plan line ran off the
    right edge of the frame: the demo read "...in about 18 mir". Measure it.
    """
    import cv2

    (tw, _th), _base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX,
                                       scale, thickness)
    return int(tw)


def _draw_right(img, text: str, right_x: int, y: int, scale: float,
                colour, thickness: int = 1, min_x: int = 0) -> bool:
    """Right-align ``text`` so it ends at ``right_x``.

    Returns False and draws nothing if the string is empty, or will not fit to
    the right of ``min_x``, which is how the overlay avoids stacking the
    rest-plan text on top of the state panel.
    """
    import cv2

    if not text:
        return False
    x = right_x - _text_w(text, scale, thickness)
    if x < min_x:
        return False
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, colour,
                thickness, cv2.LINE_AA)
    return True


def _shorten(text: str, max_px: int, scale: float, thickness: int = 1,
             min_chars: int = _MIN_INFORMATIVE_CHARS) -> str:
    """Trim with an ellipsis until the string fits in ``max_px``.

    Returns ``""`` when the budget cannot hold at least ``min_chars`` of real
    text. A bare ``"..."`` is only 10 px wide, so without this floor every
    budget looks satisfiable: a 18 px gutter yielded ``"p..."``, which told the
    driver nothing and defeated ``_draw_right``'s ``min_x`` guard, because a
    10 px string always fits where a 200 px one does not.
    """
    if _text_w(text, scale, thickness) <= max_px:
        return text
    trimmed = text
    while trimmed and _text_w(trimmed + "...", scale, thickness) > max_px:
        trimmed = trimmed[:-1]
    if len(trimmed) < min_chars:
        return ""
    return trimmed + "..."


def _bar(img, x: int, y: int, w: int, h: int, frac: float, colour,
         label: str = "", threshold: Optional[float] = None) -> None:
    import cv2

    frac = float(max(0.0, min(1.0, frac)))
    cv2.rectangle(img, (x, y), (x + w, y + h), _DARK, -1)
    cv2.rectangle(img, (x, y), (x + int(w * frac), y + h), colour, -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), _GREY, 1)
    if threshold is not None:
        tx = x + int(w * max(0.0, min(1.0, threshold)))
        cv2.line(img, (tx, y - 2), (tx, y + h + 2), _WHITE, 1)
    if label:
        cv2.putText(img, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.42, _WHITE, 1,
                    cv2.LINE_AA)


# The same words the app shows (SPEC.md, section 13), so the two can be
# compared side by side while testing.
LABEL_TEXT = {"alert": "ALERT", "a_bit": "A BIT TIRED", "drowsy": "DROWSY",
              "very": "VERY DROWSY", "eyes_closed": "EYES CLOSED", "head_drop": "HEAD DROPPING",
              "away": "LOOKING AWAY", "no_face": "NO FACE"}


def video_frame(image: np.ndarray, landmarks, eye_closed: bool,
                width: int = 480, quality: int = 70) -> bytes:
    """One JPEG for the app's Camera screen: the frame plus the eye outlines.

    Deliberately much lighter than draw_overlay: no panel or text, which the
    app draws itself, and scaled down before encoding so it costs a few
    milliseconds and a few tens of kilobytes.
    """
    import cv2

    canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image.copy()
    if landmarks is not None and landmarks.ok:
        pts = landmarks.points
        colour = (177, 143, 244) if eye_closed else (240, 155, 169)   # pink / lilac, BGR
        for ring in (RIGHT_EYE_RING, LEFT_EYE_RING):
            ring_pts = [pts[i][:2] for i in ring
                        if i < len(pts) and (pts[i][0] or pts[i][1])]
            if len(ring_pts) >= 3:
                cv2.polylines(canvas, [np.array(ring_pts, dtype=np.int32)], True,
                              colour, 2, cv2.LINE_AA)
    h, w = canvas.shape[:2]
    if w > width:
        canvas = cv2.resize(canvas, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    return buf.tobytes() if ok else b""


def draw_face_mesh(canvas: np.ndarray, pts, colour=(235, 235, 235)) -> None:
    """The face as the tracker sees it: outlines and every landmark as a dot.

    The dots go in with one array write rather than 478 circles, so the
    whole mesh costs well under a millisecond on the Pi.
    """
    import cv2

    pts = np.asarray(pts)
    if pts.ndim != 2 or len(pts) < 468:
        return
    xy = pts[:, :2]
    ok = (xy[:, 0] > 0) | (xy[:, 1] > 0)      # unset landmarks sit at the origin
    h, w = canvas.shape[:2]
    for ring, closed in FACE_OUTLINES:
        if not all(ok[i] for i in ring):
            continue
        poly = xy[list(ring)].astype(np.int32)
        cv2.polylines(canvas, [poly], closed, colour, 1, cv2.LINE_AA)
    xs = np.clip(xy[ok, 0].astype(np.int32), 0, w - 2)
    ys = np.clip(xy[ok, 1].astype(np.int32), 0, h - 2)
    dot = np.array(colour, np.uint16)
    for dy in (0, 1):                          # 2x2 dots, blended 60 %
        for dx in (0, 1):
            px = canvas[ys + dy, xs + dx].astype(np.uint16)
            canvas[ys + dy, xs + dx] = ((px * 2 + dot * 3) // 5).astype(np.uint8)


def draw_overlay(image: np.ndarray, landmarks, feature_frame, state,
                 plan=None, alert=None, ui_cfg: Optional[dict[str, Any]] = None,
                 fps: float = 0.0, calibrating: float = -1.0,
                 cal_stats: Optional[dict[str, Any]] = None) -> np.ndarray:
    """Return an annotated BGR copy of ``image``."""
    import cv2

    ui_cfg = ui_cfg or {}
    if image.ndim == 2:
        canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        canvas = image.copy()
    h, w = canvas.shape[:2]

    # -- eye geometry --------------------------------------------------- #
    if landmarks is not None and landmarks.ok and ui_cfg.get("draw_eyes", True):
        pts = landmarks.points
        if ui_cfg.get("draw_mesh", False):         # under the eye outlines
            draw_face_mesh(canvas, pts)
        closed_colour = (60, 60, 240) if feature_frame.eye_closed else (120, 220, 120)
        for ring in (RIGHT_EYE_RING, LEFT_EYE_RING):
            # Skip unpopulated points. MediaPipe always returns all 478, but
            # the IR fallback path in docs/ir_fallback.md would not, and an
            # unset landmark at the origin drags a visible line to the corner
            # of the frame rather than failing quietly.
            ring_pts = [pts[i][:2] for i in ring
                        if i < len(pts) and (pts[i][0] or pts[i][1])]
            if len(ring_pts) < 3:
                continue
            poly = np.array(ring_pts, dtype=np.int32)
            cv2.polylines(canvas, [poly], True, closed_colour, 1, cv2.LINE_AA)
        for ic in (RIGHT_IRIS_CENTER, LEFT_IRIS_CENTER):
            if ic < len(pts):
                c = tuple(int(v) for v in pts[ic][:2])
                cv2.circle(canvas, c, 2, (240, 200, 60), -1, cv2.LINE_AA)

    # -- calibration banner --------------------------------------------- #
    if calibrating >= 0.0:
        bar_h = 56 if not cal_stats else 96
        cv2.rectangle(canvas, (0, 0), (w, bar_h), _DARK, -1)
        head = "CALIBRATING  look straight ahead, blink normally"
        attempts = (cal_stats or {}).get("attempts") or 0
        if attempts:
            # Short form, and measured: the long form clipped at 640 px.
            suffix = f"  restart {attempts}"
            if _text_w(head + suffix, 0.62) > w - 32:
                head = "CALIBRATING  look ahead, blink normally"
            head = _shorten(head + suffix, w - 32, 0.62)
        cv2.putText(canvas, head, (16, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (90, 140, 250) if attempts else _WHITE, 1, cv2.LINE_AA)
        _bar(canvas, 16, 36, w - 32, 10, calibrating, (200, 200, 200))

        if cal_stats:
            # Live diagnostics. Without these, a restarting calibration is
            # indistinguishable from a frozen one, and the three causes (no
            # face, head off-axis, frame rate too low) look identical.
            frac = cal_stats.get("fraction", 0.0)
            need = cal_stats.get("need_fraction", 0.4)
            ok = frac >= need
            line = (f"tracked {frac*100:0.0f}% of {cal_stats.get('seen', 0)} frames "
                    f"(need {need*100:0.0f}%)   {cal_stats.get('fps', 0.0):0.1f} fps   "
                    f"raw yaw {cal_stats.get('raw_yaw', 0.0):+0.0f}  "
                    f"pitch {cal_stats.get('raw_pitch', 0.0):+0.0f}")
            cv2.putText(canvas, line, (16, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                        (140, 220, 140) if ok else (90, 140, 250), 1, cv2.LINE_AA)
            if cal_stats.get("rejected_pose"):
                warn = (f"{cal_stats['rejected_pose']} frames rejected for head "
                        f"pose; face the camera squarely")
                cv2.putText(canvas, warn, (16, 88), cv2.FONT_HERSHEY_SIMPLEX,
                            0.44, (90, 140, 250), 1, cv2.LINE_AA)
        return canvas

    # -- state panel ----------------------------------------------------- #
    panel_w, panel_h = 300, 210
    x0, y0 = 12, 12
    panel_right = x0 + panel_w
    if ui_cfg.get("draw_gauges", True):
        overlay = canvas.copy()
        cv2.rectangle(overlay, (x0, y0), (x0 + panel_w, y0 + panel_h), (18, 18, 18), -1)
        cv2.addWeighted(overlay, 0.72, canvas, 0.28, 0, canvas)

        # With no face there is no ocular evidence, so the gauges would be
        # showing the last values they happened to hold. An earlier version
        # rendered "eye open 100% of baseline" over a frame with nobody in it,
        # which is the overlay asserting something it does not know. Dim the
        # panel and say so instead.
        stale = state.face_lost
        colour = _colour_for_level(state.level)
        label_colour = _GREY if stale else _WHITE

        title = LABEL_TEXT.get(getattr(state, "label", ""), state.level_name.upper())
        cv2.putText(canvas, title, (x0 + 12, y0 + 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                    tuple(int(c * 0.45) for c in colour) if stale else colour,
                    2, cv2.LINE_AA)
        _draw_right(canvas, f"{100 * state.score:0.0f}/100", panel_right - 12, y0 + 30,
                    0.5, label_colour, min_x=x0 + 140)

        y = y0 + 56
        if stale:
            cv2.putText(canvas, "no driver in frame", (x0 + 12, y + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (90, 90, 220), 1,
                        cv2.LINE_AA)
            cv2.putText(canvas, f"holding last state ({state.score:0.2f})",
                        (x0 + 12, y + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        _GREY, 1, cv2.LINE_AA)
            y += 66
        else:
            _bar(canvas, x0 + 12, y, panel_w - 24, 12, state.score, colour,
                 f"drowsiness {100 * state.score:0.0f}  (level {state.level_name})",
                 threshold=0.45)
            y += 34
            _bar(canvas, x0 + 12, y, panel_w - 24, 10,
                 feature_frame.perclos / 0.30, _WHITE,
                 f"PERCLOS {feature_frame.perclos*100:0.1f}%", threshold=0.5)
            y += 30
            _bar(canvas, x0 + 12, y, panel_w - 24, 10,
                 feature_frame.ear_norm, _WHITE,
                 f"eye open {feature_frame.ear_norm*100:0.0f}%  (typical "
                 f"{feature_frame.openness*100:0.0f}%)", threshold=0.5)
            y += 32
            cv2.putText(canvas,
                        f"blinks {feature_frame.blink_rate_per_min:0.0f}/min   "
                        f"micro {feature_frame.microsleep_count}   "
                        f"yawns {feature_frame.yawn_count}",
                        (x0 + 12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, _GREY, 1,
                        cv2.LINE_AA)
            y += 18
            cv2.putText(canvas,
                        f"yaw {feature_frame.yaw:+0.0f}  "
                        f"pitch {feature_frame.pitch:+0.0f}  "
                        f"gaze {feature_frame.gaze_h:+0.2f}",
                        (x0 + 12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, _GREY, 1,
                        cv2.LINE_AA)
            y += 18
        cv2.putText(canvas, f"{fps:0.1f} fps   conf {state.confidence:0.2f}",
                    (x0 + 12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, _GREY, 1,
                    cv2.LINE_AA)

    # -- banners --------------------------------------------------------- #
    banner: Optional[tuple[str, tuple[int, int, int]]] = None
    if state.face_lost and state.face_lost_s > 1.5:
        banner = (f"DRIVER NOT VISIBLE  {state.face_lost_s:0.1f}s", (60, 60, 240))
    elif state.microsleep_now:
        banner = (f"EYES CLOSED  {feature_frame.ongoing_closure_s:0.1f}s", (50, 50, 240))
    elif state.distracted:
        banner = (f"EYES OFF ROAD  {state.distraction_reason}", (40, 140, 250))
    elif state.level >= 2:
        banner = ("DROWSY", _colour_for_level(state.level))

    if banner is not None:
        text, colour = banner
        cv2.rectangle(canvas, (0, h - 54), (w, h), (14, 14, 14), -1)
        cv2.putText(canvas, text, (16, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    colour, 2, cv2.LINE_AA)
        cv2.rectangle(canvas, (0, 0), (w - 1, h - 1), colour, 4)

    # -- rest plan ------------------------------------------------------- #
    # Right-aligned and measured, and never allowed to run under the state
    # panel. The available width is what is left to the right of the panel.
    if plan is not None:
        avail = w - 16 - (panel_right + 14)
        msg = _shorten(plan.summary(), avail, 0.5)
        urgent = bool(getattr(plan, "recommend_rest_now", False))
        _draw_right(canvas, msg, w - 16, 30, 0.5,
                    (60, 200, 240) if urgent else _WHITE,
                    min_x=panel_right + 14)
        if plan.valid and plan.time_to_unsafe_s:
            sub = (f"unsafe in ~{plan.time_to_unsafe_s/60:0.0f} min  "
                   f"(conf {plan.confidence:0.2f})")
            _draw_right(canvas, _shorten(sub, avail, 0.42), w - 16, 50, 0.42,
                        _GREY, min_x=panel_right + 14)

    # -- last actuation -------------------------------------------------- #
    if alert is not None and alert.fired:
        names = ", ".join(a.actuator for a in alert.fired)
        txt = _shorten(f"ALERT [{alert.stage_name}] -> {names}", w - 32, 0.55)
        cv2.putText(canvas, txt, (16, h - 64), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (240, 240, 240), 1, cv2.LINE_AA)

    return canvas


# --------------------------------------------------------------------------- #
# Presentation dashboard
# --------------------------------------------------------------------------- #

# The window is scaled to the screen, so every position below is in this fixed
# canvas and the text keeps its size relative to the display.
DASH_W, DASH_H = 1280, 720
_CAM_RECT = (8, 8, 832, 468)              # x, y, w, h
_CHART_Y, _CHART_H = 482, 230
_COL_X, _COL_W = 848, 424
# Buttons drawn over the camera's bottom-right corner, for a mouse or a Pi
# Connect session, where a key press doesn't always reach the window.
_BTN_Y = _CAM_RECT[1] + _CAM_RECT[3] - 46
_BTN_R = _CAM_RECT[0] + _CAM_RECT[2] - 8
BUTTONS = {"vol_down": (_BTN_R - 458, _BTN_Y, 66, 36),
           "vol_up": (_BTN_R - 386, _BTN_Y, 66, 36),
           "calibrate": (_BTN_R - 304, _BTN_Y, 150, 36),
           "fullscreen": (_BTN_R - 146, _BTN_Y, 146, 36),
           # Bottom-left: start over for the next visitor (the briefing again).
           "next_visitor": (_CAM_RECT[0] + 8, _BTN_Y, 196, 36),
           # Above it: straight to the learn-more screen (QR code, stage cards).
           "learn_more": (_CAM_RECT[0] + 8, _BTN_Y - 44, 196, 36)}
_BUTTON_WORDS = {"vol_down": "VOL -", "vol_up": "VOL +",
                 "calibrate": "CALIBRATE (c)", "fullscreen": "FULL SCREEN (f)",
                 "next_visitor": "NEXT PERSON (n)", "learn_more": "QR + STAGES (m)"}

_BG = (12, 12, 14)
_CARD = (28, 28, 32)
_EDGE = (58, 58, 64)
_DIM = (110, 110, 110)
_GOOD = (120, 200, 120)
_WARN = (60, 200, 240)
_BAD = (70, 70, 240)
_BLUE_ON = (240, 150, 60)

_LEVEL_WORDS = {"a_bit": "A BIT", "very": "VERY DROWSY"}
_COMPONENT_WORDS = {"heavy_lids": "heavy lids", "perclos": "eye closure",
                    "blink_duration": "blink length", "long_blinks": "long blinks",
                    "nods": "head nods", "lid_speed": "slow lids", "microsleep": "microsleep",
                    "yawn": "yawning", "blink_rate": "blink rate"}
_CO2_AXIS_FLOOR = 400.0                   # outdoor air; the sensor cannot read less
_CO2_STALE_S = 30.0                       # the sensor reports every 5 s
_PERCLOS_BAR_MAX = 0.30
_EYE_BAR_MAX = 1.5                        # a wide-open eye reads above its baseline
_SCORE_WINDOW_S = 120.0
_CO2_WINDOW_S = 600.0


@dataclass
class DashboardData:
    """What the dashboard shows beyond the feature frame and driver state."""

    now: float = 0.0
    fps: float = 0.0
    session_s: float = 0.0
    calibrating: float = -1.0
    score_history: Sequence[tuple[float, float]] = ()
    co2_history: Sequence[tuple[float, float]] = ()
    co2_connected: bool = False
    co2_ppm: Optional[float] = None
    co2_age_s: Optional[float] = None
    temp_c: Optional[float] = None
    rh: Optional[float] = None
    co2_elevated_ppm: float = 1000.0
    co2_high_ppm: float = 1500.0
    score_ticks: Sequence[float] = ()
    perclos_ticks: Sequence[float] = ()
    eye_closed_fraction: float = 0.50
    # Each is False, True, or for sound, None: no speaker to play through.
    ir_on: bool = False
    blue_on: bool = False
    mist_on: bool = False
    sound_on: Optional[bool] = False
    alerts_on: bool = True
    stage: int = 0
    stage_name: str = "none"
    last_alert: str = ""
    plan: Any = None
    components: dict[str, float] = field(default_factory=dict)
    calibration_hint: str = ""
    note: str = ""                            # small print for the presenter
    notice: str = ""                          # e.g. why the last calibration didn't work
    volume: Optional[int] = None              # the speaker, %; None: no mixer found
    pi_celsius: Optional[float] = None        # the Pi's chip; None off a Pi
    pi_warm: bool = False


def level_words(name: str) -> str:
    return _LEVEL_WORDS.get(name, name.replace("_", " ").upper())


def co2_status(data: DashboardData) -> str:
    """offline, waiting, stale or live: never show an old value as current."""
    if data.co2_ppm is None:
        return "waiting" if data.co2_connected else "offline"
    if data.co2_age_s is not None and data.co2_age_s > _CO2_STALE_S:
        return "stale"
    return "live"


def plan_words(plan) -> tuple[str, bool]:
    """The rest plan as a judge should read it, and whether it is urgent."""
    if plan is None:
        return "collecting trend data", False
    if not plan.valid:
        reason = str(getattr(plan, "reason", ""))
        if reason.startswith(("need", "insufficient")):
            return "collecting trend data", False
        return reason, False
    return plan.summary(), bool(plan.recommend_rest_now)


def _status_line(ff, state, data: DashboardData) -> tuple[str, tuple[int, int, int]]:
    if data.calibrating >= 0.0:
        if data.calibration_hint:
            return data.calibration_hint, _WARN
        return "look at the road, blink normally", _WHITE
    if state.face_lost:
        return "DRIVER NOT VISIBLE", _BAD
    if state.microsleep_now:
        return f"EYES CLOSED {ff.ongoing_closure_s:0.1f}s", _BAD
    if state.distracted:
        return "EYES OFF ROAD", _colour_for_level(2)
    if data.notice:
        return data.notice, _WARN
    return "", _WHITE


def _t(img, text: str, x: int, y: int, scale: float = 0.5, colour=_WHITE,
       thickness: int = 1) -> None:
    import cv2

    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, colour,
                thickness, cv2.LINE_AA)


def _card(img, x: int, y: int, w: int, h: int, title: str) -> None:
    import cv2

    cv2.rectangle(img, (x, y), (x + w, y + h), _CARD, -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), _EDGE, 1)
    _t(img, title, x + 12, y + 20, 0.46, _GREY)


def _ticks(img, x: int, y: int, w: int, h: int, fracs: Sequence[float]) -> None:
    import cv2

    for frac in fracs:
        tx = x + int(w * max(0.0, min(1.0, frac)))
        cv2.line(img, (tx, y - 2), (tx, y + h + 2), _WHITE, 1)


def _chart(img, x: int, y: int, w: int, h: int, points, now: float,
           window_s: float, lo: float, hi: float, colour,
           limits: Sequence[float] = ()) -> None:
    """A line over the last ``window_s``, newest at the right edge."""
    import cv2

    cv2.rectangle(img, (x, y), (x + w, y + h), (16, 16, 18), -1)

    def py(v: float) -> int:
        frac = (float(v) - lo) / max(hi - lo, 1e-6)
        return y + h - int(h * max(0.0, min(1.0, frac)))

    for limit in limits:
        cv2.line(img, (x, py(limit)), (x + w, py(limit)), _EDGE, 1)
    pts = [(x + w - int(w * (now - t) / window_s), py(v))
           for t, v in points if 0.0 <= now - t <= window_s]
    if len(pts) >= 2:
        cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, colour, 2,
                      cv2.LINE_AA)
    elif pts:
        cv2.circle(img, pts[0], 3, colour, -1, cv2.LINE_AA)
    else:
        _t(img, "collecting data", x + 12, y + h // 2, 0.5, _DIM)


def _light(img, x: int, y: int, w: int, h: int, label: str, on: bool,
           colour, note: str = "") -> None:
    import cv2

    cv2.rectangle(img, (x, y), (x + w, y + h), colour if on else (20, 20, 22), -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), colour if on else _EDGE, 1)
    text = _shorten(f"{label}: {note or ('ON' if on else 'off')}", w - 16, 0.52)
    _t(img, text, x + 8, y + h // 2 + 6, 0.52, (15, 15, 15) if on else _GREY,
       2 if on else 1)


def _state_card(img, x: int, y: int, w: int, h: int, ff, state,
                data: DashboardData) -> None:
    _card(img, x, y, w, h, "DRIVER STATE")
    calibrating = data.calibrating >= 0.0
    colour = _WHITE if calibrating else _colour_for_level(state.level)
    if state.face_lost and not calibrating:
        colour = tuple(int(c * 0.45) for c in colour)
    name = "CALIBRATING" if calibrating else level_words(state.level_name)
    _t(img, name, x + 12, y + 54, 1.15, colour, 3)
    bar_x, bar_w = x + 12, w - 24
    if calibrating:
        _bar(img, bar_x, y + 80, bar_w, 16, data.calibrating, _WHITE)
    else:
        _draw_right(img, f"KSS est. {state.kss:0.1f}", x + w - 12, y + 20, 0.52,
                    _WHITE)
        _t(img, f"drowsiness {state.score:0.2f}", x + 12, y + 76, 0.5,
           _GREY if state.face_lost else _WHITE)
        _draw_right(img, f"confidence {state.confidence:0.2f}", x + w - 12, y + 76,
                    0.46, _GREY)
        _bar(img, bar_x, y + 82, bar_w, 16, state.score, colour)
        _ticks(img, bar_x, y + 82, bar_w, 16, data.score_ticks)
    text, text_colour = _status_line(ff, state, data)
    if text and _text_w(text, 0.66, 2) <= w - 24:
        _t(img, text, x + 12, y + 126, 0.66, text_colour, 2)
    elif text:                           # a longer message: two smaller lines
        lines, cur = [], ""
        for word in text.split():
            nxt = f"{cur} {word}".strip()
            if cur and _text_w(nxt, 0.5) > w - 24:
                lines.append(cur)
                cur = word
            else:
                cur = nxt
        lines.append(cur)
        for i, line in enumerate(lines[:2]):
            _t(img, _shorten(line, w - 24, 0.5), x + 12, y + 110 + 20 * i, 0.5, text_colour)


def _air_card(img, x: int, y: int, w: int, h: int, data: DashboardData) -> None:
    _card(img, x, y, w, h, "CABIN AIR (CO2)")
    status = co2_status(data)
    if status == "offline":
        _t(img, "--", x + 12, y + 62, 1.25, _DIM, 2)
        _t(img, "sensor offline", x + 12, y + 92, 0.56, _DIM)
        return
    if status == "waiting":
        _t(img, "--", x + 12, y + 62, 1.25, _DIM, 2)
        _t(img, "waiting for first reading", x + 12, y + 92, 0.56, _GREY)
        return

    ppm = float(data.co2_ppm)
    if status == "stale":
        colour, note, note_colour = _DIM, f"no new reading for {data.co2_age_s:0.0f} s", _GREY
    elif ppm >= data.co2_high_ppm:
        colour, note, note_colour = _BAD, "HIGH: OPEN WINDOW", _BAD
    elif ppm >= data.co2_elevated_ppm:
        colour, note, note_colour = _WARN, "elevated", _WARN
    else:
        colour, note, note_colour = _GOOD, "normal", _GOOD
    value = f"{ppm:0.0f}"
    _t(img, value, x + 12, y + 62, 1.25, colour, 2)
    _t(img, "ppm", x + 20 + _text_w(value, 1.25, 2), y + 62, 0.52, _GREY)
    _t(img, note, x + 12, y + 92, 0.56, note_colour, 2 if note_colour == _BAD else 1)
    if status == "live":
        if data.temp_c is not None:
            _draw_right(img, f"{data.temp_c:0.1f} C", x + w - 12, y + 44, 0.6, _WHITE)
        if data.rh is not None:
            _draw_right(img, f"{data.rh:0.0f} %RH", x + w - 12, y + 72, 0.6, _WHITE)


def _eyes_card(img, x: int, y: int, w: int, h: int, ff, state,
               data: DashboardData) -> None:
    _card(img, x, y, w, h, "EYES")
    if data.calibrating >= 0.0:
        _t(img, "measuring your open-eye baseline", x + 12, y + 56, 0.54, _GREY)
        return
    if state.face_lost:
        _t(img, "no driver in frame", x + 12, y + 56, 0.56, _BAD)
        _t(img, "no eye data to show", x + 12, y + 84, 0.5, _GREY)
        return
    bar_x, bar_w = x + 12, w - 24
    _t(img, f"eyes closed (PERCLOS) {ff.perclos*100:0.1f}%", x + 12, y + 40, 0.5)
    _bar(img, bar_x, y + 46, bar_w, 10, ff.perclos / _PERCLOS_BAR_MAX, _WHITE)
    _ticks(img, bar_x, y + 46, bar_w, 10,
           [p / _PERCLOS_BAR_MAX for p in data.perclos_ticks])
    _t(img, f"eye opening {ff.ear_norm*100:0.0f}% of baseline", x + 12, y + 76, 0.5)
    _bar(img, bar_x, y + 82, bar_w, 10, ff.ear_norm / _EYE_BAR_MAX, _WHITE)
    _ticks(img, bar_x, y + 82, bar_w, 10, [data.eye_closed_fraction / _EYE_BAR_MAX])
    mid = x + w // 2
    _t(img, f"blinks {ff.blink_rate_per_min:0.0f}/min", x + 12, y + 116, 0.52)
    _t(img, f"blink {ff.mean_blink_duration_s*1000:0.0f} ms", mid, y + 116, 0.52)
    _t(img, f"microsleeps {ff.microsleep_count}", x + 12, y + 142, 0.52)
    _t(img, f"yawns {ff.yawn_count}", mid, y + 142, 0.52)


def _head_card(img, x: int, y: int, w: int, h: int, ff, state,
               data: DashboardData) -> None:
    _card(img, x, y, w, h, "HEAD")
    if data.calibrating >= 0.0 or state.face_lost or not ff.pose_valid:
        _t(img, "--", x + 12, y + 44, 0.52, _DIM)
        return
    _draw_right(img, "OFF ROAD" if ff.off_road else "ON ROAD", x + w - 12, y + 20,
                0.5, _colour_for_level(2) if ff.off_road else _GOOD)
    _t(img, f"yaw {ff.yaw:+0.0f}   pitch {ff.pitch:+0.0f}   roll {ff.roll:+0.0f}   "
            f"gaze {ff.gaze_h:+0.2f}", x + 12, y + 44, 0.52)


def _response_card(img, x: int, y: int, w: int, h: int,
                   data: DashboardData) -> None:
    _card(img, x, y, w, h, "SYSTEM RESPONSE")
    if data.alerts_on:
        stage = f"stage {data.stage}: {data.stage_name}"
        _draw_right(img, stage, x + w - 12, y + 20, 0.5,
                    _colour_for_level(data.stage) if data.stage else _GREY)
    else:
        _draw_right(img, "ALERTS OFF", x + w - 12, y + 20, 0.5, _WARN)
    lw, lh = (w - 36) // 2, 30
    left, right = x + 12, x + 24 + lw
    _light(img, left, y + 30, lw, lh, "IR LED", data.ir_on, (205, 205, 205))
    _light(img, right, y + 30, lw, lh, "BLUE", data.blue_on, _BLUE_ON)
    _light(img, left, y + 66, lw, lh, "MIST", data.mist_on, _GOOD)
    if data.sound_on is None:
        _light(img, right, y + 66, lw, lh, "SOUND", False, _WARN, note="no speaker")
    else:
        _light(img, right, y + 66, lw, lh, "SOUND", data.sound_on, _WARN)
    if data.last_alert:
        _t(img, _shorten(f"last: {data.last_alert}", w - 24, 0.48), x + 12, y + 122,
           0.48, _WHITE)
    else:
        _t(img, "no alerts this session", x + 12, y + 122, 0.48, _GREY)


def _footer_card(img, x: int, y: int, w: int, h: int, state,
                 data: DashboardData) -> None:
    _card(img, x, y, w, h, "REST PLAN")
    words, urgent = plan_words(data.plan)
    _t(img, _shorten(words, w - 24, 0.52), x + 12, y + 42, 0.52,
       _WARN if urgent else _WHITE, 2 if urgent else 1)
    mins, secs = divmod(int(max(data.session_s, 0.0)), 60)
    _t(img, f"session {mins:02d}:{secs:02d}", x + 12, y + 64, 0.46, _GREY)
    fps_text = f"{data.fps:0.1f} fps"
    if data.pi_celsius is not None:
        fps_text = f"Pi {data.pi_celsius:0.0f} C   " + fps_text
    _draw_right(img, fps_text, x + w - 12, y + 64, 0.46, _BAD if data.pi_warm else _GREY)
    if data.note:
        _t(img, _shorten(data.note, w - 24, 0.4), x + 12, y + 84, 0.4, (230, 120, 230))


def _components_card(img, x: int, y: int, w: int, h: int, state,
                     data: DashboardData) -> None:
    _card(img, x, y, w, h, "WHAT DRIVES THE SCORE")
    comps = data.components or getattr(state, "components", None) or {}
    if not comps:
        _t(img, "no evidence yet", x + 12, y + 60, 0.5, _DIM)
        return
    row_y, label_w = y + 46, 112
    top = sorted(comps.items(), key=lambda kv: -float(kv[1]))[:5]
    for name, value in top:
        words = _COMPONENT_WORDS.get(name, name.replace("_", " "))
        _t(img, _shorten(words, label_w, 0.46), x + 12, row_y, 0.46, _WHITE)
        _bar(img, x + 12 + label_w, row_y - 12, w - 36 - label_w, 12, float(value), _WARN)
        row_y += 36


def render_panels(ff, state, data: DashboardData) -> np.ndarray:
    """Everything except the camera image, on a fresh canvas."""
    import cv2

    img = np.full((DASH_H, DASH_W, 3), _BG, np.uint8)
    x = _COL_X
    w = _COL_W
    _state_card(img, x, 8, w, 136, ff, state, data)
    _air_card(img, x, 150, w, 104, data)
    _eyes_card(img, x, 260, w, 152, ff, state, data)
    _head_card(img, x, 418, w, 54, ff, state, data)
    _response_card(img, x, 478, w, 134, data)
    _footer_card(img, x, 618, w, 94, state, data)

    cw = (_CAM_RECT[2] - 12) // 3
    x0, x1, x2 = 8, 8 + cw + 6, 8 + 2 * (cw + 6)
    y, h = _CHART_Y, _CHART_H

    _card(img, x0, y, cw, h, "DROWSINESS, LAST 2 MIN")
    _chart(img, x0 + 8, y + 30, cw - 16, h - 40, data.score_history, data.now,
           _SCORE_WINDOW_S, 0.0, 1.0, _colour_for_level(state.level), data.score_ticks)

    _card(img, x1, y, cw, h, "CO2, LAST 10 MIN")
    peak = max([v for _t_, v in data.co2_history] + [data.co2_high_ppm])
    _chart(img, x1 + 8, y + 30, cw - 16, h - 40, data.co2_history, data.now,
           _CO2_WINDOW_S, _CO2_AXIS_FLOOR, peak * 1.1, _GOOD,
           (data.co2_elevated_ppm, data.co2_high_ppm))

    _components_card(img, x2, y, cw, h, state, data)
    cv2.rectangle(img, (_CAM_RECT[0] - 1, _CAM_RECT[1] - 1),
                  (_CAM_RECT[0] + _CAM_RECT[2], _CAM_RECT[1] + _CAM_RECT[3]), _EDGE, 1)
    return img


def window_to_canvas(x: int, y: int, win_w: int, win_h: int) -> tuple[int, int]:
    """Where a click at (x, y) in a window of that size lands on the dashboard
    canvas: the inverse of fit_to_window."""
    if win_w <= 0 or win_h <= 0 or (win_w, win_h) == (DASH_W, DASH_H):
        return x, y
    scale = min(win_w / DASH_W, win_h / DASH_H)
    ox, oy = (win_w - int(DASH_W * scale)) // 2, (win_h - int(DASH_H * scale)) // 2
    return int((x - ox) / scale), int((y - oy) / scale)


def button_at(x: int, y: int) -> Optional[str]:
    """The dashboard button under canvas point (x, y), if any."""
    for name, (bx, by, bw, bh) in BUTTONS.items():
        if bx <= x <= bx + bw and by <= y <= by + bh:
            return name
    return None


def _buttons(img, volume: Optional[int] = None, hover: Optional[str] = None) -> None:
    import cv2

    x, y, w, h = BUTTONS["vol_down"]
    label = "speaker" if volume is None else f"speaker {volume}%"
    cv2.rectangle(img, (x - _text_w(label, 0.5) - 20, y + 4),
                  (x - 6, y + h - 4), (40, 40, 44), -1)
    _t(img, label, x - _text_w(label, 0.5) - 13, y + h // 2 + 6, 0.5, _WHITE)
    for name, (x, y, w, h) in BUTTONS.items():
        lit = name == hover                    # under the mouse: white, dark text
        cv2.rectangle(img, (x, y), (x + w, y + h), (240, 240, 240) if lit else (40, 40, 44), -1)
        cv2.rectangle(img, (x, y), (x + w, y + h), (255, 255, 255) if lit else (200, 200, 200), 2 if lit else 1)
        text = _BUTTON_WORDS[name]
        _t(img, text, x + (w - _text_w(text, 0.5, 1)) // 2, y + h // 2 + 6, 0.5,
           (30, 30, 34) if lit else _WHITE)


def fit_to_window(canvas: np.ndarray, win_w: int, win_h: int) -> np.ndarray:
    """Scale ``canvas`` to the window ourselves, centred on black.

    Left to Qt, the image is scaled without smoothing, which drops whole rows
    of pixels: on a 1280x673 display the bottom edges of bars and buttons and
    parts of the small text went missing, and the spare width showed as grey.
    """
    import cv2

    h, w = canvas.shape[:2]
    if win_w <= 0 or win_h <= 0 or (win_w, win_h) == (w, h):
        return canvas
    scale = min(win_w / w, win_h / h)
    fw, fh = max(1, int(w * scale)), max(1, int(h * scale))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    out = np.zeros((win_h, win_w, 3), np.uint8)
    ox, oy = (win_w - fw) // 2, (win_h - fh) // 2
    out[oy:oy + fh, ox:ox + fw] = cv2.resize(canvas, (fw, fh), interpolation=interp)
    return out


class Dashboard:
    """Composes the camera into panels that are redrawn only a few times a second.

    The panels are text nobody can read any faster than that, and the loop's
    frame rate is what the blink tracker depends on.
    """

    def __init__(self, refresh_s: float = 0.2) -> None:
        self.refresh_s = float(refresh_s)
        self._panels: Optional[np.ndarray] = None
        self._drawn_at: Optional[float] = None
        self._volume: Optional[int] = None
        self.hover: Optional[str] = None      # the button under the mouse, drawn lit

    def due(self, now: float) -> bool:
        return self._drawn_at is None or now - self._drawn_at >= self.refresh_s

    def refresh(self, ff, state, data: DashboardData) -> None:
        self._panels = render_panels(ff, state, data)
        self._volume = data.volume
        self._drawn_at = data.now

    def compose(self, camera: np.ndarray) -> np.ndarray:
        """Return a new canvas with ``camera`` fitted into its slot."""
        import cv2

        if self._panels is None:
            canvas = np.full((DASH_H, DASH_W, 3), _BG, np.uint8)
        else:
            canvas = self._panels.copy()
        x, y, w, h = _CAM_RECT
        ch, cw = camera.shape[:2]
        scale = min(w / cw, h / ch)
        fw, fh = max(1, int(cw * scale)), max(1, int(ch * scale))
        fitted = cv2.resize(camera, (fw, fh), interpolation=cv2.INTER_LINEAR)
        ox, oy = x + (w - fw) // 2, y + (h - fh) // 2
        canvas[oy:oy + fh, ox:ox + fw] = fitted
        _buttons(canvas, self._volume, self.hover)
        return canvas
