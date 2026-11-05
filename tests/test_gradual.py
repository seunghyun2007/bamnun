"""The tuning tools run the same pipeline the device does.

The gradual-detection cases themselves (slight squint, slow blinks, heavy
lids, nods, microsleeps, glances, expressions...) are covered by the
scenario evaluation in tests/test_detection_eval.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun import scenarios  # noqa: E402
from bamnun.session import deep_update, load_config  # noqa: E402


def _tool():
    spec = importlib.util.spec_from_file_location("replay_session", ROOT / "tools" / "replay_session.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _measures(tool, sc):
    """A scenario as the cached measurements a recording would produce."""
    rows = []
    for f in sc.frames:
        rows.append({
            "t": f.t, "face": float(f.face), "mar": f.mar, "yaw": f.yaw, "pitch": f.pitch, "roll": f.roll,
            "pose_valid": 1.0, "gaze_h": 0.0, "gaze_v": 0.0, "gaze_valid": 1.0, "iod": f.iod,
            "ear_l": f.ear_l, "ear_r": f.ear_r, "width_l": f.width_l, "width_r": f.width_r,
            "edge_l": 0.0, "edge_r": 0.0, "edge": float(f.edge), "blink_l": f.blink_l, "blink_r": f.blink_r,
            "squint_l": f.squint_l, "squint_r": f.squint_r, "jaw": f.jaw, "smile": f.smile,
            "cheek": f.cheek, "mouth_width": 0.0, "brightness": f.brightness, "iod_frac": f.iod / 1280.0,
        })
    return {k: np.array([r[k] for r in rows]) for k in tool.FIELDS}


def _markers(sc):
    close = scenarios.CAL_LOOK_S
    return [(0.0, "calibrate_look"), (close, "calibrate_closed"),
            (close + scenarios.CAL_CLOSE_S, "settle"), (scenarios.LEAD_S, sc.name)]


def test_replay_calibrates_from_the_recordings_own_steps_and_scores():
    tool = _tool()
    sc = scenarios.build("heavy_eyelids", "medium", 3, 120.0)
    rows = tool.replay(_measures(tool, sc), load_config(), markers=_markers(sc))
    assert rows[0]["calibrating"] == 1 and any(not r["calibrating"] for r in rows)
    s = tool.summary(rows, _markers(sc))
    body = [x for x in s if x["stretch"] == "heavy_eyelids"][0]
    assert body["max_stage"] >= 1 and body["max_score"] >= 25
    assert body["microsleeps"] == 0


def test_replay_overrides_reach_the_pipeline():
    tool = _tool()
    sc = scenarios.build("heavy_eyelids", "medium", 3, 90.0)
    m, mk = _measures(tool, sc), _markers(sc)
    base = tool.replay(m, load_config(), markers=mk)[-1]["score"]
    heavier = tool.replay(m, deep_update(load_config(), tool.parse_set(["state.weights.heavy_lids=0.9"])),
                          markers=mk)[-1]["score"]
    assert heavier > base
    assert tool.parse_set(["a.b=1.5", "a.c=x"]) == {"a": {"b": 1.5, "c": "x"}}


def test_an_alert_recording_stays_quiet_in_replay():
    tool = _tool()
    sc = scenarios.build("alert", "small", 4, 90.0, fps=15.0)
    rows = tool.replay(_measures(tool, sc), load_config(), markers=_markers(sc))
    scored = [r for r in rows if not r["calibrating"]]
    assert max(r["score"] for r in scored) < 15 and max(r["stage"] for r in scored) == 0
