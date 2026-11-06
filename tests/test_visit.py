"""A booth visitor's drive and photos for their phone (visit.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
cv2 = pytest.importorskip("cv2")

from bamnun.attract import Screens, VISIT_BUTTONS, learn_hit  # noqa: E402
from bamnun.visit import Visit, face_crop  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def face_points():
    xs, ys = np.meshgrid(np.linspace(260, 380, 20), np.linspace(170, 330, 24))
    return np.stack([xs.ravel(), ys.ravel()], axis=1)


def drive(v, seconds, stage_at=None):
    img = np.full((480, 640, 3), 120, np.uint8)
    t = 0.0
    while t < seconds:
        t += 0.1
        stage = 2 if stage_at is not None and stage_at <= t < stage_at + 3 else 0
        v.frame(t, img, face_points(), fit_good=True, eyes_open=True, score=0.3 + 0.5 * (stage > 0),
                stage=stage, microsleeps=1 if stage else 0, face=True)
    return t


def test_a_drive_gets_a_profile_photo_a_caught_photo_and_the_numbers(tmp_path):
    v = Visit(tmp_path, "https://example.org/bamnun/")
    assert v.state == "none" and not v.active
    v.start(0.0)
    drive(v, 30.0, stage_at=15.0)
    assert v.photo is not None and v.caught is not None and v.state == "ask"
    p = v.payload()
    trip = p["trip"]
    assert trip["summary"]["alerts"] == 1 and trip["summary"]["max_stage"] == 2
    assert trip["summary"]["microsleeps"] == 1
    assert 25 < trip["summary"]["drive_s"] < 31 and len(trip["trace"]) >= 14
    assert 29 < trip["summary"]["duration_s"] < 31                # also when the drive starts at t = 0
    assert p["photo"].startswith("data:image/jpeg;base64,") and p["expires"] == "2026-11-24"
    assert len(json.dumps(p)) < 300_000                       # the table's size limit


def test_no_deletes_the_photos_and_a_new_visitor_starts_empty(tmp_path):
    v = Visit(tmp_path, "https://example.org/")
    v.start(0.0)
    drive(v, 12.0)
    v.decline()
    assert v.photo is None and v.caught is None and v.state == "declined"
    v.reset()
    assert v.state == "none" and v.started is None and not v.trace


def test_without_the_keys_it_fails_gracefully(tmp_path):
    v = Visit(tmp_path, "https://example.org/")
    v.start(0.0)
    drive(v, 12.0)
    v.upload()
    assert v.state == "failed"


def test_the_link_is_the_website_with_the_code():
    v = Visit(ROOT, "https://seunghyun2007.github.io/bamnun/")
    v.code = "abcdefghij"
    assert v.link() == "https://seunghyun2007.github.io/bamnun/?v=abcdefghij"


def test_face_crop_is_a_small_square_jpeg():
    img = np.zeros((480, 640, 3), np.uint8)
    jpg = face_crop(img, face_points())
    out = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert out.shape[1] == 320 and abs(out.shape[0] - 320) < 40


def test_the_screen_asks_then_shows_their_own_code():
    s = Screens(ROOT)
    photo = np.full((320, 320, 3), 90, np.uint8)
    ask = s.learn_more(0.0, "https://example.org/", (1280, 720), visit={"state": "ask", "photo": photo, "key": 1})
    x, y, w, h = VISIT_BUTTONS["visit_yes"]
    assert ask[y + h // 2, x + 5].mean() < 80                  # the dark yes button
    assert learn_hit(x + w // 2, y + h // 2, (1280, 720), asking=True) == "visit_yes"
    assert learn_hit(x + w // 2, y + h // 2, (1280, 720), asking=False) is None
    link = "https://seunghyun2007.github.io/bamnun/?v=abcdefghij"
    done = s.learn_more(0.0, "https://example.org/", (1280, 720),
                        visit={"state": "done", "photo": photo, "key": "abcdefghij", "link": link})
    assert cv2.QRCodeDetector().detectAndDecode(done)[0] == link
