"""The v2 soundtrack, built on the film's own timeline (timeline.json).

Ollie's narration on top; an original bed underneath (warm pad, soft sub pulse
and a sparse felt-piano motif at 80 BPM), ducked under the voice; UI sounds
synthesized here on the picture's cues; the device's real sounds on stages 3
and 4 (the slow chime, its recorded warning, the rising alarm).

    python3 make_timeline.py && python3 make_audio.py     -> audio/mix.wav (48 kHz stereo)
"""
import json
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
ASSETS = HERE.parent / "assets"
TL = json.loads((HERE / "timeline.json").read_text())
S, C, END = TL["scenes"], TL["cues"], TL["end"]
RATE = 48000
N = int(END * RATE)
T = np.arange(N) / RATE
voice, music, fx = np.zeros((N, 2)), np.zeros((N, 2)), np.zeros((N, 2))
rng = np.random.default_rng(5)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2" if sw == 2 else "<i4").astype(np.float64) / (32768.0 if sw == 2 else 2 ** 31)
    x = x.reshape(-1, ch)
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    if rate != RATE:
        t = np.arange(int(len(x) * RATE / rate)) / RATE
        x = np.stack([np.interp(t, np.arange(len(x)) / rate, x[:, c]) for c in range(2)], axis=1)
    return x[:, :2]


def place(bus: np.ndarray, x: np.ndarray, t: float, gain: float = 1.0, pan: float = 0.0) -> None:
    if x.ndim == 1:
        x = np.stack([x * (1 - max(0, pan)), x * (1 + min(0, pan))], axis=1)
    i = max(0, int(t * RATE))
    j = min(N, i + len(x))
    if j > i:
        bus[i:j] += x[: j - i] * gain


def lowpass(x: np.ndarray, cutoff, order: int = 2) -> np.ndarray:
    """Zero-phase low-pass by FFT (cutoff in Hz)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    return np.fft.irfft(X / (1 + (f / cutoff) ** (2 * order)), len(x))


def smooth(x: np.ndarray, seconds: float) -> np.ndarray:
    k = max(1, int(seconds * RATE))
    return np.convolve(x, np.ones(k) / k, mode="same")


def ramp(t0: float, t1: float) -> np.ndarray:
    return np.clip((T - t0) / max(t1 - t0, 1e-6), 0, 1)


# ---------------------------------------------------------------- sounds
def tick(f: float = 1700, g: float = 0.1, d: float = 0.07) -> np.ndarray:
    n = int(d * RATE)
    t = np.arange(n) / RATE
    return (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.01 * t)) * np.exp(-t / 0.014) * np.minimum(1, t / 0.001) * g


def whoosh(d: float = 0.9, g: float = 0.05, lo: float = 500, hi: float = 2600) -> np.ndarray:
    """Filtered noise that swells and opens, for the container's morphs."""
    n = int(d * RATE)
    x = rng.standard_normal(n)
    a, b = lowpass(x, lo), lowpass(x, hi)
    k = np.linspace(0, 1, n)
    return (a * (1 - k) + b * k) * np.sin(np.pi * k) ** 2 * g


def thump(g: float = 0.5, f: float = 52) -> np.ndarray:
    n = int(0.7 * RATE)
    t = np.arange(n) / RATE
    return np.sin(2 * np.pi * (f + 60 * np.exp(-t * 28)) * t) * np.exp(-t / 0.16) * np.minimum(1, t / 0.004) * g


def pop(g: float = 0.16) -> np.ndarray:
    n = int(0.22 * RATE)
    t = np.arange(n) / RATE
    return np.sin(2 * np.pi * (500 + 420 * np.exp(-t * 26)) * t) * np.exp(-t / 0.06) * np.minimum(1, t / 0.003) * g


def swipe(g: float = 0.035) -> np.ndarray:
    return whoosh(0.35, g, 1200, 5000)


