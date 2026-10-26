"""Showcase mode: every feature on a key, on demo-length timings.

    ./tools/run_pi.sh --demo

Live detection keeps running, so a real closure still climbs the ladder, but
nobody can be asked to get drowsy on cue in front of a judge. The keys fire
each stage directly, and ``t`` runs the whole sequence unattended.

Timings are shortened because the real ones are designed for a drive, not a
two-minute demo: a 30-minute blue light, a 20 s mist burst that fogs the
table, and refractory periods that would refuse a second showing.
"""

from __future__ import annotations

import copy
from typing import Any, Optional

HELP = "DEMO  1-4 stage   d glance   w window   0 all off   t tour"

DEFAULTS = {
    "light_hold_s": 20.0,     # blue light stays on this long, not 30 min
    "scent_s": 2.0,           # stage 2-3 burst
    "scent_long_s": 4.0,      # stage 4 burst
    "refractory_s": 3.0,      # ceiling on every actuator's refractory
    "cooldown_s": 8.0,        # ceiling on every stage's cooldown
}

# (seconds after 't', action). Actions: "1".."4" stage, "d", "w", "0".
TOUR = [
    (0.0, "1"),
    (6.0, "2"),
    (13.0, "3"),
    (21.0, "4"),
    (30.0, "d"),
    (34.0, "w"),
    (40.0, "0"),
]

LABELS = {
    "1": "stage 1: blue light",
    "2": "stage 2: + mint burst",
    "3": "stage 3: slow chime + voice",
    "4": "stage 4: looming alarm + voice + long mint",
    "d": "eyes off the road: chime",
    "w": "CO2 high: open the window",
    "0": "all off",
}


def apply_demo(cfg: dict[str, Any], demo: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return a copy of the config with demo-length timings."""
    cfg = copy.deepcopy(cfg)
    d = dict(DEFAULTS)
    d.update(demo or cfg.get("demo") or {})
    alerts = cfg["alerts"]
    for spec in alerts.get("actuators", {}).values():
        if "refractory_s" in spec:
            spec["refractory_s"] = min(float(spec["refractory_s"]), d["refractory_s"])
        spec.pop("max_per_hour", None)
        if spec.get("type") == "light":
            spec["hold_s"] = d["light_hold_s"]
        if spec.get("type") == "atomizer":
            spec["duration_s"] = d["scent_s"]
    for stage in alerts.get("stages", []):
        if "cooldown_s" in stage:
            stage["cooldown_s"] = min(float(stage["cooldown_s"]), d["cooldown_s"])
        for entry in stage.get("actuators", []) or []:
            if isinstance(entry, dict):
                for params in entry.values():
                    if params and "duration_s" in params:
                        params["duration_s"] = d["scent_long_s"]
    return cfg


class Tour:
    """The unattended walk through every feature, driven by the main loop."""

    def __init__(self, steps=TOUR) -> None:
        self.steps = list(steps)
        self._t0: Optional[float] = None
        self._next = 0

    @property
    def running(self) -> bool:
        return self._t0 is not None

    def start(self, now: float) -> None:
        self._t0 = now
        self._next = 0

    def stop(self) -> None:
        self._t0 = None

    def due(self, now: float) -> list[str]:
        if self._t0 is None:
            return []
        out = []
        while self._next < len(self.steps) and now - self._t0 >= self.steps[self._next][0]:
            out.append(self.steps[self._next][1])
            self._next += 1
        if self._next >= len(self.steps):
            self._t0 = None
        return out
