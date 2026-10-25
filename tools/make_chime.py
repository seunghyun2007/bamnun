#!/usr/bin/env python3
"""Write assets/chime.wav, the stage-1 notification played through the speakers.

Replaces the piezo buzzer, whose pin (GPIO18) became the I2S bit clock once
the MAX98357A amps went in. Generated rather than committed as an opaque blob,
like the icon. Two falling tones, 0.6 s in total to match the buzzer it
replaces: short enough not to be a distraction in its own right, and a falling
pair reads as "attention" rather than "error".

Stdlib only, so it runs on the Pi without the venv.
"""
from __future__ import annotations

import array
import math
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "chime.wav"
RATE = 48000                  # the I2S card's native rate; no resampling
TONES = [(880.0, 0.25), (660.0, 0.35)]   # (Hz, seconds)
PEAK = 0.5                    # headroom: the amps clip hard at full scale
ATTACK_S = 0.005              # long enough to avoid a click at onset
DECAY_PER_S = 6.0             # bell-like exponential decay


def main() -> int:
    samples = array.array("h")
    for hz, dur in TONES:
        n = int(RATE * dur)
        for i in range(n):
            t = i / RATE
            env = min(1.0, t / ATTACK_S) * math.exp(-DECAY_PER_S * t)
            env *= min(1.0, (n - i) / (RATE * ATTACK_S))   # and no click at the end
            # A quiet octave partial makes it a chime rather than a test tone.
            x = math.sin(2 * math.pi * hz * t) + 0.3 * math.sin(4 * math.pi * hz * t)
            v = int(PEAK * 32767 * env * x / 1.3)
            samples.extend((v, v))                         # same on both speakers

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())
    print(f"wrote {OUT} ({sum(d for _, d in TONES):.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
