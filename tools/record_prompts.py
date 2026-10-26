#!/usr/bin/env python3
"""Record the spoken prompts with the INMP441 and save them in assets/voice/.

    python3 tools/record_prompts.py                    # every prompt, in order
    python3 tools/record_prompts.py --only open_window # just one
    python3 tools/record_prompts.py --list

For each prompt: the phrase is printed, a chime plays, the mic records for
--seconds, a second chime marks the end, and the clip is trimmed, levelled and
played back. Run it again with --only to redo one.

A familiar voice is more arousing than a synthetic one, which is itself a
testable claim, so these are recorded by the team rather than generated.

The INMP441 has its L/R pin tied to GND, so speech is on one channel of the
stereo capture; the louder channel is kept and copied to both speakers.
Stdlib only, so it runs without the venv.
"""
from __future__ import annotations

import argparse
import array
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "voice"
BEEP = ROOT / "assets" / "chime.wav"
CAPTURE = "plughw:CARD=sndrpigooglevoi,DEV=0"
RATE = 48000

# name -> (when it plays, suggested phrase). Say it however suits the demo.
PROMPTS = {
    "open_window": ("CO2 above the limit", "Open the window, the air is stale."),
    "stage3": ("stage 3, after the slow chime", "You're getting drowsy. Find a rest stop."),
    "stage4": ("stage 4, after the looming beeps", "Wake up! Pull over now."),
    "rest_soon": ("rest planner says stop soon", "Plan a break in the next few minutes."),
    "calibrate": ("calibration starts", "Look straight ahead and blink normally."),
    "calibrated": ("calibration finished", "Calibration done. Drive safely."),
}

FRAME_S = 0.02                # 20 ms analysis frames
SPEECH_REL = 0.12             # a frame is speech above this fraction of the loudest
PAD_S = 0.12                  # kept either side of the speech
TARGET_PEAK = 0.6             # of full scale; the amps clip hard above ~0.8


def read_channels(path: Path) -> list[list[float]]:
    with wave.open(str(path), "rb") as w:
        ch, width, n = w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    code = {2: "h", 4: "i"}[width]
    data = array.array(code, raw)
    full = float(2 ** (8 * width - 1))
    return [[v / full for v in data[c::ch]] for c in range(ch)]


def trim_and_level(x: list[float]) -> list[float]:
    """Remove DC, cut leading/trailing silence, normalise the peak."""
    if not x:
        return x
    mean = sum(x) / len(x)
    x = [v - mean for v in x]
    step = int(RATE * FRAME_S)
    rms = [math.sqrt(sum(v * v for v in x[i:i + step]) / step)
           for i in range(0, len(x) - step + 1, step)]
    if not rms or max(rms) <= 0.0:
        return x
    loud = [i for i, r in enumerate(rms) if r >= SPEECH_REL * max(rms)]
    pad = int(PAD_S / FRAME_S)
    a = max(0, loud[0] - pad) * step
    b = min(len(x), (loud[-1] + 1 + pad) * step)
    x = x[a:b]
    peak = max(abs(v) for v in x) or 1.0
    g = TARGET_PEAK / peak
    fade = int(RATE * 0.01)
    out = []
    for i, v in enumerate(x):
        env = min(1.0, i / fade, (len(x) - 1 - i) / fade) if fade else 1.0
        out.append(v * g * env)
    return out


def write_stereo(path: Path, mono: list[float]) -> None:
    samples = array.array("h")
    for v in mono:
        s = int(32767 * max(-1.0, min(1.0, v)))
        samples.extend((s, s))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())


def play(path: Path) -> None:
    subprocess.run(["aplay", "-q", str(path)], check=False)


def record_one(name: str, seconds: float, playback: bool) -> Path:
    when, phrase = PROMPTS[name]
    print(f"\n[{name}]  plays when: {when}")
    print(f'  say: "{phrase}"', flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav"
        play(BEEP)
        print("  recording...", flush=True)
        subprocess.run(["arecord", "-q", "-D", CAPTURE, "-f", "S32_LE", "-r", str(RATE),
                        "-c", "2", "-d", str(int(math.ceil(seconds))), str(raw)], check=True)
        play(BEEP)
        chans = read_channels(raw)
    speech = max(chans, key=lambda c: sum(v * v for v in c))
    clip = trim_and_level(speech)
    out = OUT_DIR / f"{name}.wav"
    write_stereo(out, clip)
    print(f"  saved {out.relative_to(ROOT)} ({len(clip) / RATE:.2f}s)")
    if len(clip) / RATE > 2.5:
        print("  note: over 2.5 s; a long prompt is a distraction in its own right")
    if playback:
        play(out)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", action="append", choices=sorted(PROMPTS),
                   help="record just this prompt (repeatable)")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--no-playback", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args(argv)
    if args.list:
        for name, (when, phrase) in PROMPTS.items():
            have = "x" if (OUT_DIR / f"{name}.wav").exists() else " "
            print(f"[{have}] {name:12s} {when:34s} \"{phrase}\"")
        return 0
    for name in args.only or list(PROMPTS):
        record_one(name, args.seconds, playback=not args.no_playback)
    return 0


if __name__ == "__main__":
    sys.exit(main())