def note(midi: float, d: float = 2.6, g: float = 0.05) -> np.ndarray:
    """A felt piano: a soft hammer, a few harmonics that die quickly."""
    n = int(d * RATE)
    t = np.arange(n) / RATE
    f = 440 * 2 ** ((midi - 69) / 12)
    x = sum(a * np.sin(2 * np.pi * f * h * t + h) * np.exp(-t / (0.9 / h ** 0.8)) for h, a in ((1, 1), (2, 0.38), (3, 0.14), (4, 0.05)))
    return lowpass(x * np.minimum(1, t / 0.012), 1800) * g


# ---------------------------------------------------------------- the bed: 80 BPM, two bars per chord
BEAT = 60 / 80
BAR2 = BEAT * 8
CHORDS = [([45, 57, 60, 64, 71], "Am9"), ([41, 57, 60, 65, 69], "Fmaj7"), ([48, 55, 60, 64, 71], "Cmaj7"), ([43, 55, 59, 62, 69], "G6")]
MOTIF = [[(0, 76), (3, 72), (5, 71)], [(0, 72), (2.5, 69), (5, 67)], [(0, 71), (3, 67), (4.5, 72)], [(0, 74), (2.5, 71), (5, 69)]]
pad = np.zeros(N)
k = 0
while k * BAR2 < END:
    last = k * BAR2 >= S["I"] - 0.5                                        # the end card resolves on C
    notes = [48, 55, 60, 64, 67] if last else CHORDS[k % 4][0]
    s = int(k * BAR2 * RATE)
    e = min(N, int((k * BAR2 + BAR2 + 2.0) * RATE))
    tt = T[s:e] - k * BAR2
    shape = np.minimum(1, tt / 2.0) * np.clip((BAR2 + 2.0 - tt) / 2.0, 0, 1)
    for i, m in enumerate(notes):
        f = 440 * 2 ** ((m - 69) / 12)
        for det in (-0.35, 0.3):                                           # two slightly detuned voices: warmth
            ff = f * 2 ** (det / 120)
            pad[s:e] += (np.sin(2 * np.pi * ff * tt + i) + 0.22 * np.sin(2 * np.pi * ff * 2 * tt) + 0.07 * np.sin(2 * np.pi * ff * 3 * tt)) \
                * shape * (0.9 if i else 1.3) * (1 + 0.06 * np.sin(2 * np.pi * 0.21 * tt + i))
    if 1 <= k and k * BAR2 > S["C"] - 3 and not last:                      # the motif enters when 밤눈 does
        for beat, m in MOTIF[k % 4]:
            place(music, note(m), k * BAR2 + beat * BEAT, 1.0, pan=0.15 if beat else -0.1)
    if k * BAR2 > S["B"]:
        for beat in (0, 4):                                                # a soft sub pulse on each bar
            place(music, thump(0.07, 44), k * BAR2 + beat * BEAT)
    k += 1
if True:                                                                   # the last phrase, on the end card
    for dt, m in ((0.0, 72), (0.75, 76), (1.5, 79), (3.0, 84)):
        place(music, note(m, 3.5, 0.06), C["logo"] + dt)
pad = lowpass(pad, 1500) * 0.012
music += np.stack([pad, np.roll(pad, 300)], axis=1)
hum = lowpass(rng.standard_normal(N), 110, 3) * 0.5 * ramp(0, 1.2) * (1 - ramp(C["black"] - 0.6, C["black"]))   # the road, in the hook
music += np.stack([hum, hum], axis=1) * 0.5

# the music breathes with the film: silent on the black-out, low under the device's own sounds, out at the end
m_gain = ramp(0, 2.5) * (1 - ramp(C["black"] - 0.5, C["black"])) + ramp(S["B"], S["B"] + 1.5)
m_gain = np.minimum(m_gain, 1) * (1 - 0.7 * (ramp(C["st3"], C["chime"]) - ramp(C["alarmEnd"] - 0.2, C["alarmEnd"] + 1.2))) * (1 - ramp(END - 2.2, END - 0.1))

# ---------------------------------------------------------------- the picture's cues
place(fx, thump(0.38), C["black"] + 0.05)                                  # "단 1초"
for name, t in S.items():
    if name not in ("A", "D"):
        place(fx, whoosh(), t - 0.05, 1.0, pan=0.0)                         # the container morphs
