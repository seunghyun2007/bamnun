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
from bamnun.attract import POPUP, POPUP_CLOSE, STEPS, Screens, popup_hit  # noqa: E402
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
        policy=SimpleNamespace(reset=lambda t: "reset", stage=0),
        logger=SimpleNamespace(log_event=lambda kind, payload: events.append(kind)),
        calibrations=[], features=SimpleNamespace(calibrating=False),
        _learn_url="https://example.org/", _learn_after_s=45.0, _learn_hide_s=40.0,
        _tip_after_s=0.0, _tip_hide_s=15.0, _tip_at=None, _tip_shown=False,
        _qr_close_s=60.0, _driven_s=0.0, _learn_shown=False, _popup_at=None, _qr_at=0.0,
        _mode_t=None,
    )
    m.visit = SimpleNamespace(reset=lambda: events.append("visit_reset"))
    m._update_learn_more = lambda now, face: Monitor._update_learn_more(m, now, face)
    m._open_qr = lambda now: Monitor._open_qr(m, now)
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


def test_the_calibration_screen_and_the_drive_page_draw():
    s = Screens(ROOT)
    assert s.calibrating(0.5, 0.4, "still", (1366, 768)).shape == (768, 1366, 3)
    drive = [i for i, step in enumerate(STEPS) if step[0] == "game"]
    assert drive and s.briefing(drive[0], 0.0).shape == (DASH_H, DASH_W, 3)


def drive(m, start: float, seconds: float, face: bool = True) -> float:
    t = start
    while t < start + seconds:
        t += 0.5
        Monitor._update_mode(m, t, face)
    return t


def test_learn_more_pops_up_after_45_s_of_driving_once_per_visitor():
    m, events = stub()
    t = drive(m, 0.0, 30.0)
    assert m._popup_at is None
    m.features.calibrating = True                # calibration doesn't count as driving
    t = drive(m, t, 30.0)
    assert m._popup_at is None
    m.features.calibrating = False
    t = drive(m, t, 16.0)
    assert m._popup_at is not None and "learn_more_popup" in events
    t = drive(m, t, 41.0)                        # nobody clicked: it goes away
    assert m._popup_at is None
    t = drive(m, t, 120.0)
    assert m._popup_at is None                   # not again for the same visitor
    t = drive(m, t, 31.0, face=False)            # they leave: standby
    assert m.mode == "standby" and not m._learn_shown
    Monitor._next(m, t, t)
    m.mode = "live"
    drive(m, t, 46.0)
    assert m._popup_at is not None               # the next visitor gets one


def test_the_qr_screen_closes_on_space_or_by_itself():
    m, events = stub()
    Monitor._open_qr(m, 5.0)
    assert m.mode == "qr" and "learn_more_qr" in events
    Monitor._next(m, 6.0, 6.0)
    assert m.mode == "live"
    Monitor._open_qr(m, 10.0)
    Monitor._update_mode(m, 69.0, True)
    assert m.mode == "qr"
    Monitor._update_mode(m, 71.0, True)
    assert m.mode == "live"


def test_a_click_on_the_popup_opens_the_code_and_the_cross_closes_it():
    x, y, w, h = POPUP
    assert popup_hit(x + 200, y + 100) == "learn_more"
    assert popup_hit(POPUP_CLOSE[0] + 20, POPUP_CLOSE[1] + 20) == "learn_close"
    assert popup_hit(x - 5, y + 10) is None


