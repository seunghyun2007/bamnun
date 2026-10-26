"""Showcase mode: demo timings and the unattended tour."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import EscalationPolicy, stage_entries  # noqa: E402
from bamnun.demo import LABELS, TOUR, Tour, apply_demo  # noqa: E402
from bamnun.session import load_config  # noqa: E402


def _demo_alerts():
    cfg = apply_demo(load_config())["alerts"]
    for spec in cfg["actuators"].values():
        if spec.get("type") == "audio":
            spec["type"] = "null"
    return cfg


def test_demo_shortens_timings_without_touching_the_real_config():
    real = load_config()
    demo = apply_demo(real)
    acts = demo["alerts"]["actuators"]
    assert acts["blue_light"]["hold_s"] <= 30.0
    assert acts["scent"]["duration_s"] <= 5.0
    assert all(spec.get("refractory_s", 0.0) <= 3.0 for spec in acts.values())
    long_burst = [p["duration_s"] for s in demo["alerts"]["stages"]
                  for _, p in stage_entries(s) if p and "duration_s" in p]
    assert long_burst and max(long_burst) <= 5.0
    assert real["alerts"]["actuators"]["blue_light"]["hold_s"] == 1800.0


def test_every_stage_can_be_shown_twice_in_a_row():
    pol = EscalationPolicy(_demo_alerts())
    for stage in (1, 2, 3, 4):
        assert pol.trigger(stage, 0.0 + 10 * stage).fired
        again = pol.trigger(stage, 5.0 + 10 * stage)
        assert again.fired, f"stage {stage} refused a second showing: {again.suppressed}"


def test_reset_turns_the_blue_light_off():
    pol = EscalationPolicy(_demo_alerts())
    pol.trigger(1, 0.0)
    assert pol.actuators["blue_light"].is_on
    d = pol.reset(1.0)
    assert pol.stage == 0 and d.changed
    assert not pol.actuators["blue_light"].is_on


def test_tour_walks_every_action_once_then_stops():
    tour = Tour()
    tour.start(100.0)
    seen = []
    t = 100.0
    while t < 100.0 + TOUR[-1][0] + 1:
        seen += tour.due(t)
        t += 0.25
    assert seen == [a for _, a in TOUR]
    assert not tour.running
    assert set(seen) <= set(LABELS)
