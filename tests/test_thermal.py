"""The Pi's temperature and power warnings (thermal.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.thermal import PiHealth  # noqa: E402


@pytest.mark.parametrize("celsius,throttled,under,level", [
    (None, False, False, "ok"), (60.0, False, False, "ok"), (76.0, False, False, "warm"),
    (81.0, False, False, "hot"), (60.0, True, False, "hot"), (60.0, False, True, "power")])
def test_levels(celsius, throttled, under, level):
    h = PiHealth({})
    h.celsius, h.throttled, h.under_voltage = celsius, throttled, under
    assert h.level == level


def test_off_a_pi_it_reads_nothing_and_stays_ok(monkeypatch, tmp_path):
    monkeypatch.setattr("bamnun.thermal.TEMP_FILE", tmp_path / "missing")
    h = PiHealth({})
    h.update(0.0)
    assert h.celsius is None and h.level == "ok"


def test_the_temperature_file_is_read(monkeypatch, tmp_path):
    f = tmp_path / "temp"
    f.write_text("81234\n")
    monkeypatch.setattr("bamnun.thermal.TEMP_FILE", f)
    h = PiHealth({})
    h.update(0.0)
    assert h.celsius == pytest.approx(81.234) and h.level == "hot"


def test_the_warning_bar_sits_above_the_screen_without_covering_it():
    pytest.importorskip("cv2")
    from bamnun.attract import Screens, health_banner

    canvas = np.zeros((720, 1280, 3), np.uint8)
    out = health_banner(Screens(Path(__file__).resolve().parents[1]), canvas, "hot", 82.0)
    assert out.shape == canvas.shape            # same window, the screen fitted under the bar
    assert out[5].any() and not out[400].any()
    assert health_banner(None, canvas, "ok", 50.0) is canvas
