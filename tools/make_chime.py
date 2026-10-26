#!/usr/bin/env python3
"""Write the alert tones in assets/, played through the speakers.

    chime.wav       distraction nudge: two falling tones, 0.6 s. Replaces the
                    piezo buzzer, whose pin (GPIO18) became the I2S bit clock
                    once the MAX98357A amps went in. A falling pair reads as
                    "attention" rather than "error".
    chime_slow.wav  stage 3: four pulses at 1 Hz, the low-urgency advisory
                    rate in ISO 15006 / SAE J2808 guidance.
    looming.wav     stage 4: pulses at 3 Hz, the high-urgency rate, rising
                    30 dB over the clip (55 -> 85 dBA once the volume is set
                    so the end reaches 85 dBA at the driver's head). A rising
                    envelope arouses without the startle that a sudden full-
                    scale alarm causes, and a startle at the wheel is a
                    steering input.

Every fundamental sits in the 500-1000 Hz band the same guidance gives for
penetrating cabin noise without being shrill. Generated rather than committed
as opaque blobs, like the icon. Stdlib only, so it runs on the Pi without the
venv. The absolute loudness is set by the amp gain and ALSA volume, not here:
calibrate it once with a sound-level meter app at the driver's head.
"""
from __future__ import annotations

import array
import math
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
RATE = 48000                  # the I2S card's native rate; no resampling
PEAK = 0.5                    # headroom: the amps clip hard at full scale
ATTACK_S = 0.005              # long enough to avoid a click at onset
LOOMING_RISE_DB = 30.0        # 55 -> 85 dBA


def tone(hz: float, dur: float, gain: float = 1.0, decay_per_s: float = 6.0) -> list[float]:
    """One bell-like tone with a quiet octave partial, click-free at both ends."""
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        env = min(1.0, t / ATTACK_S) * math.exp(-decay_per_s * t)
        env *= min(1.0, (n - i) / (RATE * ATTACK_S))
        x = math.sin(2 * math.pi * hz * t) + 0.3 * math.sin(4 * math.pi * hz * t)
        out.append(gain * env * x / 1.3)
    return out


def silence(dur: float) -> list[float]:
    return [0.0] * int(RATE * dur)


def pulses(hz: float, rate_hz: float, count: int, on_frac: float,
           gains: list[float] | None = None) -> list[float]:
    period = 1.0 / rate_hz
    out: list[float] = []
    for k in range(count):
        g = gains[k] if gains else 1.0
        out += tone(hz, period * on_frac, gain=g, decay_per_s=3.0)
        out += silence(period * (1.0 - on_frac))
    return out


def write(name: str, mono: list[float]) -> None:
    samples = array.array("h")
    for x in mono:
        v = int(PEAK * 32767 * max(-1.0, min(1.0, x)))
        samples.extend((v, v))                      # same on both speakers
    path = ASSETS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())
    print(f"wrote {path} ({len(mono) / RATE:.2f}s)")


def main() -> int:
    write("chime.wav", tone(880.0, 0.25) + tone(660.0, 0.35))
    write("chime_slow.wav", pulses(750.0, rate_hz=1.0, count=4, on_frac=0.35))
    n = 12                                          # 4 s at 3 Hz
    gains = [10 ** (-LOOMING_RISE_DB * (1 - k / (n - 1)) / 20) for k in range(n)]
    write("looming.wav", pulses(900.0, rate_hz=3.0, count=n, on_frac=0.5, gains=gains))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
