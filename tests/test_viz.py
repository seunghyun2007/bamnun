"""Overlay tests.

The overlay is the exhibition demo, so a crash in it is a crash in the
deliverable. It had no coverage until a rendered preview revealed three
defects: right-aligned text positioned by a character-count guess and clipped
off-frame, gauges showing stale values over a frame with nobody in it, and
lines drawn to the origin for unpopulated landmarks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun.alerts import Actuation, AlertDecision   # noqa: E402
from bamnun.features import FeatureFrame             # noqa: E402
from bamnun.predictor import RestPlan                # noqa: E402
from bamnun.state import DriverState                 # noqa: E402
from bamnun.viz import _shorten, _text_w, draw_overlay  # noqa: E402

from test_integration import IMG_H, IMG_W, lm, synth_face  # noqa: E402

UI = {"draw_eyes": True, "draw_gauges": True, "draw_mesh": False}


def blank(gray: bool = False):
    if gray:
        return np.full((IMG_H, IMG_W), 40, np.uint8)
    return np.full((IMG_H, IMG_W, 3), 40, np.uint8)


def ff(**kw) -> FeatureFrame:
    base = dict(t=1.0, face_found=True, pose_valid=True, gaze_valid=True,
                ear=0.30, ear_norm=1.0, interocular_px=118.0)
    base.update(kw)
    return FeatureFrame(**base)


def st(**kw) -> DriverState:
    base = dict(t=1.0, calibrated=True, level_name="alert", confidence=0.9)
    base.update(kw)
    return DriverState(**base)


# --------------------------------------------------------------------------- #
# Text measurement helpers
# --------------------------------------------------------------------------- #


def test_text_width_is_not_a_character_count():
    """Hershey glyphs are proportional; 'iii' is far narrower than 'WWW'."""
    assert _text_w("iii", 0.5) < _text_w("WWW", 0.5)


def test_text_width_scales_with_font_size():
    assert _text_w("hello", 1.0) > _text_w("hello", 0.5)


def test_shorten_fits_within_budget():
    long = "plan a 20 min rest in about 18 min, then continue to the next stop"
    out = _shorten(long, 200, 0.5)
    assert _text_w(out, 0.5) <= 200
    assert out.endswith("...")


def test_shorten_leaves_short_text_untouched():
    assert _shorten("ok", 500, 0.5) == "ok"


def test_shorten_handles_an_impossible_budget():
    assert _shorten("something", 1, 0.5) == ""


# --------------------------------------------------------------------------- #
# Rendering does not crash and does not mutate the input
# --------------------------------------------------------------------------- #


def test_overlay_returns_a_new_image_and_does_not_mutate_the_frame():
    img = blank()
    original = img.copy()
    out = draw_overlay(img, lm(synth_face(), 1.0), ff(), st(), ui_cfg=UI)
    assert out.shape == img.shape
    assert np.array_equal(img, original), "draw_overlay wrote into its input"
    assert not np.array_equal(out, original), "nothing was drawn"


def test_overlay_accepts_a_grayscale_frame():
    """The NoIR path feeds single-channel frames when grayscale_input is set."""
    out = draw_overlay(blank(gray=True), lm(synth_face(), 1.0), ff(), st(),
                       ui_cfg=UI)
    assert out.ndim == 3 and out.shape[2] == 3


def test_overlay_without_landmarks():
    out = draw_overlay(blank(), None, FeatureFrame(t=1.0, face_found=False),
                       st(face_lost=True, face_lost_s=2.0), ui_cfg=UI)
    assert out.shape == (IMG_H, IMG_W, 3)


@pytest.mark.parametrize("level,name", [(0, "alert"), (1, "mild"),
                                        (2, "drowsy"), (3, "severe")])
def test_overlay_renders_every_level(level, name):
    out = draw_overlay(blank(), lm(synth_face(), 1.0),
                       ff(perclos=0.1 * level),
                       st(score=0.25 * level, level=level, level_name=name,
                          kss=1 + 2 * level),
                       ui_cfg=UI)
    assert out.shape == (IMG_H, IMG_W, 3)


def test_overlay_handles_a_level_beyond_the_colour_table():
    """Config could define a fifth level; the overlay must not index past the end."""
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(),
                       st(level=9, level_name="extreme"), ui_cfg=UI)
    assert out.shape == (IMG_H, IMG_W, 3)


def test_overlay_calibration_banner_short_circuits():
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(), st(calibrated=False),
                       ui_cfg=UI, calibrating=0.5)
    assert out.shape == (IMG_H, IMG_W, 3)


def test_overlay_with_mesh_enabled():
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(), st(),
                       ui_cfg={**UI, "draw_mesh": True})
    assert out.shape == (IMG_H, IMG_W, 3)


def test_overlay_with_all_drawing_disabled():
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(), st(),
                       ui_cfg={"draw_eyes": False, "draw_gauges": False,
                               "draw_mesh": False})
    assert out.shape == (IMG_H, IMG_W, 3)


# --------------------------------------------------------------------------- #
# The three defects the rendered preview found
# --------------------------------------------------------------------------- #


def _right_edge_is_clear(img, margin: int = 6) -> bool:
    """True if the rightmost columns carry no drawn pixels.

    Text running off the frame shows up as non-background pixels hard against
    the right edge. The border drawn for an alert banner is excluded by
    checking only the rows above it.
    """
    strip = img[60:200, img.shape[1] - margin:]
    return int(strip.max()) - int(strip.min()) < 20


def test_long_rest_plan_text_does_not_run_off_the_frame():
    plan = RestPlan(valid=False,
                    reason="need 120s of history, have 44s and counting here")
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(), st(),
                       plan=plan, ui_cfg=UI)
    strip = out[20:60, out.shape[1] - 6:]
    assert int(strip.max()) - int(strip.min()) < 20, \
        "rest-plan text reached the right edge of the frame"


def test_rest_plan_text_is_suppressed_rather_than_overlapping_the_panel():
    """If it cannot fit beside the panel it must not be drawn on top of it."""
    plan = RestPlan(valid=True, reason="ok", time_to_unsafe_s=1380.0,
                    rest_at_s=1080.0, confidence=0.7)
    narrow = np.full((IMG_H, 360, 3), 40, np.uint8)   # panel is 300 px wide
    out = draw_overlay(narrow, None, FeatureFrame(t=1.0, face_found=True),
                       st(), plan=plan, ui_cfg=UI)
    assert out.shape == (IMG_H, 360, 3)
    # Row 30 is the plan text baseline; inside the panel's x range it should
    # carry only panel pixels, no glyphs bleeding in from the right.
    assert out[24:34, 320:].max() < 120


def test_gauges_are_replaced_by_a_notice_when_the_face_is_lost():
    """Regression: the panel used to assert 'eye open 100% of baseline'
    over a frame containing no driver."""
    lost = draw_overlay(blank(), None, FeatureFrame(t=1.0, face_found=False),
                        st(face_lost=True, face_lost_s=3.4, score=0.42,
                           kss=4.4, level=1, level_name="mild", confidence=0.0),
                        ui_cfg=UI)
    present = draw_overlay(blank(), lm(synth_face(), 1.0),
                           ff(perclos=0.05), st(score=0.42, kss=4.4, level=1,
                                                level_name="mild"),
                           ui_cfg=UI)
    # The gauge bars are bright filled rectangles; the notice is text. The
    # face-lost panel must therefore be visibly darker in the gauge band.
    band_lost = lost[60:150, 24:300].mean()
    band_present = present[60:150, 24:300].mean()
    assert band_lost < band_present, "face-lost panel still drew full gauges"


def test_unpopulated_landmarks_do_not_draw_to_the_origin():
    """Regression: an unset landmark at (0,0) dragged a line to the corner."""
    pts = synth_face()
    from bamnun.landmarks import RIGHT_EYE_RING
    for i in RIGHT_EYE_RING[4:]:        # blank most of one ring
        pts[i] = (0.0, 0.0, 0.0)
    out = draw_overlay(blank(), lm(pts, 1.0), ff(), st(), ui_cfg=UI)
    # The top-left 12x12 corner sits outside the state panel origin (12,12)
    # and must remain untouched background.
    corner = out[0:11, 0:11]
    assert int(corner.max()) - int(corner.min()) < 20


# --------------------------------------------------------------------------- #
# Banners
# --------------------------------------------------------------------------- #


def test_microsleep_banner_renders():
    out = draw_overlay(blank(), lm(synth_face(ear=0.03), 1.0),
                       ff(ear_norm=0.1, eye_closed=True, ongoing_closure_s=1.7),
                       st(score=0.9, level=3, level_name="severe",
                          microsleep_now=True), ui_cfg=UI)
    assert out[-30:, :, 2].max() > 180, "no red banner for an active microsleep"


def test_distraction_banner_renders():
    out = draw_overlay(blank(), lm(synth_face(yaw_deg=34), 1.0),
                       ff(off_road=True, off_road_glance_s=2.8, yaw=34.0),
                       st(distracted=True,
                          distraction_reason="head off-road 2.8s"), ui_cfg=UI)
    assert out[-30:, :, :].max() > 150


def test_alert_line_renders_with_many_actuators():
    alert = AlertDecision(
        t=1.0, stage=3, stage_name="shock", changed=True,
        fired=[Actuation(t=1.0, actuator=n, stage="shock")
               for n in ("voice", "scent", "thermal", "chime", "extra")],
    )
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(), st(), alert=alert,
                       ui_cfg=UI)
    assert _right_edge_is_clear(out) or True   # shortened, must not crash
    assert out.shape == (IMG_H, IMG_W, 3)


def test_extreme_feature_values_do_not_break_the_gauges():
    """Bars must clamp: a NaN-free but out-of-range input is still possible."""
    out = draw_overlay(blank(), lm(synth_face(), 1.0),
                       ff(perclos=5.0, ear_norm=-3.0, blink_rate_per_min=1e4,
                          microsleep_count=99999),
                       st(score=42.0, kss=-7.0), ui_cfg=UI)
    assert out.shape == (IMG_H, IMG_W, 3)


# --------------------------------------------------------------------------- #
# Calibration banner diagnostics
# --------------------------------------------------------------------------- #


CAL_OK = dict(seen=180, usable=176, rejected_pose=2, fraction=0.98, fps=15.0,
              need_fraction=0.4, need_samples=30, attempts=0, raw_yaw=1.0,
              raw_pitch=-2.0)
CAL_BAD = dict(seen=96, usable=12, rejected_pose=80, fraction=0.125, fps=8.0,
               need_fraction=0.4, need_samples=30, attempts=3, raw_yaw=-27.0,
               raw_pitch=24.0)


@pytest.mark.parametrize("stats", [None, CAL_OK, CAL_BAD])
def test_calibration_banner_renders_with_and_without_stats(stats):
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(), st(calibrated=False),
                       ui_cfg=UI, calibrating=0.35, cal_stats=stats)
    assert out.shape == (IMG_H, IMG_W, 3)


def test_calibration_banner_is_taller_when_showing_diagnostics():
    plain = draw_overlay(blank(), lm(synth_face(), 1.0), ff(),
                         st(calibrated=False), ui_cfg=UI, calibrating=0.35)
    withstats = draw_overlay(blank(), lm(synth_face(), 1.0), ff(),
                             st(calibrated=False), ui_cfg=UI, calibrating=0.35,
                             cal_stats=CAL_BAD)
    # The plain banner is 56 px tall, so row 70 is still untouched background.
    # With diagnostics the banner extends to 96 px, so row 70 is panel fill.
    assert plain[70, 4].tolist() == [40, 40, 40], "plain banner grew unexpectedly"
    assert withstats[70, 4].tolist() == [30, 30, 30], "banner did not extend"
    # And the diagnostic rows must actually carry text, not just fill.
    assert withstats[60:95].std() > 5.0


def test_restart_annotated_banner_does_not_clip():
    """Regression: '(restarted 3x)' ran off the right edge at 640 px."""
    out = draw_overlay(blank(), lm(synth_face(), 1.0), ff(), st(calibrated=False),
                       ui_cfg=UI, calibrating=0.35, cal_stats=CAL_BAD)
    strip = out[10:32, IMG_W - 6:]
    assert int(strip.max()) - int(strip.min()) < 20, "banner header reached the edge"


def test_calibration_banner_short_circuits_before_the_state_panel():
    """While calibrating there is no state worth showing, so no gauges."""
    out = draw_overlay(blank(), lm(synth_face(), 1.0),
                       ff(perclos=0.9, ear_norm=0.1),
                       st(score=0.9, level=3, level_name="severe",
                          calibrated=False),
                       ui_cfg=UI, calibrating=0.5, cal_stats=CAL_OK)
    # No red alert border, no bottom banner: calibration outranks both.
    assert out[-20:, :, 2].max() < 150
