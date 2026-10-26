"""Debug overlay.

Dual purpose. During development it is how you see why the detector did what
it did. At the exhibition it is the entire visible product, because a judge
standing at your table cannot see a GPIO pin go high. Budget real effort here:
the overlay IS the demo.

Kept deliberately cheap. Drawing the full 478-point mesh costs several
milliseconds per frame on a Pi 5 and adds nothing a judge can read.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from .landmarks import LEFT_EYE_RING, LEFT_IRIS_CENTER, RIGHT_EYE_RING, RIGHT_IRIS_CENTER

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

        if ui_cfg.get("draw_mesh", False):
            for p in pts:
                cv2.circle(canvas, (int(p[0]), int(p[1])), 1, (90, 90, 90), -1)

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

        cv2.putText(canvas, state.level_name.upper(), (x0 + 12, y0 + 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                    tuple(int(c * 0.45) for c in colour) if stale else colour,
                    2, cv2.LINE_AA)
        _draw_right(canvas, f"KSS ~{state.kss:0.1f}", panel_right - 12, y0 + 30,
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
                 f"drowsiness {state.score:0.2f}", threshold=0.55)
            y += 34
            _bar(canvas, x0 + 12, y, panel_w - 24, 10,
                 feature_frame.perclos / 0.30, _WHITE,
                 f"PERCLOS {feature_frame.perclos*100:0.1f}%", threshold=0.5)
            y += 30
            _bar(canvas, x0 + 12, y, panel_w - 24, 10,
                 feature_frame.ear_norm, _WHITE,
                 f"eye open {feature_frame.ear_norm*100:0.0f}% of baseline",
                 threshold=0.65)
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