place(fx, whoosh(1.0, 0.07, 300, 3500), C["pushIn"])                       # into the camera
for i, t in enumerate(C["pills"]):
    place(fx, tick(1500 + 60 * i, 0.07 if i < 6 else 0.12), t)
place(fx, thump(0.22, 60), S["C"] + 0.75)                                  # the device lands
place(fx, pop(), C["ollie"] + 0.05)                                        # Ollie hops in
shim = sum(np.sin(2 * np.pi * f * np.arange(int(1.6 * RATE)) / RATE) for f in (2093, 2637, 3136)) * np.sin(np.pi * np.linspace(0, 1, int(1.6 * RATE))) ** 2
place(fx, shim * 0.006, S["D"] + 0.5)                                      # the mesh draws on
for t in C["rows"]:
    place(fx, tick(1700, 0.11), t + 0.05)
for t in C["blinks"]:
    place(fx, tick(2300, 0.045, 0.04), t)
for i, t in enumerate(C["score"]):
    place(fx, tick(880 * 2 ** (i * 2 / 12), 0.1, 0.12), t)                 # the score climbs, a tone higher each step
for t in C["ladder"]:
    place(fx, tick(1300, 0.06), t)
n = int(1.4 * RATE)
tt = np.arange(n) / RATE
place(fx, (np.sin(2 * np.pi * 196 * tt) + 0.5 * np.sin(2 * np.pi * 294 * tt)) * np.minimum(1, tt / 0.3) * np.exp(-tt / 0.6) * 0.07, C["st1"])   # the light comes on
place(fx, whoosh(1.9, 0.07, 2500, 7000) * np.linspace(1, 0.2, int(1.9 * RATE)), C["st2"] + 0.05)                                                    # the mist
place(fx, tick(1500, 0.08), C["st3"])
place(fx, read_wav(ASSETS / "chime_slow.wav") * (1 - np.clip((np.arange(4 * RATE) / RATE - 2.4) / 1.0, 0, 1))[:, None], C["chime"], 0.5)           # the device's real stage-3 chime
place(voice, read_wav(ASSETS / "voice" / "ko" / "stage3.wav"), C["dv3"], 0.85)                                                                       # and its recorded warning
alarm = read_wav(ASSETS / "looming.wav")[int(C["alarmFrom"] * RATE): int((C["alarmFrom"] + C["alarmEnd"] - C["alarm"]) * RATE)]
alarm *= (np.clip(np.arange(len(alarm)) / RATE / 0.3, 0, 1) * np.clip((len(alarm) - np.arange(len(alarm))) / RATE / 0.12, 0, 1))[:, None]
place(fx, alarm, C["alarm"], 1.0)                                          # the device's real alarm
for t in (C["scrTrip"], C["scrIns"]):
    place(fx, swipe(), t)
for t in C["calls"]:
    place(fx, tick(1700, 0.09), t + 0.1)
place(fx, tick(1900, 0.1), C["qr"] + 0.5)
place(fx, swipe(0.03), C["photoB"])
place(fx, thump(0.4, 48), C["logo"])                                       # the logo

# ---------------------------------------------------------------- Ollie, on top; the bed ducks under him
for ln in TL["lines"]:
    if not ln.get("device"):
        place(voice, read_wav(HERE / "audio" / f"{ln['id']}.wav"), ln["start"], 1.0)
env = smooth(np.abs(voice).max(axis=1), 0.03)
env = np.maximum(smooth(env, 0.25), smooth(env, 0.6))                      # fast-ish attack, slow release
duck = 1 - 0.5 * np.clip(env / max(env.max(), 1e-9) * 6, 0, 1)             # about -6 dB under the voice
mix = voice + music * (m_gain * duck)[:, None] + fx
peak = np.abs(mix).max()
mix *= 0.89 / peak
pcm = np.clip(np.round(mix * 32767), -32768, 32767).astype("<i2")
with wave.open(str(HERE / "audio" / "mix.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(pcm.tobytes())
rms = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
print(f"mix.wav {len(mix) / RATE:.1f} s, peak {peak:.2f}; voice {rms(voice[voice.any(axis=1)]):.1f} dB, bed {rms(music * (m_gain * duck)[:, None]):.1f} dB, fx peak {np.abs(fx).max():.2f}")
