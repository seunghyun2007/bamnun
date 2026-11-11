"""The one timeline of the v2 film. Picture (index.html), subtitles and sound
(make_audio.py) all read timeline.json, so they cannot drift apart.

    python3 make_timeline.py        -> timeline.json

Narration starts are set by hand around the measured durations; everything
else (scene changes, stage cues, sound cues) is listed here once.
"""
import json
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
ASSETS = HERE.parent / "assets"
FPS = 30

START = {"s01": 0.9, "s02": 6.5, "s03": 12.6, "s04": 19.2, "s05": 23.5, "s06": 30.0, "s07": 36.1, "s08": 40.4,
         "s09": 42.6, "s10": 44.9, "s11": 52.1, "s12": 56.0, "s13": 60.1, "s14": 64.2, "s15": 72.2}
SCENES = {"A": 0.0, "B": 6.0, "C": 12.1, "P": 18.3, "D": 21.4, "E": 29.7, "F": 35.8, "G": 55.5, "H": 63.8, "I": 71.3}
END = 75.0
CUES = {"black": 4.4, "pushIn": 21.0, "st1": 40.4, "st2": 42.5, "st3": 44.8, "chime": 46.3, "dv3": 49.0,
        "st4": 52.0, "alarm": 52.7, "alarmEnd": 55.3, "alarmFrom": 1.4,   # the alarm rises for 4 s: play its louder 1.4-4.0 s
        "logo": 71.8,
        "pills": [round(7.5 + 0.25 * i, 2) for i in range(7)],          # the 70% fills, one tick each
        "rows": [23.6, 25.5, 27.5], "blinks": [25.9, 26.5, 27.1],        # how it sees: three readouts
        "score": [31.0, 31.9, 32.7, 33.5, 34.3],                        # the score steps 2..6
        "ladder": [36.5, 36.8, 37.1, 37.4],                             # the four steps appear
        "scrTrip": 56.9, "scrIns": 60.2, "calls": [57.3, 58.4, 60.6], "woke": 61.6,   # the phone app
        "photoB": 66.6, "qr": 64.3}


def read_mono(path: Path):
    with wave.open(str(path), "rb") as w:
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64) / 32768.0
    return x.reshape(-1, ch).mean(axis=1), rate


def envelope(path: Path, dur: float | None = None, start: float = 0.0):
    """RMS level per video frame, 0..1."""
    x, rate = read_mono(path)
    x = x[int(start * rate):]
    if dur:
        x = x[: int(dur * rate)]
    hop = rate // FPS
    e = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2)) for i in range(0, len(x) - hop, hop)])
    return [round(float(v), 3) for v in e / max(e.max(), 1e-9)]


def pause_after(path: Path, lo: float, hi: float) -> float:
    """Middle of the longest quiet stretch between lo and hi seconds (the gap between two sentences)."""
    x, rate = read_mono(path)
    hop = rate // 100
    e = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2)) for i in range(0, len(x) - hop, hop)])
    quiet = e < 0.04 * e.max()
    best, run, start = (0, 0), 0, 0
    for i in range(int(lo * 100), min(len(quiet), int(hi * 100))):
        if quiet[i]:
            if run == 0:
                start = i
            run += 1
            if run > best[0]:
                best = (run, start)
        else:
            run = 0
    return (best[1] + best[0] / 2) / 100


lines = json.loads((HERE / "script.json").read_text())
dur = json.loads((HERE / "audio" / "durations.json").read_text())
out_lines = [{"id": ln["id"], "ko": ln["ko"], "en": ln["en"], "start": START[ln["id"]], "dur": dur[ln["id"]]} for ln in lines]
dv3_len = len(read_mono(ASSETS / "voice" / "ko" / "stage3.wav")[0]) / 48000
# the device's own recorded stage-3 warning, subtitled like a quote
out_lines.append({"id": "dv3", "ko": "“눈이 감기고 있어요. 쉴 곳을 찾아봐요.”", "en": "“Your eyes are closing. Let's find a place to rest.”",
                  "start": CUES["dv3"], "dur": round(dv3_len, 2), "device": True})
out_lines.sort(key=lambda l: l["start"])
for a, b in zip(out_lines, out_lines[1:]):
    assert a["start"] + a["dur"] < b["start"], (a["id"], b["id"], "overlap")

CUES["ollie"] = round(START["s03"] + pause_after(HERE / "audio" / "s03.wav", 1.5, 4.0), 2)   # "저는 ... 올리예요"
tl = {"fps": FPS, "end": END, "scenes": SCENES, "cues": CUES, "lines": out_lines,
      "env": {"dv3": envelope(ASSETS / "voice" / "ko" / "stage3.wav"),
              "alarm": envelope(ASSETS / "looming.wav", CUES["alarmEnd"] - CUES["alarm"], CUES["alarmFrom"])}}
(HERE / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1))
print("timeline.json:", END, "s; Ollie enters at", CUES["ollie"], "; narration", round(sum(l["dur"] for l in out_lines), 1), "s")
