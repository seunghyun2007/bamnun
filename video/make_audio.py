"""The film's soundtrack: Ollie's narration on top, a quiet warm pad
underneath, soft UI sounds on the beats, and the device's real chime and
alarm on the wake-up stages. Writes audio/mix.wav (48 kHz stereo)."""
import json
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RATE = 48000
END = 66.6
N = int(END * RATE)
mix = np.zeros((N, 2))


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2" if sw == 2 else "<i4").astype(np.float64)
    x /= 32768.0 if sw == 2 else 2 ** 31
    x = x.reshape(-1, ch)
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    if rate != RATE:
        t = np.arange(int(len(x) * RATE / rate)) / RATE
        x = np.stack([np.interp(t, np.arange(len(x)) / rate, x[:, c]) for c in range(2)], axis=1)
    return x[:, :2]


def place(x: np.ndarray, t: float, gain: float = 1.0) -> None:
    i = int(t * RATE)
    j = min(N, i + len(x))
    if j > i:
        mix[i:j] += x[: j - i] * gain


def env(n: int, a: float, r: float) -> np.ndarray:
    t = np.arange(n) / RATE
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))


# -- the pad: slow chords, 80 BPM, two bars each (A minor, F, C, G) ---------- #
t = np.arange(N) / RATE
chords = [[57, 60, 64], [53, 57, 60], [48, 55, 60], [55, 59, 62]]
bar = 60 / 80 * 4 * 2
pad = np.zeros(N)
for k in range(int(END / bar) + 2):
    notes = chords[k % 4]
    s, e = int(k * bar * RATE), int(min(END, (k + 1) * bar + 1.5) * RATE)
    if s >= N:
        break
    tt = t[s:e] - k * bar
    shape = np.minimum(1, tt / 1.6) * np.minimum(1, np.maximum(0, (bar + 1.5 - tt) / 1.5))
    for m in notes:
        f = 440 * 2 ** ((m - 69) / 12)
        tone = np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2 * tt + 0.3) + 0.5 * np.sin(2 * np.pi * f / 2 * tt)
        pad[s:e] += tone * shape
pad *= 0.022 * np.minimum(1, t / 3) * np.minimum(1, (END - t) / 3)
mix += np.stack([pad, pad], axis=1)

# -- soft sounds ---------------------------------------------------------------- #
rng = np.random.default_rng(3)


def tick(f: float = 1800, g: float = 0.12) -> np.ndarray:
    n = int(0.09 * RATE)
    x = np.sin(2 * np.pi * f * np.arange(n) / RATE) * env(n, 0.002, 0.018) * g
    return np.stack([x, x], axis=1)


def whoosh(d: float = 0.7, g: float = 0.06) -> np.ndarray:
    n = int(d * RATE)
    x = rng.standard_normal(n)
    x = np.convolve(x, np.ones(40) / 40, mode="same")                  # soften
    x *= np.sin(np.pi * np.arange(n) / n) ** 2 * g * 6
    return np.stack([x, x], axis=1)


def pop(g: float = 0.18) -> np.ndarray:
    n = int(0.25 * RATE)
    tt = np.arange(n) / RATE
    x = np.sin(2 * np.pi * (520 + 380 * np.exp(-tt * 30)) * tt) * env(n, 0.003, 0.07) * g
    return np.stack([x, x], axis=1)


for at in (5.8, 11.7, 17.9, 28.5, 33.1, 45.6, 54.1, 61.2):           # scene changes
    place(whoosh(), at - 0.35)
place(pop(), 12.9)                                                   # Ollie pops up
for at in (22.6, 24.4, 26.2, 49.4, 50.5, 51.9):                      # chips
    place(tick(), at)
place(tick(2400, 0.08), 6.4)
rise = np.linspace(0, 1, int(3.4 * RATE))
place(np.stack([np.sin(2 * np.pi * (220 + 220 * rise) * np.arange(len(rise)) / RATE) * rise * 0.03] * 2, axis=1), 29.1)

# the device's real sounds on the stages
assets = HERE.parent / "assets"
place(tick(1200, 0.1), 36.3)                                         # 1: the light comes on
place(whoosh(1.6, 0.05), 38.3)                                       # 2: mist
place(read_wav(assets / "chime.wav"), 40.0, 0.45)                    # 3: chime under the voice line
alarm = read_wav(assets / "looming.wav")[: int(2.4 * RATE)]
alarm *= np.linspace(0.2, 1, len(alarm))[:, None] * np.linspace(1, 0, len(alarm))[:, None] ** 0.3
place(alarm, 43.0, 0.35)                                             # 4: alarm, short

# -- Ollie's narration, on top -------------------------------------------------- #
for ln in json.loads((HERE / "timeline.json").read_text()):
    place(read_wav(HERE / "audio" / f"{ln['id']}.wav"), ln["start"], 1.0)

peak = np.abs(mix).max()
mix *= 0.89 / peak
pcm = np.clip(np.round(mix * 32767), -32768, 32767).astype("<i2")
with wave.open(str(HERE / "audio" / "mix.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(pcm.tobytes())
print("mix.wav", round(len(mix) / RATE, 1), "s, peak was", round(peak, 2))
