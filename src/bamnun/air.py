"""Cabin CO2 from the SCD41, and when to ask the driver to open a window.

CO2 matters to the alerting rather than being a side measurement: a sealed
cabin climbs past 1500 ppm within tens of minutes with one occupant, and at
those levels people report more sleepiness and do worse on attention tasks.
A scent burst into stale air is fighting the cabin. The response here is the
one a car without controllable vents can still give: a spoken "open the
window", with a lower threshold once the driver is already drowsy.

The sensor is read on a background thread because the SCD41 produces one
sample every 5 s and a blocking I2C read inside the 25 Hz loop would stall a
frame. Without smbus2, or without the sensor on the bus, this is a stub whose
``ppm`` stays None, so the laptop path is unchanged.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

log = logging.getLogger("bamnun.air")

SCD41_ADDR = 0x62
_START_PERIODIC = 0x21B1
_READ_MEASUREMENT = 0xEC05
_STOP_PERIODIC = 0x3F86


def _crc8(data: bytes) -> int:
    """Sensirion CRC-8 (poly 0x31, init 0xFF), one per 16-bit word."""
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def parse_measurement(raw: bytes) -> tuple[int, float, float]:
    """Nine bytes from read_measurement -> (co2 ppm, deg C, %RH).

    Raises ValueError on a CRC mismatch: a corrupted word read as CO2 would
    otherwise fire the prompt on noise.
    """
    if len(raw) != 9:
        raise ValueError(f"expected 9 bytes, got {len(raw)}")
    words = []
    for i in range(0, 9, 3):
        if _crc8(raw[i:i + 2]) != raw[i + 2]:
            raise ValueError("SCD41 CRC mismatch")
        words.append((raw[i] << 8) | raw[i + 1])
    co2, t_raw, rh_raw = words
    return co2, -45.0 + 175.0 * t_raw / 65535.0, 100.0 * rh_raw / 65535.0


class CabinAir:
    def __init__(self, cfg: Optional[dict[str, Any]]) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.bus_no = int(cfg.get("i2c_bus", 1))
        self.prompt_ppm = float(cfg.get("prompt_ppm", 1500.0))
        # Already drowsy: stale air is now part of the problem, so ask sooner.
        self.drowsy_prompt_ppm = float(cfg.get("drowsy_prompt_ppm", 1000.0))
        self.drowsy_level = int(cfg.get("drowsy_level", 2))
        # Re-arm only once the air has visibly improved, or a cabin hovering
        # at the threshold would be told to open the window every refractory.
        self.rearm_drop_ppm = float(cfg.get("rearm_drop_ppm", 200.0))
        self.actuator = str(cfg.get("actuator", "open_window"))

        self.ppm: Optional[float] = None
        self.temp_c: Optional[float] = None
        self.rh: Optional[float] = None
        self.updated_at: Optional[float] = None
        self._armed = True
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._bus = None
        if self.enabled:
            self._open()

    # -- sensor ------------------------------------------------------------ #

    def _open(self) -> None:  # pragma: no cover - hardware only
        try:
            from smbus2 import SMBus, i2c_msg  # type: ignore
        except Exception:  # noqa: BLE001
            log.info("smbus2 absent, CO2 monitoring off")
            return
        try:
            self._bus = SMBus(self.bus_no)
            self._i2c_msg = i2c_msg
            self._cmd(_STOP_PERIODIC)        # a previous run may have left it running
            time.sleep(0.5)
            self._cmd(_START_PERIODIC)
        except Exception as exc:  # noqa: BLE001
            log.warning("SCD41 not answering on i2c-%d: %s", self.bus_no, exc)
            self._bus = None
            return
        self._thread = threading.Thread(target=self._run, name="scd41", daemon=True)
        self._thread.start()
        log.info("SCD41 periodic measurement started")

    def _cmd(self, cmd: int) -> None:  # pragma: no cover
        self._bus.i2c_rdwr(self._i2c_msg.write(SCD41_ADDR, [cmd >> 8, cmd & 0xFF]))

    def _read(self) -> bytes:  # pragma: no cover
        self._cmd(_READ_MEASUREMENT)
        time.sleep(0.002)
        msg = self._i2c_msg.read(SCD41_ADDR, 9)
        self._bus.i2c_rdwr(msg)
        return bytes(list(msg))

    def _run(self) -> None:  # pragma: no cover
        while not self._stop.wait(5.0):
            try:
                co2, temp, rh = parse_measurement(self._read())
            except Exception as exc:  # noqa: BLE001
                log.debug("SCD41 read skipped: %s", exc)
                continue
            if co2 == 0:          # the sensor's "no new data yet"
                continue
            self.ppm, self.temp_c, self.rh = float(co2), temp, rh
            self.updated_at = time.monotonic()

    @property
    def available(self) -> bool:
        return self.ppm is not None

    # -- decision ------------------------------------------------------------ #

    def should_prompt(self, level: int) -> bool:
        """True once per excursion above the threshold that applies now."""
        if self.ppm is None:
            return False
        limit = self.drowsy_prompt_ppm if level >= self.drowsy_level else self.prompt_ppm
        if not self._armed and self.ppm < limit - self.rearm_drop_ppm:
            self._armed = True
        if self._armed and self.ppm >= limit:
            self._armed = False
            return True
        return False

    def close(self) -> None:
        self._stop.set()
        if self._bus is not None:  # pragma: no cover
            try:
                self._cmd(_STOP_PERIODIC)
                self._bus.close()
            except Exception:
                pass
            self._bus = None
