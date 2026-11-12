"""Generate Ollie's lines with Supertonic, an offline text-to-speech model.

    pip install supertonic                         # once; downloads ~400 MB of models
    python tools/make_voice.py                     # every line, English and Korean, voice M1
    python tools/make_voice.py --only stage3 --speed 0.95
    python tools/make_voice.py --voice F2 --lang ko

The lines and their wording come from src/bamnun/voice.py, and the clips go
where the device looks for them, assets/voice/<lang>/<key>.wav, in the same
format as tools/record_prompts.py writes: 48 kHz 16-bit stereo, silence
trimmed, peak at 0.6 of full scale (the amps clip above about 0.8). One
voice for both languages, so Ollie sounds like one character. Recording the
team instead is still possible: record_prompts.py overwrites any clip.

Runs on a laptop; the Pi only plays the files. Uses ffmpeg to resample when
it's installed, and plain numpy otherwise.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun.voice import LANGS, LINES, clip_path  # noqa: E402

RATE = 48000
TARGET_PEAK = 0.6
SILENCE = 0.02          # of the clip's peak: quieter than this at the ends is trimmed
PAD_S = 0.08            # kept either side of the speech


def tidy(x: np.ndarray, rate: int) -> np.ndarray:
    """Trim silence at both ends and set the peak, like record_prompts.py."""
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    x = x - x.mean()
    peak = np.abs(x).max() or 1.0
    loud = np.flatnonzero(np.abs(x) >= SILENCE * peak)
    if loud.size:
        pad = int(PAD_S * rate)
        x = x[max(0, loud[0] - pad):loud[-1] + pad]
    return x * (TARGET_PEAK / peak)


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == RATE:
        return x
    if shutil.which("ffmpeg"):
        raw = (x.astype("<f4")).tobytes()
        out = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ar", str(rate), "-ac", "1",
             "-i", "pipe:0", "-ar", str(RATE), "-f", "f32le", "pipe:1"],
            input=raw, capture_output=True, check=True).stdout
        return np.frombuffer(out, dtype="<f4").astype(np.float64)
    t = np.arange(int(len(x) * RATE / rate)) / RATE
    return np.interp(t, np.arange(len(x)) / rate, x)


def write_stereo(path: Path, x: np.ndarray) -> None:
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.repeat(pcm, 2).tobytes())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--voice", default="M1", help="Supertonic voice: M1-M5, F1-F5")
    ap.add_argument("--lang", choices=LANGS, action="append",
                    help="only this language (default: both)")
    ap.add_argument("--only", action="append", choices=sorted(LINES),
                    help="only this line (repeatable)")
    ap.add_argument("--speed", type=float, default=1.0, help="1.0 is normal pace")
    args = ap.parse_args()

    from supertonic import TTS
    tts = TTS()
    style = tts.get_voice_style(args.voice)
    for key in args.only or list(LINES):
        for lang in args.lang or LANGS:
            text = LINES[key][1 if lang == "ko" else 0]
            wav, _ = tts.synthesize(text, voice_style=style, lang=lang, speed=args.speed)
            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
                tts.save_audio(wav, tmp.name)          # learn the model's sample rate
                with wave.open(tmp.name, "rb") as w:
                    rate = w.getframerate()
            x = resample(tidy(np.asarray(wav).reshape(-1), rate), rate)
            path = clip_path(key, lang, ROOT)
            write_stereo(path, x)
            print(f"{lang}/{key}.wav  {len(x) / RATE:4.1f} s  {text}")


if __name__ == "__main__":
    main()
