"""The booth's standby screen and visitor briefing (attract.py, app.Monitor)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

cv2 = pytest.importorskip("cv2")

from bamnun.app import Monitor  # noqa: E402
from bamnun.attract import STEPS, Screens  # noqa: E402
from bamnun.viz import DASH_H, DASH_W  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_screens_draw_at_dashboard_size_with_or_without_a_korean_font():
    s = Screens(ROOT)
    cam = np.zeros((480, 640, 3), np.uint8)
    assert s.standby(0.0, cam).shape == (DASH_H, DASH_W, 3)
    for i in range(len(STEPS)):
        assert s.briefing(i, 0.0).shape == (DASH_H, DASH_W, 3)
    s.korean = False                       # the English-only fallback
    s._cache.clear()
    assert s.standby(0.0, cam).shape == (DASH_H, DASH_W, 3)


def stub():
    events = []
    m = SimpleNamespace(
        mode="live", _standby_after_s=30.0, _no_face_since=None, _face_since=None,
        _brief_step=0, _brief_at=0.0, _last_alert=None,
        policy=SimpleNamespace(reset=lambda t: "reset"),
        logger=SimpleNamespace(log_event=lambda kind, payload: events.append(kind)),
        calibrations=[],
    )
    m._start_calibration = lambda t: m.calibrations.append(t)
    m._voice = lambda key, t: None
    return m, events


def test_nobody_for_30_s_is_standby_and_it_waits_for_the_visitor():
    m, events = stub()
    Monitor._update_mode(m, 0.0, False)
    Monitor._update_mode(m, 29.0, False)
    assert m.mode == "live"
    Monitor._update_mode(m, 30.5, False)
    assert m.mode == "standby" and m._last_alert == "reset" and "standby" in events
    Monitor._update_mode(m, 40.0, True)          # someone sits down and reads it:
    Monitor._update_mode(m, 60.0, True)          # it stays until they press space
    assert m.mode == "standby"
    Monitor._next(m, 61.0, 61.0)
    assert m.mode == "briefing"


def test_space_runs_the_briefing_then_starts_calibrating():
    m, _ = stub()
    m.mode = "standby"
    Monitor._next(m, 1.0, 1.0)
    assert m.mode == "briefing" and m._brief_step == 0
    for i in range(1, len(STEPS)):
        Monitor._next(m, 1.0 + i, 1.0 + i)
        assert m._brief_step == i
    Monitor._next(m, 10.0, 10.0)                 # the last page
    assert m.mode == "live" and m.calibrations == [10.0]


def test_an_untouched_briefing_closes():
    m, _ = stub()
    m.mode, m._brief_at = "briefing", 0.0
    Monitor._update_mode(m, 50.0, True)
    assert m.mode == "live"


def test_screens_are_drawn_at_the_window_size_not_stretched():
    s = Screens(ROOT)
    cam = np.zeros((480, 640, 3), np.uint8)
    assert s.standby(0.0, cam, (1920, 1080)).shape == (1080, 1920, 3)
    assert s.briefing(4, 0.0, (1366, 768)).shape == (768, 1366, 3)