def test_the_popup_and_a_scannable_qr_code_draw():
    s = Screens(ROOT)
    dash = np.zeros((DASH_H, DASH_W, 3), np.uint8)
    s.learn_popup(dash, 1.0, 1.0)
    x, y, w, h = POPUP
    assert dash[y + h // 2, x + w // 2].any() and not dash[600, 100].any()
    big = np.zeros((1080, 1920, 3), np.uint8)    # drawn at the window's size, where it lands
    s.learn_popup(big, 1.0, 1.0)
    assert big[int((y + h / 2) * 1.5), int((x + w / 2) * 1.5)].any() and not big[900, 150].any()
    url = "https://seunghyun2007.github.io/bamnun/"
    screen = s.learn_more(0.0, url, (1366, 768))
    assert screen.shape == (768, 1366, 3)
    assert cv2.QRCodeDetector().detectAndDecode(screen)[0] == url


def test_next_person_starts_the_briefing_over_with_a_fresh_popup():
    m, events = stub()
    m._driven_s, m._learn_shown, m._popup_at = 80.0, True, 50.0
    Monitor._next_visitor(m, 100.0)
    assert m.mode == "briefing" and m._brief_step == 0 and m._last_alert == "reset"
    assert (m._driven_s, m._learn_shown, m._popup_at) == (0.0, False, None)
    assert "next_visitor" in events


def test_the_next_person_button_is_on_the_dashboard():
    from bamnun.viz import BUTTONS, button_at
    for name in ("next_visitor", "learn_more"):
        x, y, w, h = BUTTONS[name]
        assert button_at(x + w // 2, y + h // 2) == name


def test_a_blocked_camera_is_not_a_head_drop_at_the_booth():
    """2026-11-06: the driver's arm passed in front of the side camera; the
    face vanished right after a jump in the landmarks, which read as a head
    drop and fired stage 4. With head_drop_when_lost off it's just unseen."""
    import yaml
    from bamnun.eyes import NodDetector
    cfg = yaml.safe_load((ROOT / "config" / "default.yaml").read_text())
    nod_cfg = cfg["features"]["nod"]
    assert nod_cfg["head_drop_when_lost"] is False
    for on, expected in ((True, True), (False, False)):
        n = NodDetector({**nod_cfg, "head_drop_when_lost": on})
        t = 0.0
        for p in (0, 0, 2, 6, 10, 14):           # a fast move "down" (the arm drags the mesh) ...
            t += 0.07
            n.update(t, float(p), 0.9)
        assert n.lost(t + 0.07) is expected      # ... then the face is gone


def test_stage_cards_play_on_the_device_one_at_a_time():
    from bamnun.control import SHOWCASE_STAGES
    m, events = stub()
    sent = []
    m.controller = SimpleNamespace(handle=lambda cmd, t, face: sent.append(cmd))
    m._stage_play = (0, 0.0, 0.0)
    m.mode, m._qr_at = "qr", 0.0
    Monitor._play_stage(m, 3, 10.0, 10.0)
    assert sent == list(SHOWCASE_STAGES[3][0]) and m._stage_play[0] == 3
    assert m._qr_at == 10.0 and "qr_stage" in events          # stays open while used
    Monitor._play_stage(m, 4, 11.0, 11.0)                     # still playing 3: ignored
    assert len(sent) == len(SHOWCASE_STAGES[3][0])
    Monitor._play_stage(m, 4, 10.0 + SHOWCASE_STAGES[3][1] + 0.1, 20.0)
    assert sent[-1] == SHOWCASE_STAGES[4][0][-1]


def test_clicks_on_the_learn_more_screen_find_the_cards_and_back():
    from bamnun.attract import QR_BACK, _card_rect, learn_hit
    for size, k in (((1280, 720), 1.0), ((1920, 1080), 1.5)):
        for n in (1, 2, 3, 4):
            x, y, w, h = _card_rect(n)
            assert learn_hit(int((x + w / 2) * k), int((y + h / 2) * k), size) == f"stage{n}"
        x, y, w, h = QR_BACK
        assert learn_hit(int((x + w / 2) * k), int((y + h / 2) * k), size) == "qr_back"
        assert learn_hit(int(100 * k), int(100 * k), size) is None


def test_the_learn_more_screen_lights_the_playing_card():
    s = Screens(ROOT)
    url = "https://seunghyun2007.github.io/bamnun/"
    idle = s.learn_more(0.0, url, (1280, 720))
    lit = s.learn_more(0.0, url, (1280, 720), playing=2, progress=0.5)
    from bamnun.attract import _card_rect
    x, y, w, h = _card_rect(2)
    assert lit[y + 5, x + 5].mean() > 200 and idle[y + 5, x + 5].mean() < 100


def test_booth_screens_pause_the_ladder_and_coming_back_starts_fresh():
    from bamnun.app import QUIET_AFTER_SCREEN_S
    resets, cleared = [], []
    m = SimpleNamespace(mode="live", _seen_mode="live", _last_alert=None, _quiet_until=0.0,
                        policy=SimpleNamespace(reset=lambda t: resets.append(t) or "reset"),
                        features=SimpleNamespace(_reset_live=lambda: cleared.append(1)))
    Monitor._mode_changed(m, 1.0, 1.0)
    assert resets == []
    m.mode = "qr"
    Monitor._mode_changed(m, 2.0, 2.0)                     # into the QR screen: lights off
    assert resets == [2.0] and cleared == []
    m.mode = "live"
    Monitor._mode_changed(m, 30.0, 30.0)                   # back: fresh, and quiet a while
    assert resets == [2.0, 30.0] and cleared == [1]
    assert m._quiet_until == 30.0 + QUIET_AFTER_SCREEN_S


def test_hover_lights_up_what_the_mouse_is_on():
    from bamnun.attract import _card_rect
    from bamnun.viz import BUTTONS, Dashboard
    s = Screens(ROOT)
    url = "https://example.org/"
    x, y, w, h = _card_rect(1)
    plain = s.learn_more(0.0, url, (1280, 720))
    lit = s.learn_more(0.0, url, (1280, 720), hover="stage1")
    assert lit[y + 10, x + 10].mean() > plain[y + 10, x + 10].mean() + 20
    d = Dashboard()
    cam = np.zeros((480, 640, 3), np.uint8)
    bx, by, bw, bh = BUTTONS["calibrate"]
    a = d.compose(cam)[by + 3, bx + 3].mean()
    d.hover = "calibrate"
    b = d.compose(cam)[by + 3, bx + 3].mean()
    assert b > a + 100


def test_the_sleepy_tip_comes_first_then_learn_more():
    m, events = stub()
    voices = []
    m._voice = lambda key, t: voices.append(key)
    m._tip_after_s, m._learn_after_s = 20.0, 60.0
    t = drive(m, 0.0, 21.0)
    assert m._tip_at is not None and voices == ["sleepy_voice"] and "sleepy_tip" in events
    m.policy.stage = 4                           # they shut their eyes: an alert answers it
    t = drive(m, t, 1.0)
    assert m._tip_at is None
    m.policy.stage = 0
    t = drive(m, t, 40.0)
    assert m._popup_at is not None and voices == ["sleepy_voice"]   # once per visitor


def test_the_centring_page_knows_a_good_fit():
    from bamnun.attract import face_fit
    assert face_fit(None) == "none"
    assert face_fit((0.5, 0.5, 0.3)) == "good"
    assert face_fit((0.85, 0.5, 0.3)) == "off"
    assert face_fit((0.5, 0.5, 0.08)) == "far"
    assert face_fit((0.5, 0.5, 0.8)) == "near"
    s = Screens(ROOT)
    i = [k for k, st in enumerate(STEPS) if st[0] == "center"][0]
    cam = np.zeros((480, 640, 3), np.uint8)
    assert s.briefing(i, 0.0, (1280, 720), cam, (0.5, 0.5, 0.3)).shape == (720, 1280, 3)
    assert not any(st[0] == "sleepy" for st in STEPS)    # now a tip while driving


def test_the_guided_tour_walks_every_part_then_hands_back():
    from bamnun.attract import TOUR
    m, events = stub()
    m._popup_at = m._tip_at = None
    Monitor._start_tour(m, 0.0)
    assert m.mode == "tour" and m._tour_step == 0 and "tour" in events
    for i in range(1, len(TOUR)):
        Monitor._next(m, float(i), float(i))
        assert m._tour_step == i
    Monitor._next(m, 99.0, 99.0)
    assert m.mode == "live"


def test_each_tour_step_draws_with_its_part_lit():
    from bamnun.attract import TOUR
    s = Screens(ROOT)
    for i, ((x, y, w, h), *_rest) in enumerate(TOUR):
        c = np.full((1080, 1920, 3), 200, np.uint8)
        s.tour_overlay(c, i, 0.0, 1.0)
        inside = c[int((y + h / 2) * 1.5), int((x + w / 2) * 1.5)]
        assert inside.mean() >= 195 or i == 0          # the card may sit on a corner
        assert c[3, 1917].mean() < 120 or x + w > 1270  # elsewhere dimmed
