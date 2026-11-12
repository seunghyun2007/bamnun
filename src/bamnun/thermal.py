"""The Pi's own health: chip temperature, and whether it's slowing itself down.

A booth runs all day in a warm room. The Pi 5 starts throttling (slowing
the CPU, so detection loses frames) at 85 C, and a weak power supply makes
it do the same. This reads the temperature every few seconds and the
firmware's throttle flags (vcgencmd get_throttled) less often, and says how
worried to be. It only reports; the window shows it (app.py, attract.py).

On a laptop there's no Pi to read: ``celsius`` stays None and the level ok.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("bamnun.thermal")

TEMP_FILE = Path("/sys/class/thermal/thermal_zone0/temp")
# get_throttled bits: now (0-3) and since boot (16-19).
UNDER_VOLTAGE_NOW = 1 << 0
THROTTLED_NOW = 1 << 2


class PiHealth:
    def __init__(self, cfg: Optional[dict[str, Any]] = None) -> None:
        cfg = cfg or {}
        self.warm_c = float(cfg.get("warm_c", 75.0))
        self.hot_c = float(cfg.get("hot_c", 80.0))
        self.every_s = float(cfg.get("every_s", 2.0))
        self.flags_every_s = float(cfg.get("flags_every_s", 10.0))
        self.celsius: Optional[float] = None
        self.throttled = False
        self.under_voltage = False
        self._read_at = -1e9
        self._flags_at = -1e9

    def update(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        if now - self._read_at >= self.every_s:
            self._read_at = now
            try:
                self.celsius = int(TEMP_FILE.read_text().strip()) / 1000.0
            except (OSError, ValueError):
                self.celsius = None
        if now - self._flags_at >= self.flags_every_s:
            self._flags_at = now
            try:
                out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                                     text=True, timeout=2).stdout
                bits = int(out.strip().split("=")[1], 16)
                self.throttled = bool(bits & THROTTLED_NOW)
                self.under_voltage = bool(bits & UNDER_VOLTAGE_NOW)
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass

    @property
    def level(self) -> str:
        """ok, warm, hot (temperature) or power (the supply is too weak)."""
        c = self.celsius
        if self.throttled or (c is not None and c >= self.hot_c):
            return "hot"
        if self.under_voltage:
            return "power"
        if c is not None and c >= self.warm_c:
            return "warm"
        return "ok"
