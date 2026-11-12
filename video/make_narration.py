"""Ollie's Korean narration for the video (Supertonic voice M1, like the device)."""
import json, tempfile, wave, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_voice import tidy, resample, write_stereo, RATE   # same processing as the device's lines
from supertonic import TTS

here = Path(__file__).parent
lines = json.loads((here / "script.json").read_text())
tts = TTS(); style = tts.get_voice_style("M1")
out = json.loads((here / "audio" / "durations.json").read_text()) if (here / "audio" / "durations.json").exists() else {}
only = set(sys.argv[1:])
for ln in lines:
    if only and ln["id"] not in only: continue
    wav, _ = tts.synthesize(ln.get("say", ln["ko"]), voice_style=style, lang="ko", speed=0.97)
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        tts.save_audio(wav, tmp.name)
        with wave.open(tmp.name, "rb") as w:
            rate = w.getframerate()
    x = resample(tidy(np.asarray(wav).reshape(-1), rate), rate)
    write_stereo(here / "audio" / f"{ln['id']}.wav", x)
    out[ln["id"]] = round(len(x) / RATE, 2)
    print(ln["id"], out[ln["id"]], ln["ko"])
(here / "audio" / "durations.json").write_text(json.dumps(out, indent=1))
